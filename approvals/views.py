from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from academics.models import ClassOffering, ClassRosterEntry, Program, Semester
from accounts.decorators import role_required
from accounts.models import User
from core.htmx import is_htmx
from grading.services import compute_class

from .forms import CorrectionForm, ReturnRemarksForm, SubmitConfirmForm
from .models import GradeSheet, GradeSheetEntry, GradeSheetStatus
from .services import (
    approve_grade_sheet,
    correct_grade,
    lock_term,
    release_all_approved,
    release_grade_sheet,
    return_grade_sheet,
    submit_grade_sheet,
)

ADMIN = User.Role.ADMIN
PROGRAM_HEAD = User.Role.PROGRAM_HEAD
INSTRUCTOR = User.Role.INSTRUCTOR


# ---------------------------------------------------------------------------
# Access helpers
# ---------------------------------------------------------------------------


def _program_head_owns(user, class_offering):
    return class_offering.sections.filter(program__program_head_id=user.id).exists()


def _get_sheet_for_reviewer(request, pk):
    sheet = get_object_or_404(
        GradeSheet.objects.select_related("class_offering__subject", "class_offering__semester", "class_offering__instructor"),
        pk=pk,
    )
    user = request.user
    if user.is_program_head and not _program_head_owns(user, sheet.class_offering):
        raise PermissionDenied("This class is not under your program.")
    if user.is_instructor and sheet.class_offering.instructor_id != user.id:
        raise PermissionDenied("This class is not assigned to you.")
    return sheet


def _build_submit_summary(class_offering):
    results = compute_class(class_offering)
    counts = {"PASSED": 0, "FAILED": 0, "INC": 0, "DROPPED": 0}
    final_grades = []
    missing_results = []
    for result in results:
        remark = result.remarks
        if remark in counts:
            counts[remark] += 1
        if remark in ("PASSED", "FAILED") and result.final_grade is not None:
            final_grades.append(result.final_grade)
        if (
            result.roster_entry.status == ClassRosterEntry.Status.ACTIVE
            and not result.roster_entry.is_incomplete
            and result.missing_items
        ):
            missing_results.append(result)
    average = sum(final_grades) / len(final_grades) if final_grades else None
    return {
        "counts": counts,
        "average": average,
        "missing_results": missing_results,
        "can_submit": not missing_results,
    }


# ---------------------------------------------------------------------------
# Instructor — submit / resubmit (triggered from the class grading page)
# ---------------------------------------------------------------------------


@role_required(INSTRUCTOR)
def submit_review(request, pk):
    class_offering = get_object_or_404(ClassOffering, pk=pk)
    if class_offering.instructor_id != request.user.id:
        raise PermissionDenied
    summary = _build_submit_summary(class_offering)
    form = SubmitConfirmForm()
    return render(
        request,
        "approvals/_submit_review_modal.html",
        {"class_offering": class_offering, "summary": summary, "form": form},
    )


@role_required(INSTRUCTOR)
def submit(request, pk):
    class_offering = get_object_or_404(ClassOffering, pk=pk)
    if class_offering.instructor_id != request.user.id:
        raise PermissionDenied

    summary = _build_submit_summary(class_offering)
    form = SubmitConfirmForm(request.POST)
    if not form.is_valid() or not summary["can_submit"]:
        if form.is_valid() and not summary["can_submit"]:
            form.add_error(None, "Some active students still have missing scores — encode them or mark INC first.")
        return render(
            request,
            "approvals/_submit_review_modal.html",
            {"class_offering": class_offering, "summary": summary, "form": form},
        )

    try:
        submit_grade_sheet(class_offering, request.user)
    except ValidationError as exc:
        form.add_error(None, str(exc))
        return render(
            request,
            "approvals/_submit_review_modal.html",
            {"class_offering": class_offering, "summary": summary, "form": form},
        )

    response = HttpResponse(status=204)
    response["HX-Refresh"] = "true"
    return response


@role_required(INSTRUCTOR)
def submitted_sheets(request):
    active = Semester.objects.filter(is_active=True).first()
    sheets = (
        GradeSheet.objects.filter(class_offering__instructor=request.user, class_offering__semester=active)
        .select_related("class_offering__subject")
        .order_by("-created_at")
        if active
        else GradeSheet.objects.none()
    )
    status_filter = request.GET.get("status")
    if status_filter:
        sheets = sheets.filter(status=status_filter)

    context = {
        "page_title": "Submitted Grades",
        "sheets": sheets,
        "status_filter": status_filter or "",
        "statuses": GradeSheetStatus.choices,
        "active_semester_set": bool(active),
    }
    if is_htmx(request):
        return render(request, "grading/_submitted_table.html", context)
    return render(request, "grading/submitted.html", context)


