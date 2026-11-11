"""Teaching-load assignment: Program Heads assign which instructor teaches
each class in their program (CITCI confirmed practice); Admin keeps the
ability to set/change it too, as a logged "admin override". Pure functions
— no view/HTTP concerns; views call these and translate ValidationError to
a form error.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q

import re

from .models import (
    AcademicYear,
    ClassOffering,
    ClassRosterEntry,
    CurriculumEntry,
    Section,
    Semester,
    Subject,
    TeachingAssignmentLog,
)


def check_instructor_change_allowed(class_offering):
    """Raises ValidationError if this class's grade sheet has already been
    submitted — once grades are in the approval pipeline, who taught the
    class shouldn't change out from under it. Allowed while the sheet is
    still DRAFT/RETURNED, or doesn't exist yet."""
    from approvals.services import is_class_editable

    if not is_class_editable(class_offering):
        raise ValidationError(
            "This class's grade sheet has already been submitted — the instructor can no longer be changed."
        )


def assign_instructor(class_offering, new_instructor, actor, is_admin_override=False, reason=""):
    """Assigns/changes/clears (new_instructor=None) a class's instructor.
    Returns the TeachingAssignmentLog row, or None if the instructor didn't
    actually change (a no-op is never logged or notified)."""
    old_instructor = class_offering.instructor
    if old_instructor_id_matches(old_instructor, new_instructor):
        return None

    check_instructor_change_allowed(class_offering)

    class_offering.instructor = new_instructor
    class_offering.save(update_fields=["instructor"])

    return log_and_notify_instructor_change(
        class_offering, old_instructor, new_instructor, actor, is_admin_override=is_admin_override, reason=reason
    )


def old_instructor_id_matches(old_instructor, new_instructor):
    old_id = old_instructor.id if old_instructor else None
    new_id = new_instructor.id if new_instructor else None
    return old_id == new_id


def log_and_notify_instructor_change(class_offering, old_instructor, new_instructor, actor, is_admin_override=False, reason=""):
    """Writes the TeachingAssignmentLog row and notifies both the new
    instructor and the previous one (if any) — shared by the dedicated
    assign/bulk-assign views and the admin Classes edit form, so every
    path that changes an instructor logs and notifies the same way."""
    from dashboard.services import notify

    log = TeachingAssignmentLog.objects.create(
        class_offering=class_offering,
        old_instructor=old_instructor,
        new_instructor=new_instructor,
        changed_by=actor,
        is_admin_override=is_admin_override,
        reason=reason,
    )

    if new_instructor is not None:
        notify(
            new_instructor,
            "New teaching assignment",
            f"You've been assigned {class_offering}.",
            link="/academics/my-classes/",
        )
    if old_instructor is not None and (new_instructor is None or old_instructor.id != new_instructor.id):
        notify(
            old_instructor,
            "Teaching assignment changed",
            f"{class_offering.subject.code} was reassigned.",
            link="/academics/my-classes/",
        )
    return log


def teaching_load_rows(semester, programs, program_id=None, instructor_id=None):
    """Per-instructor teaching load for `semester`, scoped to `programs`
    (already role-scoped by the caller — see reports.views._scope_programs
    for the same pattern). Returns (rows, unassigned_classes):
    rows = [{"instructor": User, "classes": [...], "total_units": Decimal,
    "total_students": int}, ...] sorted by instructor name; unassigned
    classes are listed separately, never silently dropped."""
    if semester is None:
        return [], []

    scoped_programs = programs.filter(pk=program_id) if program_id else programs
    classes = (
        ClassOffering.objects.filter(semester=semester, sections__program__in=scoped_programs)
        .distinct()
        .select_related("subject", "instructor")
        .annotate(
            roster_size=Count(
                "roster_entries", filter=Q(roster_entries__status=ClassRosterEntry.Status.ACTIVE), distinct=True
            )
        )
    )
    if instructor_id:
        classes = classes.filter(instructor_id=instructor_id)

    by_instructor = {}
    unassigned = []
    for class_offering in classes:
        if class_offering.instructor_id is None:
            unassigned.append(class_offering)
            continue
        row = by_instructor.setdefault(
            class_offering.instructor_id,
            {"instructor": class_offering.instructor, "classes": [], "total_units": Decimal("0"), "total_students": 0},
        )
        row["classes"].append(class_offering)
        row["total_units"] += class_offering.subject.units
        row["total_students"] += class_offering.roster_size

    rows = sorted(by_instructor.values(), key=lambda r: r["instructor"].full_name)
    return rows, unassigned


# ---------------------------------------------------------------------------
# Program Head assignment notification — Admin assigns a head on the
# Programs/Majors pages; the new head is notified. Modeled directly on
# log_and_notify_instructor_change's no-op guard (re-saving the same head
# is never notified twice).
# ---------------------------------------------------------------------------


def notify_program_head_assignment(entity, old_head, new_head):
    from dashboard.services import notify

    old_id = old_head.id if old_head else None
    new_id = new_head.id if new_head else None
    if old_id == new_id or new_head is None:
        return
    notify(
        new_head,
        "You've been assigned as Program Head",
        f"You now manage {entity}.",
        link="/academics/my-program/sections/",
    )


# ---------------------------------------------------------------------------
# "Copy classes from previous semester" — admin picks a source semester
# (defaults to the same term, previous A.Y.), previews the classes that
# would be created for the active/target semester, then confirms. The
# instructor is always left Unassigned on the copy — Program Heads assign
# teaching loads (section 3a) — regardless of who taught the source class.
# ---------------------------------------------------------------------------


