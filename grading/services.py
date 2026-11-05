"""Grade computation — pure functions over Score/AssessmentItem data, no
view or HTTP concerns. See CLAUDE.md section "Grading Rules" for the
underlying formulas, confirmed against CITCI's actual class record
(grading-system.xlsx).

    component grade = 5 − 4 × (earned ÷ possible)        (1.00 best, 5.00 worst)
    final grade     = Σ (component grade × weight)        weight as a 0–1 fraction
    passing          = final grade ≤ 3.00

All arithmetic is Decimal — never float — per CLAUDE.md's "Use Decimal
everywhere" rule, so results are exact and reproducible.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Prefetch

from academics.models import ClassRosterEntry

from .models import (
    AssessmentItem,
    ClassGradingScheme,
    ComponentCategory,
    GradingComponent,
    GradingTemplate,
    Score,
    ScoreChangeLog,
    SchemeComponentChangeLog,
)

# (component name, category, weight, is_locked) — CITCI's real class record
# (grading-system.xlsx). Only Examination's weight is school-locked; the
# other four are the suggested starting point an instructor can freely
# rename/reweight for their own class (see CLAUDE.md section 4).
DEFAULT_TEMPLATE_COMPONENTS = [
    ("Attendance", ComponentCategory.ATTENDANCE, 5, False),
    ("Quizzes", ComponentCategory.QUIZ, 30, False),
    ("Recitation", ComponentCategory.RECITATION, 15, False),
    ("Project", ComponentCategory.PROJECT, 10, False),
    ("Examination", ComponentCategory.EXAM, 40, True),
]


def ensure_default_grading_template():
    """Creates (or updates) the "CITCI Default" GradingTemplate + its five
    components — used both by the demo seeder (seed_grading_demo, which
    also needs per-item max-score lists for fake scores) and by
    setup_production (which needs the template but none of the fake data)."""
    template, _ = GradingTemplate.objects.update_or_create(
        name="CITCI Default",
        defaults={
            "description": "Attendance 5%, Quizzes 30%, Recitation 15%, Project 10%, Examination 40% "
            "— CITCI's official class record weights.",
            "is_default": True,
            "is_active": True,
        },
    )
    for order, (name, category, weight, is_locked) in enumerate(DEFAULT_TEMPLATE_COMPONENTS, start=1):
        GradingComponent.objects.update_or_create(
            template=template,
            name=name,
            defaults={"category": category, "weight": weight, "is_locked": is_locked, "order": order},
        )
    return template

PASSING_THRESHOLD = Decimal("3.00")


def validate_component_weights(weights):
    """Raise if a template/scheme's component weights don't total exactly
    100% — called from the admin template form's formset clean()."""
    total = sum(weights, Decimal("0"))
    if total != Decimal("100"):
        raise ValidationError(f"Component weights must total 100% (currently {total}%).")


def save_score(roster_entry, item, new_value, user):
    """Create/update one Score, validating against item.max_score and
    writing a ScoreChangeLog entry whenever the value actually changes.
    Returns (score, error_message) — error_message is None on success."""
    score_obj, _ = Score.objects.get_or_create(roster_entry=roster_entry, item=item)
    old_value = score_obj.score

    if new_value is not None and (new_value < 0 or new_value > item.max_score):
        return score_obj, f"Max is {item.max_score}"

    if old_value == new_value:
        return score_obj, None

    score_obj.score = new_value
    score_obj.updated_by = user
    score_obj.save()

    ScoreChangeLog.objects.create(score=score_obj, old_value=old_value, new_value=new_value, changed_by=user)
    return score_obj, None


def component_snapshot(component):
    """Plain-dict snapshot of a SchemeComponent's editable fields, for
    SchemeComponentChangeLog's before/after JSON."""
    return {"name": component.name, "category": component.category, "weight": component.weight}


def ensure_locked_component_unchanged(instance, name, category, weight):
    """Raise if an edit would change a locked component's name/category/
    weight — CITCI policy: Examination's weight (and whichever other
    components an admin locks) is fixed by the school, not the instructor."""
    if instance.pk and instance.is_locked:
        if name != instance.name or category != instance.category or weight != instance.weight:
            raise ValidationError(
                "This component is set by the school and can't be renamed, recategorized, or reweighted."
            )


