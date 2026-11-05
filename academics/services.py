"""Teaching-load assignment: Program Heads assign which instructor teaches
each class in their program (CITCI confirmed practice); Admin keeps the
ability to set/change it too, as a logged "admin override". Pure functions
— no view/HTTP concerns; views call these and translate ValidationError to
a form error.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Count, Q

from .models import ClassOffering, ClassRosterEntry, TeachingAssignmentLog


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