def default_source_semester(target_semester):
    """Same term, previous academic year — just a pre-selected default;
    the admin can still pick a different source semester."""
    previous_ay = AcademicYear.objects.filter(start_year=target_semester.academic_year.start_year - 1).first()
    if previous_ay is None:
        return None
    return Semester.objects.filter(academic_year=previous_ay, term=target_semester.term).first()


def build_copy_preview(source_semester, target_semester):
    """Never writes. One row per source ClassOffering: its subject, its
    source sections, the resolved equivalent sections in the target
    semester's academic year (same program/major/year_level/name), or a
    reported "no equivalent section" if one can't be found — never
    guessed."""
    rows = []
    classes = source_semester.class_offerings.select_related("subject").prefetch_related(
        "sections__program", "sections__major"
    )
    for class_offering in classes:
        source_sections = list(class_offering.sections.all())
        target_sections = []
        missing = []
        for section in source_sections:
            equivalent = Section.objects.filter(
                program=section.program,
                major=section.major,
                academic_year=target_semester.academic_year,
                year_level=section.year_level,
                name=section.name,
            ).first()
            if equivalent is None:
                missing.append(section)
            else:
                target_sections.append(equivalent)
        rows.append(
            {
                "class_offering": class_offering,
                "subject": class_offering.subject,
                "source_sections": source_sections,
                "target_section_ids": [s.id for s in target_sections],
                "target_sections": target_sections,
                "missing_sections": missing,
                "can_copy": not missing,
            }
        )
    return rows


def commit_copy(preview_rows, target_semester):
    """One atomic transaction. Skips (and the caller reports) any row
    whose sections didn't fully resolve rather than creating a class with
    missing sections. Instructor is always None on the copy."""
    created = 0
    skipped = 0
    with transaction.atomic():
        for row in preview_rows:
            if not row["can_copy"]:
                skipped += 1
                continue
            source = row["class_offering"]
            new_class = ClassOffering.objects.create(
                subject=source.subject,
                semester=target_semester,
                instructor=None,
                schedule=source.schedule,
                room=source.room,
            )
            new_class.sections.set(row["target_section_ids"])
            created += 1
    return {"created": created, "skipped": skipped}


# ---------------------------------------------------------------------------
# Add/Edit Subject — the subject catalog is school-wide, so a new code
# must never silently duplicate an existing one that's merely spelled or
# spaced differently ("EL 100" vs "el100"); a code match always wins over
# creating a new row. A subject also sits in a given program/major's
# curriculum AT MOST ONCE, period (see CurriculumEntry's Meta constraints)
# — not once per year-level/term slot.
# ---------------------------------------------------------------------------

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_code(code):
    """Case/spacing-insensitive canonical form of a subject code, used
    only for matching — never stored or displayed (the original casing
    a human typed is what's saved)."""
    return _WHITESPACE_RE.sub(" ", (code or "").strip()).upper()


def find_subject_by_normalized_code(code):
    """Exact match against the catalog, ignoring case and whitespace
    differences. The catalog is small (low hundreds of rows at most) so
    a Python-side scan is simpler and plenty fast — no need for a
    generated/indexed normalized-code column."""
    target = normalize_code(code)
    if not target:
        return None
    for subject in Subject.objects.all():
        if normalize_code(subject.code) == target:
            return subject
    return None


def slot_label(year_level, term):
    """"1st Year · 1st Semester" / "1st Semester" (no year level, e.g.
    TCP) — display label for one curriculum slot."""
    term_labels = {"FIRST": "1st Semester", "SECOND": "2nd Semester", "SUMMER": "Summer"}
    term_label = term_labels.get(term, term)
    if not year_level:
        return term_label
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(year_level, "th")
    return f"{year_level}{suffix} Year · {term_label}"


def scope_label(program, major):
    """Display label for a program/major scope, e.g. "BSED – English".
    `.title()` guards against a Major whose `name` happens to be stored
    in a different case (e.g. imported from an all-caps docx heading like
    "MAJOR IN ENGLISH") -- the badge should always read in proper case
    regardless of how it's stored."""
    return f"{program.code} – {major.name.title()}" if major else program.code


def subject_duplicate_error(subject, program, major, year_level, term):
    """None if `subject` isn't already in this program/major's curriculum
    anywhere; else a user-facing message — worded differently depending
    on whether the existing placement happens to be the exact slot being
    added to, or elsewhere in the same program/major (a subject can only
    ever sit once per program/major, so these are the only two cases)."""
    existing = CurriculumEntry.objects.filter(program=program, major=major, subject=subject).first()
    if existing is None:
        return None
    if existing.year_level == year_level and existing.term == term:
        return f"{subject.code} is already in {slot_label(year_level, term)}."
    return (
        f"{subject.code} is already in {slot_label(existing.year_level, existing.term)} of "
        f"{scope_label(program, major)}. Remove it there first."
    )


def subject_used_in_released_grades(subject):
    """True if any class using this subject has a RELEASED/LOCKED grade
    sheet — changing the subject's code at that point would alter what
    reads as an official record, so a code change is blocked (admin can
    still force it through the explicit "Correct code" action)."""
    from approvals.models import GradeSheetStatus

    return ClassOffering.objects.filter(
        subject=subject, grade_sheets__status__in=[GradeSheetStatus.RELEASED, GradeSheetStatus.LOCKED]
    ).exists()
