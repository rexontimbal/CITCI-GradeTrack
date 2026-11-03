from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.utils import timezone

from academics.models import ClassOffering, Program, Semester
from accounts.decorators import role_required
from accounts.models import User
from approvals.models import GradeSheet, GradeSheetStatus

from . import excel
from .excel_import import build_import_preview, commit_import
from .forms import InstitutionSettingsForm
from .models import InstitutionSettings
from .pdf import render_pdf, watermark_data_uri
from .services import class_performance_rows, failing_inc_rows, submission_status_rows

ADMIN = User.Role.ADMIN
PROGRAM_HEAD = User.Role.PROGRAM_HEAD
INSTRUCTOR = User.Role.INSTRUCTOR


# ---------------------------------------------------------------------------
# Access helpers
# ---------------------------------------------------------------------------


def _program_head_owns(user, class_offering):
    return class_offering.sections.filter(program__program_head_id=user.id).exists()


def _can_view_class_reports(user, class_offering):
    if user.is_admin_role:
        return True
    if user.is_program_head:
        return _program_head_owns(user, class_offering)
    if user.is_instructor:
        return class_offering.instructor_id == user.id
    return False


def _get_class_offering_for_reports(request, pk):
    class_offering = get_object_or_404(
        ClassOffering.objects.select_related("subject", "semester", "instructor").prefetch_related("sections__program"),
        pk=pk,
    )
    if not _can_view_class_reports(request.user, class_offering):
        raise PermissionDenied("You don't have access to this class's reports.")
    return class_offering


def _logo_context(request):
    inst = InstitutionSettings.get_solo()
    if inst.logo:
        logo_url = request.build_absolute_uri(inst.logo.url)
    else:
        logo_url = request.build_absolute_uri(static("img/citci-seal-256.png"))
    return inst, logo_url


# ---------------------------------------------------------------------------
# Admin — Institution Settings
# ---------------------------------------------------------------------------


@role_required(ADMIN)
def settings_edit(request):
    instance = InstitutionSettings.get_solo()
    if request.method == "POST":
        form = InstitutionSettingsForm(request.POST, request.FILES, instance=instance)
        if form.is_valid():
            form.save()
            messages.success(request, "Institution settings saved.")
            return redirect("reports:settings")
    else:
        form = InstitutionSettingsForm(instance=instance)
    return render(request, "reports/settings.html", {"page_title": "Institution Settings", "form": form, "instance": instance})


# ---------------------------------------------------------------------------
# Grade Sheet PDF
# ---------------------------------------------------------------------------


@role_required(ADMIN, PROGRAM_HEAD, INSTRUCTOR)
def grade_sheet_pdf(request, pk):
    sheet = get_object_or_404(
        GradeSheet.objects.select_related("class_offering__subject", "class_offering__semester__academic_year", "class_offering__instructor"),
        pk=pk,
    )
    class_offering = sheet.class_offering
    if not _can_view_class_reports(request.user, class_offering):
        raise PermissionDenied("You don't have access to this class's grade sheet.")

    inst, logo_url = _logo_context(request)
    entries = sheet.entries.select_related("roster_entry__student").order_by(
        "roster_entry__student__last_name", "roster_entry__student__first_name"
    )
    counts = {"PASSED": 0, "FAILED": 0, "INC": 0, "DROPPED": 0}
    for entry in entries:
        if entry.remarks in counts:
            counts[entry.remarks] += 1

    is_official = sheet.status in (GradeSheetStatus.RELEASED, GradeSheetStatus.LOCKED)
    context = {
        "settings": inst,
        "logo_url": logo_url,
        "generated_at": timezone.now(),
        "watermark_text": None if is_official else f"UNOFFICIAL — {sheet.get_status_display().upper()}",
        "sheet": sheet,
        "class_offering": class_offering,
        "entries": entries,
        "counts": counts,
        "total_students": entries.count(),
    }
    if not is_official:
        context["watermark_data_uri"] = watermark_data_uri(context["watermark_text"])

    filename = f"GradeSheet_{class_offering.subject.code}_{class_offering.pk}.pdf"
    return render_pdf("reports/pdf/grade_sheet.html", context, filename)


# ---------------------------------------------------------------------------
# Class Record Excel export / import
# ---------------------------------------------------------------------------


@role_required(ADMIN, PROGRAM_HEAD, INSTRUCTOR)
def class_record_excel(request, pk):
    class_offering = _get_class_offering_for_reports(request, pk)
    blank = request.GET.get("blank") == "1"
    workbook = excel.build_class_record_workbook(class_offering, blank=blank)
    filename = f"ClassRecord_{class_offering.subject.code}{'_blank' if blank else ''}.xlsx"
    return excel.workbook_response(workbook, filename)


def _can_edit_class_record(user, class_offering):
    from approvals.services import is_class_editable

    return user.is_instructor and class_offering.instructor_id == user.id and is_class_editable(class_offering)


@role_required(INSTRUCTOR)
def class_record_import(request, pk):
    class_offering = get_object_or_404(ClassOffering, pk=pk)
    if not _can_edit_class_record(request.user, class_offering):
        raise PermissionDenied("This class's grades aren't editable right now.")

    if request.method != "POST":
        return render(request, "reports/_import_modal.html", {"class_offering": class_offering})

    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return render(request, "reports/_import_modal.html", {"class_offering": class_offering, "error": "Choose a file first."})

    try:
        preview = build_import_preview(class_offering, uploaded_file)
    except ValueError as exc:
        return render(request, "reports/_import_modal.html", {"class_offering": class_offering, "error": str(exc)})

    request.session["class_record_import_preview"] = preview.to_session()
    request.session["class_record_import_class_id"] = class_offering.pk
    return render(request, "reports/_import_preview.html", {"class_offering": class_offering, "preview": preview})