def check_can_delete_scheme_component(component):
    """Returns (can_delete, reason). A locked component can never be
    deleted; an unlocked one only once none of its items have a score yet
    (matching the single-item delete rule — move or delete those first)."""
    if component.is_locked:
        return False, "This component is set by the school and can't be deleted."
    if component.has_scored_items:
        return False, "This component has scored items — move or delete those items first."
    return True, ""


def delete_scheme_component(component):
    """Delete a component and any assessment items still pointing at it —
    safe to call only after check_can_delete_scheme_component() confirms
    none of those items have scores (AssessmentItem.component is PROTECT)."""
    component.items.all().delete()
    component.delete()


def log_component_change(scheme, action, component_name, user, before=None, after=None):
    SchemeComponentChangeLog.objects.create(
        scheme=scheme, action=action, component_name=component_name, before=before, after=after, changed_by=user
    )


def _component_grade(earned: Decimal, possible: Decimal) -> Optional[Decimal]:
    if possible == 0:
        return None
    return Decimal("5") - Decimal("4") * (earned / possible)


def format_grade(value):
    """Round a raw Decimal grade for display only — full precision is always
    kept on the computed/stored value itself. Decimal places configurable via
    settings.GRADE_DISPLAY_DECIMALS (default 2, e.g. 1.77)."""
    if value is None:
        return None
    places = getattr(settings, "GRADE_DISPLAY_DECIMALS", 2)
    quantum = Decimal("1").scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


@dataclass
class ComponentBreakdown:
    component: object
    final_earned: Decimal
    final_possible: Decimal
    running_earned: Decimal
    running_possible: Decimal
    running_included: bool
    missing_items: list = field(default_factory=list)

    @property
    def final_grade(self) -> Optional[Decimal]:
        return _component_grade(self.final_earned, self.final_possible)

    @property
    def running_grade(self) -> Optional[Decimal]:
        if not self.running_included:
            return None
        return _component_grade(self.running_earned, self.running_possible)


@dataclass
class StudentGradeResult:
    roster_entry: object
    components: list
    missing_items: list = field(default_factory=list)

    @property
    def final_grade(self) -> Optional[Decimal]:
        """All components, all items, blanks count as 0 — never re-normalized."""
        total = Decimal("0")
        any_component = False
        for c in self.components:
            grade = c.final_grade
            if grade is None:
                continue
            any_component = True
            total += grade * (c.component.weight / Decimal("100"))
        return total if any_component else None

    @property
    def running_grade(self) -> Optional[Decimal]:
        """Only components that have at least one encoded item anywhere in
        the class; the remaining components' weights are re-normalized to
        sum to 100%."""
        included = [c for c in self.components if c.running_included]
        if not included:
            return None
        weight_sum = sum((c.component.weight for c in included), Decimal("0"))
        if weight_sum == 0:
            return None
        total = Decimal("0")
        for c in included:
            total += c.running_grade * (c.component.weight / weight_sum)
        return total

    @property
    def is_grade_complete(self) -> bool:
        """True once every component has at least one assessment item and
        every one of those items has a score — i.e. the FINAL grade reflects
        real data, not blanks-counted-as-zero filler. A component with zero
        items (not yet set up) does NOT count as complete."""
        if not self.components:
            return False
        return not self.missing_items and all(c.final_possible > 0 for c in self.components)

    @property
    def remarks(self) -> Optional[str]:
        """PASSED/FAILED only once the grade is final (no missing cells and
        every component has items) — a mid-term FINAL grade with half the
        gradebook still blank is not a real pass/fail, just zeros padding
        out the average, so showing it as "Passed" would be misleading. Until
        then, show a provisional ON_TRACK/AT_RISK based on the RUNNING grade
        (same ≤3.00 threshold), which already ignores unstarted components."""
        if self.roster_entry.status == ClassRosterEntry.Status.DROPPED:
            return "DROPPED"
        if self.roster_entry.is_incomplete:
            return "INC"

        if self.is_grade_complete:
            final = self.final_grade
            if final is None:
                return None
            return "PASSED" if final <= PASSING_THRESHOLD else "FAILED"

        running = self.running_grade
        if running is None:
            return None
        return "ON_TRACK" if running <= PASSING_THRESHOLD else "AT_RISK"

    @property
    def final_remarks(self) -> str:
        """PASSED/FAILED/INC/DROPPED only — the FINAL remark a grade sheet
        snapshot may ever store. Always derived from the FINAL grade (every
        component, every item, blanks count as 0), never the provisional
        ON_TRACK/AT_RISK labels `remarks` shows mid-term — submission must
        never freeze a provisional label into the official record."""
        if self.roster_entry.status == ClassRosterEntry.Status.DROPPED:
            return "DROPPED"
        if self.roster_entry.is_incomplete:
            return "INC"
        final = self.final_grade
        if final is None:
            return "FAILED"
        return "PASSED" if final <= PASSING_THRESHOLD else "FAILED"


