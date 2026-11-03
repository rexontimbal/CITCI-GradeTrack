"""Grade sheet workflow — explicit allowed-transition checks, never a bare
status assignment in a view. See CLAUDE.md section 5.

    draft/returned -> submitted -> approved -> released -> locked
                   submitted -> returned -> (edit) -> submitted again

Role checks (who may call which function) live in approvals/views.py,
mirroring grading/views.py's `_can_edit`/`_get_class_offering_for_grading`
pattern — these functions only enforce *status* transitions.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from academics.models import ClassRosterEntry
from dashboard.services import notify, notify_many
from grading.services import compute_class

from .models import GradeCorrection, GradeSheet, GradeSheetEntry, GradeSheetPeriod, GradeSheetStatus, GradeSheetTransition


def is_class_editable(class_offering, period=GradeSheetPeriod.FINAL):
    """True if the instructor may still edit scores/items/components for
    this class — no sheet yet, or the sheet is DRAFT/RETURNED."""
    sheet = GradeSheet.objects.filter(class_offering=class_offering, period=period).first()
    return sheet is None or sheet.is_editable


def get_grade_sheet(class_offering, period=GradeSheetPeriod.FINAL):
    return GradeSheet.objects.filter(class_offering=class_offering, period=period).first()


def _log_transition(sheet, from_status, to_status, actor, remarks=""):
    return GradeSheetTransition.objects.create(
        sheet=sheet, from_status=from_status, to_status=to_status, actor=actor, remarks=remarks
    )


def _require_status(sheet, *allowed):
    if sheet.status not in allowed:
        raise ValidationError(f"This action isn't allowed while the sheet is {sheet.get_status_display()}.")


def _program_heads_for(class_offering):
    from accounts.models import User

    return list(
        User.objects.filter(
            role=User.Role.PROGRAM_HEAD,
            headed_programs__sections__class_offerings=class_offering,
        ).distinct()
    )


def missing_score_students(class_offering):
    """Active, non-INC students who still have at least one blank score —
    these are what blocks submit()."""
    return [
        result
        for result in compute_class(class_offering)
        if result.roster_entry.status == ClassRosterEntry.Status.ACTIVE
        and not result.roster_entry.is_incomplete
        and result.missing_items
    ]


def submit_grade_sheet(class_offering, user, period=GradeSheetPeriod.FINAL):
    """Instructor submits (first time) or re-submits (after a return). Both
    paths replace the sheet's entire entry snapshot — re-submitting isn't a
    diff, it's a fresh take of the current Class Record."""
    sheet = GradeSheet.get_or_create_draft(class_offering, period)
    _require_status(sheet, GradeSheetStatus.DRAFT, GradeSheetStatus.RETURNED)

    if missing_score_students(class_offering):
        raise ValidationError(
            "Some active students still have missing scores — encode them or mark the student INC first."
        )

    results = compute_class(class_offering)

    with transaction.atomic():
        sheet.entries.all().delete()
        for result in results:
            roster_entry = result.roster_entry
            components_json = [
                {
                    "name": breakdown.component.name,
                    "category": breakdown.component.category,
                    "weight": breakdown.component.weight,
                    "earned": str(breakdown.final_earned),
                    "possible": str(breakdown.final_possible),
                    "grade": str(breakdown.final_grade) if breakdown.final_grade is not None else None,
                }
                for breakdown in result.components
            ]
            GradeSheetEntry.objects.create(
                sheet=sheet,
                roster_entry=roster_entry,
                final_grade=result.final_grade,
                remarks=result.final_remarks,
                inc_reason=roster_entry.incomplete_reason if roster_entry.is_incomplete else "",
                components_json=components_json,
            )

        from_status = sheet.status
        sheet.status = GradeSheetStatus.SUBMITTED
        sheet.submitted_at = timezone.now()
        sheet.submitted_by = user
        sheet.save()
        _log_transition(sheet, from_status, GradeSheetStatus.SUBMITTED, user)

    notify_many(
        _program_heads_for(class_offering),
        "Grade sheet submitted",
        f"{class_offering} was submitted for approval by {user.full_name}.",
        link=f"/approvals/sheets/{sheet.pk}/",
    )
    return sheet


def return_grade_sheet(sheet, user, remarks):
    if not remarks or not remarks.strip():
        raise ValidationError("Remarks are required when returning a grade sheet.")
    _require_status(sheet, GradeSheetStatus.SUBMITTED)

    from_status = sheet.status
    sheet.status = GradeSheetStatus.RETURNED
    sheet.return_remarks = remarks
    sheet.save()
    _log_transition(sheet, from_status, GradeSheetStatus.RETURNED, user, remarks=remarks)

    notify(
        sheet.class_offering.instructor,
        "Grade sheet returned",
        remarks,
        link=f"/grading/classes/{sheet.class_offering_id}/",
    )
    return sheet


def approve_grade_sheet(sheet, user):
    _require_status(sheet, GradeSheetStatus.SUBMITTED)

    from_status = sheet.status
    sheet.status = GradeSheetStatus.APPROVED
    sheet.approved_at = timezone.now()
    sheet.approved_by = user
    sheet.save()
    _log_transition(sheet, from_status, GradeSheetStatus.APPROVED, user)

    notify(
        sheet.class_offering.instructor,
        "Grade sheet approved",
        f"{sheet.class_offering} was approved.",
        link=f"/grading/classes/{sheet.class_offering_id}/",
    )
    return sheet


