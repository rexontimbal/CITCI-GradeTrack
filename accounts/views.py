import io
import re

import openpyxl
from axes.utils import reset as axes_reset
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash, views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from academics.models import ClassOffering, Major, Program, Section, Semester
from core.crud import EntityListView, trigger_response
from core.htmx import is_htmx
from core.importing import SpreadsheetImportError

from .audit import log_audit
from .bulk_import import (
    build_instructor_preview,
    build_student_preview,
    commit_instructor_import,
    commit_student_import,
    parse_instructor_file,
    parse_student_file,
)
from .decorators import role_required
from .forms import ForcedPasswordChangeForm, ProfileEmailForm, UserForm
from .mixins import RoleRequiredMixin
from .models import AuditLog, User
from .utils import generate_temp_password

ADMIN = User.Role.ADMIN

TABS = [
    ("", "All"),
    (User.Role.ADMIN, "Admins"),
    (User.Role.PROGRAM_HEAD, "Program Heads"),
    (User.Role.INSTRUCTOR, "Instructors"),
    (User.Role.STUDENT, "Students"),
]


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        from reports.models import InstitutionSettings

        context = super().get_context_data(**kwargs)
        context["institution_settings"] = InstitutionSettings.get_solo()
        return context

    def form_valid(self, form):
        """"Remember me" controls whether the session cookie survives a
        browser close — the 30-minute sliding inactivity expiry (the real
        security control) applies either way."""
        response = super().form_valid(form)
        if self.request.POST.get("remember_me"):
            self.request.session.set_expiry(settings.SESSION_COOKIE_AGE)
        else:
            self.request.session.set_expiry(0)
        return response


class LogoutView(auth_views.LogoutView):
    """Logout only via POST (template uses a form, not a link)."""


@login_required
def profile(request):
    if request.method == "POST":
        form = ProfileEmailForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Email updated.")
            return redirect("accounts:profile")
    else:
        form = ProfileEmailForm(instance=request.user)

    context = {"form": form}
    if request.user.is_instructor:
        context["classes_count"] = ClassOffering.objects.filter(instructor=request.user).count()
    return render(request, "accounts/profile.html", context)


@login_required
def help_page(request):
    return render(request, "accounts/help.html")


@login_required
def force_password_change(request):
    """Doubles as the forced first-login screen (must_change_password=True)
    and a voluntary "Change Password" page reachable from the sidebar user
    menu at any time."""
    if request.method == "POST":
        form = ForcedPasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            user.must_change_password = False
            user.save(update_fields=["must_change_password"])
            update_session_auth_hash(request, user)
            messages.success(request, "Password updated.")
            if not user.privacy_consent_at:
                return redirect("accounts:privacy_consent")
            return redirect("dashboard:home")
    else:
        form = ForcedPasswordChangeForm(request.user)
    return render(request, "accounts/force_password_change.html", {"form": form})


@login_required
def privacy_consent(request):
    from reports.models import InstitutionSettings

    if request.user.privacy_consent_at:
        return redirect("dashboard:home")
    if request.method == "POST":
        request.user.privacy_consent_at = timezone.now()
        request.user.save(update_fields=["privacy_consent_at"])
        return redirect("dashboard:home")
    return render(
        request, "accounts/privacy_consent.html", {"institution_settings": InstitutionSettings.get_solo()}
    )


def permission_denied_view(request, exception=None):
    return render(request, "accounts/403.html", status=403)


def not_found_view(request, exception=None):
    """Standalone template (no {% extends base.html %}, no context
    processors) — `loader.render_to_string` without a `request` renders a
    plain Context, never touching the auth/sidebar/active_semester context
    processors that query the DB (Phase 8 part A resilience pass)."""
    from django.http import HttpResponseNotFound
    from django.template import loader

    return HttpResponseNotFound(loader.render_to_string("errors/404.html"))


def server_error_view(request):
    """Same reasoning as not_found_view, and additionally: must never
    itself depend on the database, since this is exactly the view that
    renders when something (often the DB) has already gone wrong."""
    from django.http import HttpResponseServerError
    from django.template import loader

    return HttpResponseServerError(loader.render_to_string("errors/500.html"))


def csrf_failure_view(request, reason=""):
    from django.http import HttpResponseForbidden
    from django.template import loader

    return HttpResponseForbidden(loader.render_to_string("errors/csrf_failure.html"))


# ---------------------------------------------------------------------------
# Users (admin) — replaces the Phase 2 read-only Students list.
# ---------------------------------------------------------------------------


