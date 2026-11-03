"""Report query functions — pure data gathering, no view/HTTP concerns.
Every function takes `programs` (a queryset the caller has already scoped
to what the current user may see — see reports.views._scope_programs) so
role scoping happens once, at the call site, not re-implemented per report.
"""

from decimal import Decimal

from academics.models import ClassOffering
from approvals.models import GradeSheet, GradeSheetEntry, GradeSheetStatus
from grading.services import compute_class


def submission_status_rows(semester, programs):
    classes = (
        ClassOffering.objects.filter(semester=semester, sections__program__in=programs)
        .distinct()
        .select_related("subject", "instructor")
        .order_by("subject__code")
    )
    rows = []
    for class_offering in classes:
        sheet = GradeSheet.objects.filter(class_offering=class_offering).first()
        rows.append(
            {
                "class_offering": class_offering,
                "instructor": class_offering.instructor,
                "status": sheet.status if sheet else GradeSheetStatus.DRAFT,
                "status_display": sheet.get_status_display() if sheet else "Draft",
                "submitted_at": sheet.submitted_at if sheet else None,
                "approved_at": sheet.approved_at if sheet else None,
                "released_at": sheet.released_at if sheet else None,
            }
        )
    return rows


def class_performance_rows(semester, programs):
    """Reads the submitted snapshot when one exists (so the report matches
    what was actually submitted/approved/released); falls back to a live
    compute for classes still in Draft, so an in-progress class isn't just
    missing from the report."""
    classes = (
        ClassOffering.objects.filter(semester=semester, sections__program__in=programs)
        .distinct()
        .select_related("subject", "instructor")
        .order_by("subject__code")
    )
    rows = []
    for class_offering in classes:
        sheet = GradeSheet.objects.filter(class_offering=class_offering).first()
        counts = {"PASSED": 0, "FAILED": 0, "INC": 0, "DROPPED": 0}
        grades = []
        total_students = 0

        if sheet and sheet.entries.exists():
            for entry in sheet.entries.all():
                total_students += 1
                if entry.remarks in counts:
                    counts[entry.remarks] += 1
                if entry.remarks in ("PASSED", "FAILED") and entry.final_grade is not None:
                    grades.append(entry.final_grade)
        else:
            for result in compute_class(class_offering):
                total_students += 1
                remark = result.remarks
                if remark in counts:
                    counts[remark] += 1
                if remark in ("PASSED", "FAILED") and result.final_grade is not None:
                    grades.append(result.final_grade)

        average = (sum(grades) / len(grades)) if grades else None
        pass_rate = (Decimal(counts["PASSED"]) / Decimal(total_students) * 100) if total_students else None
        rows.append(
            {
                "class_offering": class_offering,
                "total_students": total_students,
                "counts": counts,
                "average": average,
                "pass_rate": pass_rate,
            }
        )
    return rows


def failing_inc_rows(semester, programs):
    """Only from RELEASED/LOCKED sheets — these are official grades."""
    return list(
        GradeSheetEntry.objects.filter(
            sheet__status__in=[GradeSheetStatus.RELEASED, GradeSheetStatus.LOCKED],
            sheet__class_offering__semester=semester,
            sheet__class_offering__sections__program__in=programs,
            remarks__in=[GradeSheetEntry.Remarks.FAILED, GradeSheetEntry.Remarks.INC],
        )
        .distinct()
        .select_related(
            "roster_entry__student__student_profile__program",
            "roster_entry__student__student_profile__major",
            "sheet__class_offering__subject",
            "sheet__class_offering__instructor",
        )
        .order_by("roster_entry__student__last_name", "roster_entry__student__first_name")
    )