def release_grade_sheet(sheet, user):
    _require_status(sheet, GradeSheetStatus.APPROVED)

    from_status = sheet.status
    sheet.status = GradeSheetStatus.RELEASED
    sheet.released_at = timezone.now()
    sheet.released_by = user
    sheet.save()
    _log_transition(sheet, from_status, GradeSheetStatus.RELEASED, user)

    notify(
        sheet.class_offering.instructor,
        "Grades released",
        f"Grades for {sheet.class_offering} are now official.",
        link=f"/grading/classes/{sheet.class_offering_id}/",
    )

    for entry in sheet.entries.select_related("roster_entry__student"):
        if entry.remarks == GradeSheetEntry.Remarks.DROPPED:
            continue
        notify(
            entry.roster_entry.student,
            "Grade released",
            f"Your final grade in {sheet.class_offering.subject.code} is now available.",
            link=f"/grading/my-grades/{entry.roster_entry_id}/",
        )
    return sheet


def release_all_approved(semester, user, program=None):
    sheets = GradeSheet.objects.filter(status=GradeSheetStatus.APPROVED, class_offering__semester=semester)
    if program is not None:
        sheets = sheets.filter(class_offering__sections__program=program)
    return [release_grade_sheet(sheet, user) for sheet in sheets.distinct()]


def lock_term(semester, user):
    """Admin "Lock term" — locks every RELEASED sheet in the semester at once."""
    sheets = GradeSheet.objects.filter(status=GradeSheetStatus.RELEASED, class_offering__semester=semester)
    locked = []
    for sheet in sheets:
        from_status = sheet.status
        sheet.status = GradeSheetStatus.LOCKED
        sheet.locked_at = timezone.now()
        sheet.locked_by = user
        sheet.save()
        _log_transition(sheet, from_status, GradeSheetStatus.LOCKED, user)
        locked.append(sheet)
    return locked


def correct_grade(entry, user, new_grade, new_remarks, reason):
    if not reason or not reason.strip():
        raise ValidationError("A reason is required for a grade correction.")
    sheet = entry.sheet
    if sheet.status not in (GradeSheetStatus.RELEASED, GradeSheetStatus.LOCKED):
        raise ValidationError("Grade corrections are only allowed on released or locked sheets.")

    old_grade, old_remarks = entry.final_grade, entry.remarks

    with transaction.atomic():
        GradeCorrection.objects.create(
            entry=entry,
            old_grade=old_grade,
            new_grade=new_grade,
            old_remarks=old_remarks,
            new_remarks=new_remarks,
            reason=reason,
            corrected_by=user,
        )
        entry.final_grade = new_grade
        entry.remarks = new_remarks
        entry.save(update_fields=["final_grade", "remarks"])
        _log_transition(
            sheet,
            sheet.status,
            sheet.status,
            user,
            remarks=f"Grade correction for {entry.roster_entry.student.full_name}: {reason}",
        )

    notify(
        sheet.class_offering.instructor,
        "Grade correction",
        f"{entry.roster_entry.student.full_name}'s grade was corrected: {reason}",
        link=f"/grading/classes/{sheet.class_offering_id}/",
    )
    notify(
        entry.roster_entry.student,
        "Grade corrected",
        f"Your final grade in {sheet.class_offering.subject.code} was corrected.",
        link=f"/grading/my-grades/{entry.roster_entry_id}/",
    )
    return entry


def compute_gwa(student, semester):
    """Σ(final grade × units) ÷ Σ units over the student's RELEASED/LOCKED
    entries in the semester, excluding DROPPED and INC. `is_complete` is
    False if any non-dropped class in the semester isn't released yet, or
    was released with an INC remark."""
    entries = (
        GradeSheetEntry.objects.filter(
            roster_entry__student=student,
            roster_entry__class_offering__semester=semester,
            sheet__status__in=[GradeSheetStatus.RELEASED, GradeSheetStatus.LOCKED],
        )
        .exclude(remarks__in=[GradeSheetEntry.Remarks.DROPPED, GradeSheetEntry.Remarks.INC])
        .select_related("roster_entry__class_offering__subject")
    )

    total_weighted = Decimal("0")
    total_units = Decimal("0")
    for entry in entries:
        units = entry.roster_entry.class_offering.subject.units
        total_weighted += entry.final_grade * units
        total_units += units

    gwa = (total_weighted / total_units).quantize(Decimal("0.01")) if total_units else None

    active_roster_entries = ClassRosterEntry.objects.filter(
        student=student, class_offering__semester=semester
    ).exclude(status=ClassRosterEntry.Status.DROPPED)

    is_complete = True
    released_count = 0
    total_count = 0
    for roster_entry in active_roster_entries:
        total_count += 1
        released_entry = GradeSheetEntry.objects.filter(
            roster_entry=roster_entry, sheet__status__in=[GradeSheetStatus.RELEASED, GradeSheetStatus.LOCKED]
        ).first()
        if released_entry is not None:
            released_count += 1
        if released_entry is None or released_entry.remarks == GradeSheetEntry.Remarks.INC:
            is_complete = False

    return {
        "gwa": gwa,
        "total_units": total_units,
        "is_complete": is_complete,
        # For the "Partial GWA: x.xx (n of m subjects released)" note — a
        # student's non-dropped class count and how many of those are
        # already official, independent of whether every one is complete.
        "released_count": released_count,
        "total_count": total_count,
    }