class UserListView(RoleRequiredMixin, EntityListView):
    allowed_roles = (ADMIN,)
    model = User
    list_template = "accounts/users.html"
    table_template = "accounts/_users_filters_and_table.html"
    table_id = "users-filters-and-table"
    page_title = "Users"
    search_fields = ["first_name__icontains", "last_name__icontains", "username__icontains", "id_number__icontains"]
    refresh_event = "refreshUsers"

    def apply_filters(self, request, qs):
        qs = qs.select_related("student_profile", "student_profile__program", "student_profile__major", "student_profile__section")
        role = request.GET.get("role")
        if role:
            qs = qs.filter(role=role)
        status = request.GET.get("status")
        if status in ("active", "inactive"):
            qs = qs.filter(is_active=(status == "active"))
        program = request.GET.get("program")
        if program:
            qs = qs.filter(student_profile__program_id=program)
        major = request.GET.get("major")
        if major:
            qs = qs.filter(student_profile__major_id=major)
        year_level = request.GET.get("year_level")
        if year_level:
            qs = qs.filter(student_profile__year_level=year_level)
        section = request.GET.get("section")
        if section:
            qs = qs.filter(student_profile__section_id=section)
        return qs

    def get_extra_context(self, request):
        counts = {role: User.objects.filter(role=role).count() for role, _ in User.Role.choices}
        counts[""] = User.objects.count()
        return {
            "tabs": TABS,
            "tab_counts": counts,
            "active_tab": request.GET.get("role", ""),
            "programs": Program.objects.filter(is_active=True),
            "majors": Major.objects.filter(is_active=True),
            "sections": Section.objects.select_related("program", "major"),
        }


def _suggest_username(last_name):
    return re.sub(r"[^a-z0-9]", "", (last_name or "").lower()) or "user"


@role_required(ADMIN)
def user_form(request, pk=None):
    user_obj = get_object_or_404(User, pk=pk) if pk else None

    if request.method == "POST":
        form = UserForm(request.POST, instance=user_obj)
        if form.is_valid():
            creating = user_obj is None
            saved_user = form.save(commit=False)
            temp_password = None
            if creating:
                temp_password = generate_temp_password()
                saved_user.set_password(temp_password)
                saved_user.must_change_password = True
            saved_user.save()
            form.save_student_profile(saved_user)
            log_audit(
                request.user,
                AuditLog.Action.USER_CREATED if creating else AuditLog.Action.USER_UPDATED,
                saved_user,
                role=saved_user.role,
            )

            if temp_password:
                return render(
                    request,
                    "accounts/_user_password_reveal.html",
                    {"user": saved_user, "temp_password": temp_password, "refresh_event": "refreshUsers"},
                )
            return trigger_response("refreshUsers", toast=f"{saved_user.full_name} updated.")
        return render(
            request,
            "accounts/_user_form_modal.html",
            {"form": form, "object": user_obj, "modal_title": "Edit User" if user_obj else "Add User"},
        )

    # GET: either the initial modal open, or an HTMX cascade refresh (role/
    # program/major changed) — never validate on a GET, just re-render with
    # the dependent dropdowns narrowed to what's currently selected.
    form = UserForm(instance=user_obj)
    if is_htmx(request) and request.GET:
        for name in form.fields:
            if name in request.GET:
                form.initial[name] = request.GET[name]
        role = request.GET.get("role")
        program_id = request.GET.get("program")
        major_id = request.GET.get("major")
        year_level = request.GET.get("year_level")
        if program_id:
            form.fields["major"].queryset = Major.objects.filter(program_id=program_id, is_active=True)
            section_qs = Section.objects.filter(program_id=program_id)
            if major_id:
                section_qs = section_qs.filter(major_id=major_id)
            if year_level:
                section_qs = section_qs.filter(year_level=year_level)
            form.fields["section"].queryset = section_qs
    else:
        role = user_obj.role if user_obj else None

    return render(
        request,
        "accounts/_user_form_modal.html",
        {
            "form": form,
            "object": user_obj,
            "modal_title": "Edit User" if user_obj else "Add User",
            "selected_role": role,
            "suggested_username": _suggest_username(request.GET.get("last_name", "")) if not user_obj else "",
        },
    )


