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

from .models import AssessmentItem, ClassGradingScheme, Score, ScoreChangeLog, SchemeComponentChangeLog

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


def compute_student(roster_entry) -> StudentGradeResult:
    """Full breakdown + running/final grade for one student. Not the
    efficient path for a whole class — see compute_class for that."""
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