def _encoded_item_ids(item_ids):
    """Items with at least one non-null score anywhere in the class — the
    running grade only considers these (spec: "uses only items that have at
    least one score encoded in the class")."""
    if not item_ids:
        return set()
    return set(
        Score.objects.filter(item_id__in=item_ids, score__isnull=False)
        .values_list("item_id", flat=True)
        .distinct()
    )


def _build_breakdown(components, scores_by_item, encoded_item_ids):
    breakdowns = []
    missing_items = []
    for component in components:
        items = list(component.items.all())
        final_earned = Decimal("0")
        final_possible = Decimal("0")
        running_earned = Decimal("0")
        running_possible = Decimal("0")
        running_included = False
        component_missing = []

        for item in items:
            final_possible += item.max_score
            score = scores_by_item.get(item.id)
            if score is None:
                missing_items.append(item)
                component_missing.append(item)
            else:
                final_earned += score

            if item.id in encoded_item_ids:
                running_included = True
                running_possible += item.max_score
                running_earned += score if score is not None else Decimal("0")

        breakdowns.append(
            ComponentBreakdown(
                component=component,
                final_earned=final_earned,
                final_possible=final_possible,
                running_earned=running_earned,
                running_possible=running_possible,
                running_included=running_included,
                missing_items=component_missing,
            )
        )
    return breakdowns, missing_items


def _get_scheme_components(class_offering):
    scheme = ClassGradingScheme.get_or_create_default(class_offering)
    return list(
        scheme.components.prefetch_related(
            Prefetch("items", queryset=AssessmentItem.objects.order_by("order", "id"))
        ).order_by("order", "id")
    )


def get_encoded_item_ids(item_ids):
    """Public wrapper — views need to know which specific items already
    have at least one score in the class (to highlight still-blank cells on
    an item that's "in progress"), not just which components do."""
    return _encoded_item_ids(item_ids)


def get_scheme_components(class_offering):
    """Public wrapper around the scheme/component lookup used internally by
    compute_student/compute_class — views need the raw component/item
    objects too (to render the grid's column headers)."""
    return _get_scheme_components(class_offering)


def compute_student(roster_entry, components=None) -> StudentGradeResult:
    """Full breakdown + running/final grade for one student. Not the
    efficient path for a whole class — see compute_class for that.

    `components` lets a caller that already fetched the scheme (e.g.
    subject_detail, which also needs it for running_grade_progression and
    the item-by-term list) pass it in instead of this function re-querying
    the same scheme/components/items — see get_scheme_components."""
    if components is None:
        components = _get_scheme_components(roster_entry.class_offering)
    item_ids = [item.id for c in components for item in c.items.all()]
    encoded_item_ids = _encoded_item_ids(item_ids)
    scores_by_item = {
        s.item_id: s.score for s in Score.objects.filter(roster_entry=roster_entry, item_id__in=item_ids)
    }
    breakdowns, missing_items = _build_breakdown(components, scores_by_item, encoded_item_ids)
    return StudentGradeResult(roster_entry=roster_entry, components=breakdowns, missing_items=missing_items)


def compute_class(class_offering) -> list:
    """compute_student for every roster entry in the class, without the
    N+1 queries compute_student-in-a-loop would cause."""
    components = _get_scheme_components(class_offering)
    item_ids = [item.id for c in components for item in c.items.all()]
    encoded_item_ids = _encoded_item_ids(item_ids)

    roster_entries = (
        class_offering.roster_entries.select_related("student")
        .prefetch_related(Prefetch("scores", queryset=Score.objects.filter(item_id__in=item_ids)))
        .order_by("status", "student__last_name", "student__first_name")
    )

    results = []
    for entry in roster_entries:
        scores_by_item = {s.item_id: s.score for s in entry.scores.all()}
        breakdowns, missing_items = _build_breakdown(components, scores_by_item, encoded_item_ids)
        results.append(StudentGradeResult(roster_entry=entry, components=breakdowns, missing_items=missing_items))
    return results