@role_required(ADMIN)
def user_reset_password(request, pk):
    user_obj = get_object_or_404(User, pk=pk)
    if request.method != "POST":
        return render(request, "accounts/_user_reset_password_confirm.html", {"object": user_obj})

    temp_password = generate_temp_password()
    user_obj.set_password(temp_password)
    user_obj.must_change_password = True
    user_obj.save(update_fields=["password", "must_change_password"])
    log_audit(request.user, AuditLog.Action.PASSWORD_RESET, user_obj)
    return render(
        request,
        "accounts/_user_password_reveal.html",
        {"user": user_obj, "temp_password": temp_password, "refresh_event": "refreshUsers"},
    )


@role_required(ADMIN)
def user_toggle_active(request, pk):
    user_obj = get_object_or_404(User, pk=pk)

    if user_obj.id == request.user.id:
        raise PermissionDenied("You can't deactivate your own account.")

    if user_obj.is_active and user_obj.role == ADMIN:
        other_active_admins = User.objects.filter(role=ADMIN, is_active=True).exclude(pk=user_obj.pk).exists()
        if not other_active_admins:
            raise PermissionDenied("You can't deactivate the last active admin.")

    user_obj.is_active = not user_obj.is_active
    user_obj.save(update_fields=["is_active"])
    log_audit(
        request.user,
        AuditLog.Action.USER_REACTIVATED if user_obj.is_active else AuditLog.Action.USER_DEACTIVATED,
        user_obj,
    )
    verb = "reactivated" if user_obj.is_active else "deactivated"
    return trigger_response("refreshUsers", toast=f"{user_obj.full_name} {verb}.")


@role_required(ADMIN)
def user_unlock(request, pk):
    user_obj = get_object_or_404(User, pk=pk)
    axes_reset(username=user_obj.username)
    log_audit(request.user, AuditLog.Action.ACCOUNT_UNLOCKED, user_obj)
    return trigger_response("refreshUsers", toast=f"{user_obj.full_name}'s account unlocked.")


# ---------------------------------------------------------------------------
# Bulk import — Students / Instructors. Same upload -> preview -> confirm
# shape as the Phase 2.1 class-list importer, sharing its file parser
# (core.importing) and session-stash pattern for the preview step.
# ---------------------------------------------------------------------------

_STUDENT_IMPORT_SESSION_KEY = "student_import_preview"
_INSTRUCTOR_IMPORT_SESSION_KEY = "instructor_import_preview"


@role_required(ADMIN)
def import_students_template(request):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Students"
    sheet.append(["ID Number", "Last Name", "First Name", "Middle Name", "Program Code", "Major Code", "Year Level", "Email"])
    sheet.append(["2026-0001", "Dela Cruz", "Juan", "Santos", "BSED", "ENG", "1", ""])
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="students_import_template.xlsx"'
    return response


@role_required(ADMIN)
def import_instructors_template(request):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Instructors"
    sheet.append(["Employee ID", "Last Name", "First Name", "Middle Name", "Title", "Email"])
    sheet.append(["EMP-0001", "Garibay", "Juan", "Santos", "Mr.", ""])
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="instructors_import_template.xlsx"'
    return response


@role_required(ADMIN)
def import_students(request):
    if request.method != "POST":
        return render(request, "accounts/_bulk_import_modal.html", {"kind": "students"})

    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return render(request, "accounts/_bulk_import_modal.html", {"kind": "students", "error": "Choose a file first."})

    try:
        index, data_rows = parse_student_file(uploaded_file)
    except SpreadsheetImportError as exc:
        return render(request, "accounts/_bulk_import_modal.html", {"kind": "students", "error": str(exc)})

    active_semester = Semester.objects.filter(is_active=True).select_related("academic_year").first()
    active_academic_year = active_semester.academic_year if active_semester else None
    preview = build_student_preview(index, data_rows, active_academic_year)
    request.session[_STUDENT_IMPORT_SESSION_KEY] = preview

    return render(
        request,
        "accounts/_bulk_import_preview.html",
        {
            "kind": "students",
            "preview": preview,
            "new_count": sum(1 for r in preview if r["kind"] == "new"),
            "update_count": sum(1 for r in preview if r["kind"] == "update"),
            "invalid_count": sum(1 for r in preview if r["kind"] == "invalid"),
        },
    )


