"""Grade sheet workflow — explicit allowed-transition checks, never a bare
status assignment in a view. See CLAUDE.md section 5.

    draft/returned -> submitted -> approved -> released -> locked
                   submitted -> returned -> (edit) -> submitted again

Role checks (who may call which function) live in approvals/views.py,
mirroring grading/views.py's `_can_edit`/`_get_class_offering_for_grading`
pattern — these functions only enforce *status* transitions.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from academics.models import ClassOffering, ClassRosterEntry
from dashboard.services import notify, notify_many
from grading.services import compute_class, released_entries_for

from .models import (
    GradeCorrection,
    GradeSheet,
    GradeSheetEntry,
    GradeSheetPeriod,
    GradeSheetStatus,
    GradeSheetTransition,
    IncCompletion,
    IncCompletionStatus,
)


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


def missing_score_counts_for_classes(classes):
    """Count-only, batched sibling of missing_score_students — the to-do
    dashboard only needs a number per class, not full StudentGradeResult
    objects. {class_id: count}, omitting classes with zero."""
    counts = {}
    for class_offering in classes:
        count = len(missing_score_students(class_offering))
        if count:
            counts[class_offering.id] = count
    return counts


def returned_sheets_for_classes(classes):
    return list(
        GradeSheet.objects.filter(class_offering__in=classes, status=GradeSheetStatus.RETURNED).select_related(
            "class_offering__subject"
        )
    )


def unsubmitted_sheets_for_classes(classes):
    """Classes with no sheet yet, or a DRAFT/RETURNED one — each paired
    with its semester's deadline (or None) for a countdown display."""
    classes = list(classes)
    sheets_by_class = {
        sheet.class_offering_id: sheet
        for sheet in GradeSheet.objects.filter(class_offering__in=classes, period=GradeSheetPeriod.FINAL)
    }
    rows = []
    for class_offering in classes:
        sheet = sheets_by_class.get(class_offering.id)
        if sheet is not None and sheet.status not in (GradeSheetStatus.DRAFT, GradeSheetStatus.RETURNED):
            continue
        rows.append({"class_offering": class_offering, "deadline": class_offering.semester.submission_deadline})
    return rows


def unsubmitted_sheets_for_instructor(instructor, semester):
    classes = ClassOffering.objects.filter(instructor=instructor, semester=semester).select_related(
        "subject", "semester"
    )
    return unsubmitted_sheets_for_classes(classes)


def late_or_unsubmitted_counts(semester, programs=None):
    """Batched counts for the Late / Not-yet-submitted filters on Grade
    Approvals, Grade Sheets, and the Submission Status report. `programs`
    is already role-scoped by the caller (reports.views._scope_programs's
    convention)."""
    classes = ClassOffering.objects.filter(semester=semester)
    if programs is not None:
        classes = classes.filter(sections__program__in=programs).distinct()

    late_count = GradeSheet.objects.filter(class_offering__in=classes, is_late=True).count()
    not_submitted_count = len(unsubmitted_sheets_for_classes(classes))
    return {"late_count": late_count, "not_submitted_count": not_submitted_count}


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
    deadline = class_offering.semester.submission_deadline
    is_late = bool(deadline and timezone.now() > deadline)

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
        sheet.is_late = is_late
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


# ---------------------------------------------------------------------------
# INC completion — instructor files, Program Head approves/rejects.
# Approval reuses correct_grade() verbatim (see its docstring on IncCompletion
# in models.py). compute_gwa() is a pure read-time computation (see below) —
# nothing needs to explicitly "recompute" GWA after an approval, the very
# next call already reflects the corrected final_grade/remarks.
# ---------------------------------------------------------------------------


def can_file_inc_completion(entry):
    """Returns (bool, reason). `reason` is set whenever the bool is False
    — including the lapsed-window case, whose exact wording is reused
    verbatim everywhere this is surfaced (the Class Record INC badge, the
    "INC to complete" list), so there's one source of that copy."""
    from reports.models import InstitutionSettings

    if entry.remarks != GradeSheetEntry.Remarks.INC:
        return False, "This entry isn't marked INC."
    if entry.sheet.status not in (GradeSheetStatus.RELEASED, GradeSheetStatus.LOCKED):
        return False, "INC completion is only available once the grade sheet is released."
    if entry.inc_completions.filter(status__in=[IncCompletionStatus.PENDING, IncCompletionStatus.APPROVED]).exists():
        return False, "An INC completion is already filed for this entry."

    window_days = InstitutionSettings.get_solo().inc_completion_window_days
    deadline = entry.sheet.released_at + timedelta(days=window_days) if entry.sheet.released_at else None
    if deadline and timezone.now() > deadline:
        return False, "INC lapsed — contact Registrar."
    return True, ""