# ---------------------------------------------------------------------------
# Program Head — approvals queue + review/approve/return/release
# ---------------------------------------------------------------------------


@role_required(PROGRAM_HEAD)
def index(request):
    status_filter = request.GET.get("status", GradeSheetStatus.SUBMITTED)
    base_qs = GradeSheet.objects.filter(class_offering__sections__program__program_head=request.user).distinct()

    sheets = base_qs
    if status_filter and status_filter != "ALL":
        sheets = sheets.filter(status=status_filter)
    sheets = sheets.select_related("class_offering__subject", "class_offering__instructor").order_by("-submitted_at", "-created_at")

    counts = {status: base_qs.filter(status=status).count() for status, _ in GradeSheetStatus.choices}

    context = {
        "page_title": "Grade Approvals",
        "sheets": sheets,
        "status_filter": status_filter,
        "counts": counts,
        "statuses": GradeSheetStatus.choices,
    }
    if is_htmx(request):
        return render(request, "approvals/_queue_table.html", context)
    return render(request, "approvals/queue.html", context)


@role_required(ADMIN, PROGRAM_HEAD)
def review(request, pk):
    sheet = _get_sheet_for_reviewer(request, pk)
    entries = sheet.entries.select_related("roster_entry__student").prefetch_related("corrections")

    counts = {"PASSED": 0, "FAILED": 0, "INC": 0, "DROPPED": 0}
    final_grades = []
    for entry in entries:
        if entry.remarks in counts:
            counts[entry.remarks] += 1
        if entry.remarks in ("PASSED", "FAILED") and entry.final_grade is not None:
            final_grades.append(entry.final_grade)
    average = sum(final_grades) / len(final_grades) if final_grades else None
    distribution = {str(i): 0 for i in range(1, 6)}
    for grade in final_grades:
        distribution[str(min(5, max(1, int(grade))))] += 1

    context = {
        "page_title": f"Review — {sheet.class_offering}",
        "sheet": sheet,
        "entries": entries,
        "counts": counts,
        "average": average,
        "distribution": distribution,
        "transitions": sheet.transitions.select_related("actor"),
        "is_admin": request.user.is_admin_role,
        "can_approve_return": request.user.is_program_head and sheet.status == GradeSheetStatus.SUBMITTED,
        "can_release": sheet.status == GradeSheetStatus.APPROVED,
    }
    return render(request, "approvals/review.html", context)


@role_required(PROGRAM_HEAD)
def approve(request, pk):
    sheet = _get_sheet_for_reviewer(request, pk)
    try:
        approve_grade_sheet(sheet, request.user)
        messages.success(request, "Grade sheet approved.")
    except ValidationError as exc:
        messages.error(request, str(exc))
    return redirect("approvals:review", pk=sheet.pk)


@role_required(PROGRAM_HEAD)
def return_sheet(request, pk):
    sheet = _get_sheet_for_reviewer(request, pk)
    if request.method == "GET":
        form = ReturnRemarksForm()
        return render(request, "approvals/_return_modal.html", {"sheet": sheet, "form": form})

    form = ReturnRemarksForm(request.POST)
    if not form.is_valid():
        return render(request, "approvals/_return_modal.html", {"sheet": sheet, "form": form})
    try:
        return_grade_sheet(sheet, request.user, form.cleaned_data["remarks"])
    except ValidationError as exc:
        form.add_error(None, str(exc))
        return render(request, "approvals/_return_modal.html", {"sheet": sheet, "form": form})

    response = HttpResponse(status=204)
    response["HX-Redirect"] = reverse("approvals:index")
    return response


@role_required(ADMIN, PROGRAM_HEAD)
def release(request, pk):
    sheet = _get_sheet_for_reviewer(request, pk)
    try:
        release_grade_sheet(sheet, request.user)
        messages.success(request, "Grades released.")
    except ValidationError as exc:
        messages.error(request, str(exc))
    return redirect("approvals:review", pk=sheet.pk)