@role_required(ADMIN)
def import_students_confirm(request):
    rows = request.session.get(_STUDENT_IMPORT_SESSION_KEY) or []
    summary = commit_student_import(rows)
    if _STUDENT_IMPORT_SESSION_KEY in request.session:
        del request.session[_STUDENT_IMPORT_SESSION_KEY]

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "New Accounts"
    sheet.append(["Username", "ID Number", "Name", "Temporary Password"])
    for row in rows:
        if row.get("temp_password"):
            sheet.append([row["username"], row["id_number"], f"{row['first_name']} {row['last_name']}", row["temp_password"]])
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="new_student_passwords.xlsx"'
    response["X-Import-Summary"] = f"{summary['created']} created, {summary['updated']} updated"
    return response


@role_required(ADMIN)
def import_instructors(request):
    if request.method != "POST":
        return render(request, "accounts/_bulk_import_modal.html", {"kind": "instructors"})

    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return render(request, "accounts/_bulk_import_modal.html", {"kind": "instructors", "error": "Choose a file first."})

    try:
        index, data_rows = parse_instructor_file(uploaded_file)
    except SpreadsheetImportError as exc:
        return render(request, "accounts/_bulk_import_modal.html", {"kind": "instructors", "error": str(exc)})

    preview = build_instructor_preview(index, data_rows)
    request.session[_INSTRUCTOR_IMPORT_SESSION_KEY] = preview

    return render(
        request,
        "accounts/_bulk_import_preview.html",
        {
            "kind": "instructors",
            "preview": preview,
            "new_count": sum(1 for r in preview if r["kind"] == "new"),
            "update_count": sum(1 for r in preview if r["kind"] == "update"),
            "invalid_count": sum(1 for r in preview if r["kind"] == "invalid"),
        },
    )


@role_required(ADMIN)
def import_instructors_confirm(request):
    rows = request.session.get(_INSTRUCTOR_IMPORT_SESSION_KEY) or []
    summary = commit_instructor_import(rows)
    if _INSTRUCTOR_IMPORT_SESSION_KEY in request.session:
        del request.session[_INSTRUCTOR_IMPORT_SESSION_KEY]

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "New Accounts"
    sheet.append(["Username", "Employee ID", "Name", "Temporary Password"])
    for row in rows:
        if row.get("temp_password"):
            sheet.append([row["username"], row["id_number"], f"{row['first_name']} {row['last_name']}", row["temp_password"]])
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="new_instructor_passwords.xlsx"'
    response["X-Import-Summary"] = f"{summary['created']} created, {summary['updated']} updated"
    return response


# ---------------------------------------------------------------------------
# Audit Log (Phase 8 part A) — combines accounts.AuditLog, grading score/
# component change logs, and approvals grade-sheet transitions/corrections
# into one filterable, admin-only view. See accounts/audit.py for the
# normalization logic.
# ---------------------------------------------------------------------------


def _audit_log_filters(request):
    from django.utils.dateparse import parse_date

    date_from = parse_date(request.GET.get("date_from", "")) if request.GET.get("date_from") else None
    date_to = parse_date(request.GET.get("date_to", "")) if request.GET.get("date_to") else None
    source = request.GET.get("source") or None
    username = request.GET.get("username", "").strip()
    user = User.objects.filter(username__iexact=username).first() if username else None
    return date_from, date_to, source, username, user


@role_required(ADMIN)
def audit_log(request):
    from django.core.paginator import Paginator

    from .audit import SOURCES, collect_audit_rows

    date_from, date_to, source, username, user = _audit_log_filters(request)
    rows = collect_audit_rows(date_from=date_from, date_to=date_to, user=user, source=source)
    paginator = Paginator(rows, 50)
    page = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "accounts/audit_log.html",
        {
            "page": page,
            "sources": SOURCES,
            "selected_source": source,
            "date_from": request.GET.get("date_from", ""),
            "date_to": request.GET.get("date_to", ""),
            "username": username,
            "total_count": len(rows),
        },
    )


@role_required(ADMIN)
def audit_log_export(request):
    from .audit import collect_audit_rows

    date_from, date_to, source, username, user = _audit_log_filters(request)
    rows = collect_audit_rows(date_from=date_from, date_to=date_to, user=user, source=source)

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Audit Log"
    sheet.append(["Timestamp", "Source", "Action", "Actor", "Target", "Details"])
    for row in rows:
        sheet.append(
            [
                timezone.localtime(row["timestamp"]).strftime("%Y-%m-%d %H:%M:%S"),
                row["source"],
                row["action"],
                str(row["actor"]) if row["actor"] else "",
                str(row["target"]) if row["target"] else "",
                ", ".join(f"{k}={v}" for k, v in row["details"].items()) if row["details"] else "",
            ]
        )
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="audit_log.xlsx"'
    return response