def show_unofficial_scores_to_students():
    """The admin "Show running (unofficial) scores to students" toggle
    (Institution Settings) — local import since `reports` loads after
    `grading` in INSTALLED_APPS; fine at call time, not at module load."""
    from reports.models import InstitutionSettings

    return InstitutionSettings.get_solo().show_unofficial_scores_to_students


def released_entry_for(roster_entry):
    """The frozen RELEASED/LOCKED GradeSheetEntry for this roster entry, if
    any — the one and only source for a student's OFFICIAL grade. None
    means the class hasn't been released yet (show UNOFFICIAL data, or
    nothing, depending on show_unofficial_scores_to_students())."""
    from approvals.models import GradeSheetEntry, GradeSheetStatus

    return (
        GradeSheetEntry.objects.filter(
            roster_entry=roster_entry, sheet__status__in=[GradeSheetStatus.RELEASED, GradeSheetStatus.LOCKED]
        )
        .select_related("sheet")
        .first()
    )


def released_entries_for(roster_entries):
    """Batch version of released_entry_for for MANY roster entries (the
    student dashboard / My Grades list) — one query total instead of one
    per entry. Returns {roster_entry_id: GradeSheetEntry-or-None}."""
    from approvals.models import GradeSheetEntry, GradeSheetStatus

    roster_entries = list(roster_entries)
    if not roster_entries:
        return {}
    entries = GradeSheetEntry.objects.filter(
        roster_entry__in=roster_entries, sheet__status__in=[GradeSheetStatus.RELEASED, GradeSheetStatus.LOCKED]
    ).select_related("sheet")
    by_entry = {e.roster_entry_id: e for e in entries}
    return {entry.id: by_entry.get(entry.id) for entry in roster_entries}


def compute_students_batch(roster_entries):
    """Batch version of compute_student for roster entries spanning MANY
    different classes (the student dashboard / My Grades, as opposed to
    compute_class's "many students, one class") — a handful of queries
    total regardless of how many classes are involved, instead of
    compute_student's own ~3 queries PER entry (Phase 8 part B dashboard
    query-count pass). Returns {roster_entry_id: StudentGradeResult}."""
    from django.db.models import prefetch_related_objects

    from .models import SchemeComponent

    roster_entries = list(roster_entries)
    if not roster_entries:
        return {}

    class_ids = {e.class_offering_id for e in roster_entries}
    schemes = {s.class_offering_id: s for s in ClassGradingScheme.objects.filter(class_offering_id__in=class_ids)}

    # A class with no scheme row yet is rare (one is normally created the
    # first time anyone opens its grading page) — fall back to the
    # single-entry path for just those rather than special-casing it below.
    results = {}
    batchable_entries = []
    for entry in roster_entries:
        if entry.class_offering_id in schemes:
            batchable_entries.append(entry)
        else:
            results[entry.id] = compute_student(entry)
    if not batchable_entries:
        return results

    scheme_ids = [s.id for s in schemes.values()]
    components = list(SchemeComponent.objects.filter(scheme_id__in=scheme_ids).order_by("order", "id"))
    prefetch_related_objects(components, Prefetch("items", queryset=AssessmentItem.objects.order_by("order", "id")))
    components_by_scheme = {}
    for component in components:
        components_by_scheme.setdefault(component.scheme_id, []).append(component)

    all_item_ids = [item.id for component in components for item in component.items.all()]
    encoded_item_ids = _encoded_item_ids(all_item_ids)

    entry_ids = [e.id for e in batchable_entries]
    scores_by_entry = {}
    for score in Score.objects.filter(roster_entry_id__in=entry_ids, item_id__in=all_item_ids):
        scores_by_entry.setdefault(score.roster_entry_id, {})[score.item_id] = score.score

    for entry in batchable_entries:
        scheme = schemes[entry.class_offering_id]
        components_for_entry = components_by_scheme.get(scheme.id, [])
        scores_by_item = scores_by_entry.get(entry.id, {})
        breakdowns, missing_items = _build_breakdown(components_for_entry, scores_by_item, encoded_item_ids)
        results[entry.id] = StudentGradeResult(roster_entry=entry, components=breakdowns, missing_items=missing_items)
    return results