@role_required(INSTRUCTOR)
def class_record_import_confirm(request, pk):
    class_offering = get_object_or_404(ClassOffering, pk=pk)
    if not _can_edit_class_record(request.user, class_offering):
        raise PermissionDenied("This class's grades aren't editable right now.")

    stashed = request.session.get("class_record_import_preview")
    stashed_class_id = request.session.get("class_record_import_class_id")
    if not stashed or stashed_class_id != class_offering.pk:
        response = render(
            request, "reports/_import_modal.html", {"class_offering": class_offering, "error": "Your preview expired — upload the file again."}
        )
        response["HX-Retarget"] = "#modal-content"
        response["HX-Reswap"] = "innerHTML"
        return response

    commit_import(class_offering, stashed, request.user)
    del request.session["class_record_import_preview"]
    del request.session["class_record_import_class_id"]

    response = HttpResponse(status=204)
    response["HX-Refresh"] = "true"
    return response


# ---------------------------------------------------------------------------
# Reports page — role-aware
# ---------------------------------------------------------------------------


@role_required(ADMIN, PROGRAM_HEAD, INSTRUCTOR)
def index(request):
    user = request.user
    active = Semester.objects.filter(is_active=True).first()

    if user.is_instructor:
        classes = (
            ClassOffering.objects.filter(instructor=user, semester=active).select_related("subject")
            if active
            else ClassOffering.objects.none()
        )
        return render(
            request,
            "reports/index_instructor.html",
            {"page_title": "Reports", "classes": classes, "active_semester_set": bool(active)},
        )

    # Program Head / Admin
    semester_id = request.GET.get("semester")
    semester = Semester.objects.filter(pk=semester_id).first() if semester_id else active
    semesters = Semester.objects.select_related("academic_year").all()

    if user.is_program_head:
        programs = Program.objects.filter(program_head=user)
    else:
        programs = Program.objects.all()

    return render(
        request,
        "reports/index_admin.html",
        {
            "page_title": "Reports",
            "semester": semester,
            "semesters": semesters,
            "programs": programs,
            "is_admin": user.is_admin_role,
        },
    )


def _scope_programs(request):
    """Programs the current user may see report data for."""
    if request.user.is_admin_role:
        program_id = request.GET.get("program")
        qs = Program.objects.all()
        return qs.filter(pk=program_id) if program_id else qs
    return Program.objects.filter(program_head=request.user)


def _get_report_semester(request):
    semester_id = request.GET.get("semester")
    if semester_id:
        return get_object_or_404(Semester, pk=semester_id)
    return Semester.objects.filter(is_active=True).first()


@role_required(ADMIN, PROGRAM_HEAD)
def submission_status(request):
    semester = _get_report_semester(request)
    programs = _scope_programs(request)
    rows = submission_status_rows(semester, programs) if semester else []

    if request.GET.get("export") == "excel":
        workbook = excel.build_submission_status_workbook(semester, rows)
        return excel.workbook_response(workbook, f"GradeSubmissionStatus_{semester}.xlsx" if semester else "GradeSubmissionStatus.xlsx")

    return render(
        request,
        "reports/submission_status.html",
        {"page_title": "Grade Submission Status", "semester": semester, "rows": rows, "semesters": Semester.objects.all()},
    )


@role_required(ADMIN, PROGRAM_HEAD)
def class_performance(request):
    semester = _get_report_semester(request)
    programs = _scope_programs(request)
    rows = class_performance_rows(semester, programs) if semester else []

    if request.GET.get("export") == "excel":
        workbook = excel.build_class_performance_workbook(semester, rows)
        return excel.workbook_response(workbook, f"ClassPerformance_{semester}.xlsx" if semester else "ClassPerformance.xlsx")

    return render(
        request,
        "reports/class_performance.html",
        {"page_title": "Class Performance Summary", "semester": semester, "rows": rows, "semesters": Semester.objects.all()},
    )


@role_required(ADMIN, PROGRAM_HEAD)
def failing_inc(request):
    semester = _get_report_semester(request)
    programs = _scope_programs(request)
    rows = failing_inc_rows(semester, programs) if semester else []

    if request.GET.get("export") == "excel":
        workbook = excel.build_failing_inc_workbook(semester, rows)
        return excel.workbook_response(workbook, f"FailingINC_{semester}.xlsx" if semester else "FailingINC.xlsx")

    return render(
        request,
        "reports/failing_inc.html",
        {"page_title": "Students with Failing/INC Grades", "semester": semester, "rows": rows, "semesters": Semester.objects.all()},
    )


@role_required(ADMIN, PROGRAM_HEAD)
def program_grade_report_pdf(request, pk):
    program = get_object_or_404(Program, pk=pk)
    if request.user.is_program_head and program.program_head_id != request.user.id:
        raise PermissionDenied("This program is not under your headship.")

    semester = _get_report_semester(request)
    rows = class_performance_rows(semester, Program.objects.filter(pk=program.pk)) if semester else []

    inst, logo_url = _logo_context(request)
    context = {
        "settings": inst,
        "logo_url": logo_url,
        "generated_at": timezone.now(),
        "watermark_text": None,
        "program": program,
        "semester": semester,
        "rows": rows,
    }
    filename = f"ProgramGradeReport_{program.code}.pdf"
    return render_pdf("reports/pdf/program_grade_report.html", context, filename)