def file_inc_completion(entry, user, new_grade, new_remarks, date_complied, remarks_text=""):
    allowed, reason = can_file_inc_completion(entry)
    if not allowed:
        raise ValidationError(reason)
    if new_remarks not in (GradeSheetEntry.Remarks.PASSED, GradeSheetEntry.Remarks.FAILED):
        raise ValidationError("An INC completion must resolve to Passed or Failed.")

    completion = IncCompletion.objects.create(
        entry=entry,
        filed_by=user,
        new_grade=new_grade,
        new_remarks=new_remarks,
        date_complied=date_complied,
        remarks_text=remarks_text,
    )
    notify_many(
        _program_heads_for(entry.sheet.class_offering),
        "INC completion filed",
        f"{entry.roster_entry.student.full_name}'s INC in {entry.sheet.class_offering} is ready for review.",
        link="/approvals/?status=INC_COMPLETIONS",
    )
    return completion


def decide_inc_completion(completion, user, approve, decision_remarks=""):
    if completion.status != IncCompletionStatus.PENDING:
        raise ValidationError("This INC completion has already been decided.")

    entry = completion.entry
    if approve:
        correct_grade(
            entry,
            user,
            completion.new_grade,
            completion.new_remarks,
            reason=f"INC completion: {completion.remarks_text}" if completion.remarks_text else "INC completion approved.",
        )
        completion.status = IncCompletionStatus.APPROVED
        completion.decided_by = user
        completion.decided_at = timezone.now()
        completion.save(update_fields=["status", "decided_by", "decided_at"])

        notify(
            entry.sheet.class_offering.instructor,
            "INC completion approved",
            f"{entry.roster_entry.student.full_name}'s INC in {entry.sheet.class_offering} has been completed.",
            link=f"/grading/classes/{entry.sheet.class_offering_id}/",
        )
        notify(
            entry.roster_entry.student,
            "INC completed",
            f"Your INC in {entry.sheet.class_offering.subject.code} has been completed.",
            link=f"/grading/my-grades/{entry.roster_entry_id}/",
        )
    else:
        if not decision_remarks or not decision_remarks.strip():
            raise ValidationError("Remarks are required when rejecting an INC completion.")
        completion.status = IncCompletionStatus.REJECTED
        completion.decided_by = user
        completion.decided_at = timezone.now()
        completion.decision_remarks = decision_remarks
        completion.save(update_fields=["status", "decided_by", "decided_at", "decision_remarks"])

        notify(
            entry.sheet.class_offering.instructor,
            "INC completion rejected",
            f"{entry.roster_entry.student.full_name}'s INC completion was rejected: {decision_remarks}",
            link=f"/grading/classes/{entry.sheet.class_offering_id}/",
        )
    return completion


def pending_inc_completions_for_program_head(user):
    return (
        IncCompletion.objects.filter(
            status=IncCompletionStatus.PENDING,
            entry__sheet__class_offering__sections__program__program_head=user,
        )
        .distinct()
        .select_related("entry__roster_entry__student", "entry__sheet__class_offering__subject")
    )


def inc_completions_to_file_for_instructor(instructor):
    """Active (RELEASED/LOCKED + INC) entries for this instructor's
    classes that don't already have a PENDING/APPROVED filing — what the
    instructor's "INC to complete" list shows."""
    return (
        GradeSheetEntry.objects.filter(
            remarks=GradeSheetEntry.Remarks.INC,
            sheet__class_offering__instructor=instructor,
            sheet__status__in=[GradeSheetStatus.RELEASED, GradeSheetStatus.LOCKED],
        )
        .exclude(inc_completions__status__in=[IncCompletionStatus.PENDING, IncCompletionStatus.APPROVED])
        .select_related("roster_entry__student", "sheet__class_offering__subject")
    )


def inc_completions_pending_for_classes(classes):
    """Batched sibling of inc_completions_to_file_for_instructor, for the
    instructor to-do dashboard — one query for however many classes."""
    return list(
        GradeSheetEntry.objects.filter(
            remarks=GradeSheetEntry.Remarks.INC,
            sheet__class_offering__in=classes,
            sheet__status__in=[GradeSheetStatus.RELEASED, GradeSheetStatus.LOCKED],
        )
        .exclude(inc_completions__status__in=[IncCompletionStatus.PENDING, IncCompletionStatus.APPROVED])
        .select_related("roster_entry__student", "sheet__class_offering__subject")
    )


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

    active_roster_entries = list(
        ClassRosterEntry.objects.filter(student=student, class_offering__semester=semester).exclude(
            status=ClassRosterEntry.Status.DROPPED
        )
    )

    # Batched (Phase 8 part B dashboard query-count pass) — this used to
    # run one GradeSheetEntry query PER roster entry; now it's one query
    # total for however many subjects the student has this semester.
    released_by_entry = released_entries_for(active_roster_entries)

    is_complete = True
    released_count = 0
    total_count = len(active_roster_entries)
    for roster_entry in active_roster_entries:
        released_entry = released_by_entry.get(roster_entry.id)
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