def subject_status_chip(roster_entry, released_entry):
    """(label, css-class-key) — the small status chip shown on the student
    dashboard's subject cards and the My Grades table."""
    if roster_entry.status == ClassRosterEntry.Status.DROPPED:
        return "Dropped", "dropped"
    if released_entry is not None:
        if released_entry.remarks == "INC":
            return "INC", "inc"
        return "Released", "released"
    if roster_entry.is_incomplete:
        return "INC", "inc"
    return "In progress", "in_progress"


def running_grade_progression(roster_entry, components=None, scores_by_item=None):
    """The running grade "as of" each grading period (Prelim → Final) —
    same semantics as StudentGradeResult.running_grade (only components
    with at least one scored item count, re-normalized), but windowed to
    items whose term is at or before the cutoff. Used by the student
    portal's subject-detail progression chart. Returns a list of
    (term_value, term_label, grade-or-None) in Prelim..Final order.

    `components`/`scores_by_item` let a caller that already fetched the
    scheme and scores (subject_detail) pass them in instead of this
    function re-querying the same data — see get_scheme_components."""
    from .models import AssessmentTerm, ASSESSMENT_TERM_ORDER

    if components is None:
        components = _get_scheme_components(roster_entry.class_offering)
    if scores_by_item is None:
        item_ids = [item.id for c in components for item in c.items.all()]
        scores_by_item = {
            s.item_id: s.score for s in Score.objects.filter(roster_entry=roster_entry, item_id__in=item_ids)
        }

    progression = []
    for term, label in AssessmentTerm.choices:
        cutoff = ASSESSMENT_TERM_ORDER[term]
        component_grades = []
        for component in components:
            earned = Decimal("0")
            possible = Decimal("0")
            any_scored = False
            for item in component.items.all():
                if ASSESSMENT_TERM_ORDER[item.term] > cutoff:
                    continue
                score = scores_by_item.get(item.id)
                if score is None:
                    continue
                any_scored = True
                earned += score
                possible += item.max_score
            if any_scored:
                grade = _component_grade(earned, possible)
                if grade is not None:
                    component_grades.append((component, grade))

        if not component_grades:
            progression.append((term, label, None))
            continue
        weight_sum = sum((c.weight for c, _ in component_grades), Decimal("0"))
        if weight_sum == 0:
            progression.append((term, label, None))
            continue
        total = sum(grade * (c.weight / weight_sum) for c, grade in component_grades)
        progression.append((term, label, total))

    return progression


def class_average_per_component(class_offering, minimum_active_students=5):
    """Aggregate-only per-component average grade across ACTIVE students —
    returns None if fewer than `minimum_active_students` are active, so a
    small class never exposes something close to an individual student's
    own data. Keyed by SchemeComponent id."""
    results = [r for r in compute_class(class_offering) if r.roster_entry.status == ClassRosterEntry.Status.ACTIVE]
    if len(results) < minimum_active_students:
        return None

    totals = {}
    for result in results:
        for breakdown in result.components:
            grade = breakdown.final_grade
            if grade is None:
                continue
            bucket = totals.setdefault(breakdown.component.id, [])
            bucket.append(grade)

    return {component_id: (sum(grades) / len(grades)) for component_id, grades in totals.items() if grades}


def per_term_breakdown(roster_entry):
    """Scores grouped by grading period (Prelim/Midterm/Semi-final/Final),
    across all components — for later forecasting checkpoints, not used by
    any UI in this phase."""
    from .models import AssessmentTerm

    class_offering = roster_entry.class_offering
    components = _get_scheme_components(class_offering)
    items = [item for c in components for item in c.items.all()]
    scores_by_item = {
        s.item_id: s.score for s in Score.objects.filter(roster_entry=roster_entry, item_id__in=[i.id for i in items])
    }
    breakdown = {term: {"earned": Decimal("0"), "possible": Decimal("0")} for term, _ in AssessmentTerm.choices}
    for item in items:
        breakdown[item.term]["possible"] += item.max_score
        score = scores_by_item.get(item.id)
        if score is not None:
            breakdown[item.term]["earned"] += score
    return breakdown