@role_required(PROGRAM_HEAD)
def release_all(request):
    active = Semester.objects.filter(is_active=True).first()
    if not active:
        messages.error(request, "No active semester is set.")
        return redirect("approvals:index")
    released = []
    for program in Program.objects.filter(program_head=request.user):
        released.extend(release_all_approved(active, request.user, program=program))
    messages.success(request, f"{len(released)} grade sheet(s) released.")
    return redirect("approvals:index")


# ---------------------------------------------------------------------------
# Admin — all grade sheets, lock term, grade correction
# ---------------------------------------------------------------------------


@role_required(ADMIN)
def admin_sheets(request):
    active = Semester.objects.filter(is_active=True).first()
    total_classes = ClassOffering.objects.filter(semester=active).count() if active else 0

    sheets = GradeSheet.objects.filter(class_offering__semester=active) if active else GradeSheet.objects.none()

    program_id = request.GET.get("program")
    status = request.GET.get("status")
    instructor_id = request.GET.get("instructor")
    if program_id:
        sheets = sheets.filter(class_offering__sections__program_id=program_id)
    if status:
        sheets = sheets.filter(status=status)
    if instructor_id:
        sheets = sheets.filter(class_offering__instructor_id=instructor_id)
    sheets = sheets.distinct().select_related("class_offering__subject", "class_offering__instructor").order_by("-created_at")

    submitted_or_further = (
        GradeSheet.objects.filter(
            class_offering__semester=active,
            status__in=[GradeSheetStatus.SUBMITTED, GradeSheetStatus.RETURNED, GradeSheetStatus.APPROVED, GradeSheetStatus.RELEASED, GradeSheetStatus.LOCKED],
        ).count()
        if active
        else 0
    )
    approved_or_further = (
        GradeSheet.objects.filter(
            class_offering__semester=active, status__in=[GradeSheetStatus.APPROVED, GradeSheetStatus.RELEASED, GradeSheetStatus.LOCKED]
        ).count()
        if active
        else 0
    )
    released_or_further = (
        GradeSheet.objects.filter(class_offering__semester=active, status__in=[GradeSheetStatus.RELEASED, GradeSheetStatus.LOCKED]).count()
        if active
        else 0
    )

    context = {
        "page_title": "Grade Sheets",
        "sheets": sheets,
        "active_semester": active,
        "total_classes": total_classes,
        "progress": {"submitted": submitted_or_further, "approved": approved_or_further, "released": released_or_further},
        "programs": Program.objects.all(),
        "instructors": User.objects.filter(role=INSTRUCTOR).order_by("last_name", "first_name"),
        "statuses": GradeSheetStatus.choices,
        "selected_program": program_id or "",
        "selected_status": status or "",
        "selected_instructor": instructor_id or "",
    }
    if is_htmx(request):
        return render(request, "approvals/_admin_sheets_table.html", context)
    return render(request, "approvals/admin_sheets.html", context)


@role_required(ADMIN)
def admin_lock_term(request):
    active = Semester.objects.filter(is_active=True).first()
    if request.method == "GET":
        releasable_count = (
            GradeSheet.objects.filter(status=GradeSheetStatus.RELEASED, class_offering__semester=active).count()
            if active
            else 0
        )
        return render(request, "approvals/_lock_term_modal.html", {"active_semester": active, "count": releasable_count})

    if active:
        locked = lock_term(active, request.user)
        messages.success(request, f"{len(locked)} grade sheet(s) locked.")
    else:
        messages.error(request, "No active semester is set.")

    response = HttpResponse(status=204)
    response["HX-Refresh"] = "true"
    return response


@role_required(ADMIN)
def correct_entry(request, pk):
    entry = get_object_or_404(
        GradeSheetEntry.objects.select_related("sheet__class_offering", "roster_entry__student"), pk=pk
    )
    if request.method == "GET":
        form = CorrectionForm(initial={"final_grade": entry.final_grade, "remarks": entry.remarks})
        return render(request, "approvals/_correct_grade_modal.html", {"entry": entry, "form": form})

    form = CorrectionForm(request.POST)
    if not form.is_valid():
        return render(request, "approvals/_correct_grade_modal.html", {"entry": entry, "form": form})
    try:
        correct_grade(
            entry, request.user, form.cleaned_data["final_grade"], form.cleaned_data["remarks"], form.cleaned_data["reason"]
        )
    except ValidationError as exc:
        form.add_error(None, str(exc))
        return render(request, "approvals/_correct_grade_modal.html", {"entry": entry, "form": form})

    response = HttpResponse(status=204)
    response["HX-Refresh"] = "true"
    return response
