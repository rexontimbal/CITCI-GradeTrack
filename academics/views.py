import io
import json
from datetime import date
from decimal import Decimal

import openpyxl
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, ProtectedError, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views import View

from accounts.decorators import role_required
from accounts.mixins import RoleRequiredMixin
from accounts.models import User
from core.crud import EntityDeleteView, EntityFormView, EntityListView, ToggleActiveView, trigger_response
from core.htmx import is_htmx

from . import scoping
from .forms import (
    AcademicYearForm,
    AdhocOfferingForm,
    AdminSubjectForm,
    ClassOfferingForm,
    JoinClassForm,
    JoinCodeForm,
    MajorForm,
    ProgramForm,
    ProgramHeadClassOfferingForm,
    ProgramHeadSectionForm,
    SectionForm,
    SemesterForm,
    SubjectAddForm,
    SubjectCodeCorrectionForm,
    SubjectEditForm,
    TeachingAssignmentForm,
)
from . import services
from .models import (
    YEAR_LEVEL_CHOICES,
    AcademicSetupChangeLog,
    AcademicYear,
    ClassJoinRequest,
    ClassOffering,
    ClassRosterEntry,
    CurriculumEntry,
    Major,
    Program,
    Section,
    SectionMembership,
    Semester,
    SemesterStatus,
    StudentProfile,
    Subject,
    SubjectOffering,
    Term,
)
from .ay_wizard import step1_preview, step2_preview_sections, step3_preview_promotions, step4_commit
from .offerings_import import (
    SpreadsheetImportError,
    build_offerings_preview,
    commit_offerings_import,
    parse_offerings_docx_for_preview,
    parse_offerings_xlsx,
)
from .roster_import import RosterImportError, build_preview, commit_import, parse_roster_file
from .services import (
    assign_instructor,
    build_copy_preview,
    check_instructor_change_allowed,
    commit_copy,
    commit_subject_offerings,
    default_source_semester,
    log_and_notify_instructor_change,
    notify_program_head_assignment,
    preview_adhoc_offering,
    preview_subject_offerings,
    teaching_load_rows,
    withdraw_offering,
)

ADMIN = User.Role.ADMIN
PROGRAM_HEAD = User.Role.PROGRAM_HEAD
INSTRUCTOR = User.Role.INSTRUCTOR
STUDENT = User.Role.STUDENT


# ---------------------------------------------------------------------------
# Academic Years & Semesters — one page, two small tables (no search/paging:
# these lists stay short, so the generic EntityListView machinery is more
# than they need — plain function views keep this simple).
# ---------------------------------------------------------------------------


@role_required(ADMIN)
def terms(request):
    context = {
        "page_title": "Academic Years & Semesters",
        "academic_years": AcademicYear.objects.all(),
        "semesters": Semester.objects.select_related("academic_year").all(),
        "latest_semester": Semester.objects.order_by("-created_at").first(),
    }
    return render(request, "academics/terms.html", context)


@role_required(ADMIN)
def academic_years_table(request):
    return render(request, "academics/_academic_years_table.html", {"academic_years": AcademicYear.objects.all()})


@role_required(ADMIN)
def semesters_table(request):
    return render(
        request,
        "academics/_semesters_table.html",
        {
            "semesters": Semester.objects.select_related("academic_year").all(),
            "latest_semester": Semester.objects.order_by("-created_at").first(),
        },
    )


class AcademicYearFormView(RoleRequiredMixin, EntityFormView):
    allowed_roles = (ADMIN,)
    model = AcademicYear
    form_class = AcademicYearForm
    refresh_event = "refreshYears"
    modal_title_create = "Add Academic Year"
    modal_title_edit = "Edit Academic Year"


class AcademicYearDeleteView(RoleRequiredMixin, EntityDeleteView):
    allowed_roles = (ADMIN,)
    model = AcademicYear
    refresh_event = "refreshYears"
    protect_message = "This academic year has semesters, sections, or other records using it."


class SemesterFormView(RoleRequiredMixin, EntityFormView):
    allowed_roles = (ADMIN,)
    model = Semester
    form_class = SemesterForm
    refresh_event = "refreshSemesters"
    modal_title_create = "Add Semester"
    modal_title_edit = "Edit Semester"

    def post(self, request, pk=None):
        obj = self.get_object(pk)
        is_create = obj is None
        had_active_before = Semester.objects.filter(is_active=True).exists()
        form = self.form_class(request.POST, instance=obj)
        if not form.is_valid():
            return render(request, self.form_template, self.get_context(request, form, obj))

        saved = form.save()
        verb = "updated" if obj else "created"
        toast = f"Semester {verb}."
        toast_level = "success"
        if form.duration_warning:
            toast = f"{toast} {form.duration_warning}"
            toast_level = "warning"

        if is_create and not had_active_before:
            response = render(request, "academics/_semester_activate_prompt.html", {"semester": saved})
            response["HX-Trigger"] = json.dumps(
                {self.refresh_event: True, "toast": {"message": toast, "level": toast_level}}
            )
            return response

        return trigger_response(self.refresh_event, toast=toast, toast_level=toast_level)


class SemesterDeleteView(RoleRequiredMixin, EntityDeleteView):
    allowed_roles = (ADMIN,)
    model = Semester
    refresh_event = "refreshSemesters"
    protect_message = "This semester has classes or other records using it."


class SemesterSetActiveView(RoleRequiredMixin, View):
    allowed_roles = (ADMIN,)

    def post(self, request, pk):
        semester = get_object_or_404(Semester, pk=pk)
        semester.is_active = True
        semester.save()  # model.save() deactivates every other semester in a transaction
        return trigger_response("refreshSemesters", toast=f"{semester} is now the active semester.")


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------


class ProgramListView(RoleRequiredMixin, EntityListView):
    allowed_roles = (ADMIN,)
    model = Program
    list_template = "academics/programs.html"
    table_template = "academics/_programs_table.html"
    table_id = "programs-table"
    page_title = "Programs"
    search_fields = ["code__icontains", "name__icontains"]
    refresh_event = "refreshPrograms"

    def apply_filters(self, request, qs):
        is_active = request.GET.get("is_active")
        if is_active in ("true", "false"):
            qs = qs.filter(is_active=(is_active == "true"))
        return qs.select_related("program_head")


class ProgramFormView(RoleRequiredMixin, EntityFormView):
    allowed_roles = (ADMIN,)
    model = Program
    form_class = ProgramForm
    refresh_event = "refreshPrograms"
    modal_title_create = "Add Program"
    modal_title_edit = "Edit Program"

    def post(self, request, pk=None):
        obj = self.get_object(pk)
        old_head = obj.program_head if obj else None
        form = self.form_class(request.POST, instance=obj)
        if form.is_valid():
            program = form.save()
            notify_program_head_assignment(program, old_head, program.program_head)
            verb = "updated" if obj else "created"
            return trigger_response(self.refresh_event, toast=f"Program {verb}.")
        return render(request, self.form_template, self.get_context(request, form, obj))


class ProgramDeleteView(RoleRequiredMixin, EntityDeleteView):
    allowed_roles = (ADMIN,)
    model = Program
    refresh_event = "refreshPrograms"
    label_field = "code"
    deactivate_url_name = "academics:program_toggle_active"
    protect_message = "This program has majors, sections, subjects, or students using it."


class ProgramToggleActiveView(RoleRequiredMixin, ToggleActiveView):
    allowed_roles = (ADMIN,)
    model = Program
    refresh_event = "refreshPrograms"


# ---------------------------------------------------------------------------
# Majors
# ---------------------------------------------------------------------------


class MajorListView(RoleRequiredMixin, EntityListView):
    allowed_roles = (ADMIN,)
    model = Major
    list_template = "academics/majors.html"
    table_template = "academics/_majors_table.html"
    table_id = "majors-table"
    page_title = "Majors"
    search_fields = ["code__icontains", "name__icontains"]
    refresh_event = "refreshMajors"

    def apply_filters(self, request, qs):
        qs = qs.select_related("program", "program_head")
        program = request.GET.get("program")
        if program:
            qs = qs.filter(program_id=program)
        return qs

    def get_extra_context(self, request):
        return {"programs": Program.objects.all()}


class MajorFormView(RoleRequiredMixin, EntityFormView):
    allowed_roles = (ADMIN,)
    model = Major
    form_class = MajorForm
    refresh_event = "refreshMajors"
    modal_title_create = "Add Major"
    modal_title_edit = "Edit Major"

    def post(self, request, pk=None):
        obj = self.get_object(pk)
        old_head = obj.program_head if obj else None
        form = self.form_class(request.POST, instance=obj)
        if form.is_valid():
            major = form.save()
            notify_program_head_assignment(major, old_head, major.program_head)
            verb = "updated" if obj else "created"
            return trigger_response(self.refresh_event, toast=f"Major {verb}.")
        return render(request, self.form_template, self.get_context(request, form, obj))


class MajorDeleteView(RoleRequiredMixin, EntityDeleteView):
    allowed_roles = (ADMIN,)
    model = Major
    refresh_event = "refreshMajors"
    protect_message = "This major has sections, subjects, or students using it."


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


class SectionFormView(RoleRequiredMixin, EntityFormView):
    """Admin's Sections CRUD — normally the Program Head's own job (see
    academics:ph_sections); every save here is logged as an admin
    override."""

    allowed_roles = (ADMIN,)
    model = Section
    form_class = SectionForm
    refresh_event = "refreshSections"
    modal_title_create = "Add Section"
    modal_title_edit = "Edit Section"

    def get(self, request, pk=None):
        obj = self.get_object(pk)
        initial = {}
        if obj is None:
            program_id = request.GET.get("program")
            major_id = request.GET.get("major")
            year_level = request.GET.get("year_level")
            if program_id:
                initial["program"] = program_id
            if major_id:
                initial["major"] = major_id
            if year_level:
                initial["year_level"] = year_level
            active_ay = _active_academic_year()
            if active_ay:
                initial["academic_year"] = active_ay.pk
            if program_id and year_level:
                initial["name"] = services.next_section_letter(
                    Program.objects.filter(pk=program_id).first(),
                    Major.objects.filter(pk=major_id).first() if major_id else None,
                    active_ay,
                    int(year_level),
                )
        form = self.form_class(instance=obj, initial=initial)
        return render(request, self.form_template, self.get_context(request, form, obj))

    def post(self, request, pk=None):
        obj = self.get_object(pk)
        is_create = obj is None
        form = self.form_class(request.POST, instance=obj)
        if not form.is_valid():
            return render(request, self.form_template, self.get_context(request, form, obj))
        saved = form.save()
        _log_academic_setup_change(
            AcademicSetupChangeLog.ModelName.SECTION,
            saved,
            AcademicSetupChangeLog.Action.CREATED if is_create else AcademicSetupChangeLog.Action.UPDATED,
            request.user,
            is_admin_override=True,
        )
        verb = "updated" if obj else "created"
        return trigger_response(self.refresh_event, toast=f"Section {verb}.")


class SectionDeleteView(RoleRequiredMixin, EntityDeleteView):
    allowed_roles = (ADMIN,)
    model = Section
    refresh_event = "refreshSections"
    protect_message = "This section has classes or students using it."


# ---------------------------------------------------------------------------
# Program Head — Sections (hand-written, matching the style already used
# for program_head_classes/my_classes/class_lists_home rather than
# core.crud, since EntityFormView has no hook for scoping a form's
# querysets to the acting user). Section has no is_active field (neither
# does admin's own SectionDeleteView offer a "deactivate instead" fallback
# today) — create/edit/delete, same ProtectedError handling as admin's.
# ---------------------------------------------------------------------------


def _active_academic_year():
    active = Semester.objects.filter(is_active=True).first()
    return active.academic_year if active else None


def _require_semester_unlocked(class_offering):
    """Raises PermissionDenied if class_offering's semester is CLOSED --
    offerings/classes/rosters/instructor assignment are all read-only once
    a semester closes (grade corrections are exempt — they go through
    approvals.services.correct_grade's own RELEASED/LOCKED-only gate,
    independent of semester status)."""
    if services.is_semester_locked(class_offering.semester):
        raise PermissionDenied("This semester is closed and read-only.")


def _log_academic_setup_change(model_name, obj, action, actor, is_admin_override, program=None, major=None, **details):
    AcademicSetupChangeLog.objects.create(
        model_name=model_name,
        object_id=obj.pk,
        object_repr=str(obj),
        action=action,
        program=program if program is not None else getattr(obj, "program", None),
        major=major if major is not None else getattr(obj, "major", None),
        actor=actor,
        is_admin_override=is_admin_override,
        details=details,
    )


def _selected_sections_from_request(request, section_queryset):
    """The sections multi-select's live/in-progress value, carried via
    `?sections=<pk>&sections=<pk>` on the hx-get re-render that fires
    when the field changes — None (not an empty list) when no `sections`
    param is present at all, so callers can tell "nothing selected yet"
    apart from "the field was submitted empty"."""
    ids = request.GET.getlist("sections") or request.POST.getlist("sections")
    if not ids:
        return None
    return list(section_queryset.filter(pk__in=ids))


def _wire_live_subject_regroup(form, url):
    """Re-renders the whole modal (recomputing the subject field's
    curriculum-aware grouping) whenever the sections field changes —
    same re-render-on-change mechanic as the User form's role-dependent
    fields (templates/accounts/_user_form_modal.html)."""
    if "sections" in form.fields:
        form.fields["sections"].widget.attrs.update(
            {
                "hx-get": url,
                "hx-include": "[name='sections']",
                "hx-target": "#modal-content",
                "hx-swap": "innerHTML",
                "hx-trigger": "change",
            }
        )


@role_required(ADMIN, PROGRAM_HEAD)
def sections_home(request):
    """Shared Sections prospectus for admin (program/major selector, every
    program) and Program Head (segmented major pills, scoped) — same
    shape as academics.views.subjects_home: a toolbar (major scope +
    Academic Year, sections aren't term-scoped so there's no Semester
    dropdown) over year-level cards. "Classes this semester" is counted
    against whatever semester is currently is_active=True, independent of
    the Academic Year filter (a section can exist across several AYs but
    "this semester" only ever means one)."""
    is_admin = request.user.is_admin_role
    pills = None if is_admin else _build_pills(request.user)
    program, major = _resolve_program_major_from_request(request, request.user, pills=pills)

    context = {"page_title": "Sections", "is_admin": is_admin, "program": program, "major": major}
    if program is None:
        context["no_scope"] = True
        return render(request, "academics/sections.html", context)

    academic_years = AcademicYear.objects.all()
    selected_ay_id = request.GET.get("ay")
    selected_ay = AcademicYear.objects.filter(pk=selected_ay_id).first() if selected_ay_id else None
    if selected_ay is None:
        selected_ay = _active_academic_year() or academic_years.first()

    year_level_filter = request.GET.get("year_level", "ALL")
    query = request.GET.get("q", "").strip()

    sections_qs = Section.objects.filter(program=program, major=major)
    if selected_ay:
        sections_qs = sections_qs.filter(academic_year=selected_ay)
    if query:
        sections_qs = sections_qs.filter(name__icontains=query)
    sections_qs = sections_qs.select_related("program", "major", "academic_year").annotate(
        student_count=Count(
            "memberships",
            filter=Q(memberships__student__student_profile__status=StudentProfile.Status.ACTIVE),
            distinct=True,
        )
    )
    all_sections = list(sections_qs)

    active_semester = Semester.objects.filter(is_active=True).first()
    class_counts = {}
    if active_semester and all_sections:
        rows = (
            ClassOffering.objects.filter(sections__in=all_sections, semester=active_semester)
            .values("sections__id")
            .annotate(c=Count("id", distinct=True))
        )
        class_counts = {row["sections__id"]: row["c"] for row in rows}
    delete_url_name = "academics:section_delete" if is_admin else "academics:ph_section_delete"
    for section in all_sections:
        section.classes_this_semester = class_counts.get(section.id, 0)
        section.row_actions = [
            {"label": "Delete", "hx_get": reverse(delete_url_name, args=[section.pk]), "extra_classes": "text-red-600 hover:bg-red-50"}
        ]

    available_year_levels = sorted({s.year_level for s in all_sections if s.year_level is not None})
    if year_level_filter and year_level_filter != "ALL":
        yl = int(year_level_filter)
        all_sections = [s for s in all_sections if s.year_level == yl]

    year_levels = sorted({s.year_level for s in all_sections if s.year_level is not None})
    has_no_year_level_rows = any(s.year_level is None for s in all_sections)
    cards = [{"year_level": yl, "rows": [s for s in all_sections if s.year_level == yl]} for yl in year_levels]
    if has_no_year_level_rows or not year_levels:
        cards.append({"year_level": None, "rows": [s for s in all_sections if s.year_level is None]})

    context.update(
        {
            "cards": cards,
            "academic_years": academic_years,
            "selected_ay_id": selected_ay.pk if selected_ay else None,
            "year_level_filter": year_level_filter,
            "available_year_levels": available_year_levels,
            "query": query,
            "section_count": len(all_sections),
        }
    )
    if is_admin:
        context["programs"] = Program.objects.filter(is_active=True).order_by("code")
        context["majors"] = Major.objects.filter(program=program, is_active=True).order_by("code")
    else:
        for pill in pills:
            pill["active"] = program.id == pill["program"].id and (
                (major.id if major else None) == (pill["major"].id if pill["major"] else None)
            )
        context["pills"] = pills

    template = "academics/_sections_prospectus.html" if is_htmx(request) else "academics/sections.html"
    return render(request, template, context)


def _section_in_scope_or_403(request, section):
    if not scoping.is_in_scope(request.user, section.program_id, section.major_id):
        raise PermissionDenied("This section is not under your program.")


@role_required(PROGRAM_HEAD)
def ph_section_create(request):
    academic_year = _active_academic_year()
    if academic_year is None:
        raise PermissionDenied("No active semester is set.")

    if request.method != "POST":
        program_id = request.GET.get("program")
        major_id = request.GET.get("major")
        year_level = request.GET.get("year_level")
        initial = {}
        if program_id:
            initial["program"] = program_id
        if major_id:
            initial["major"] = major_id
        if year_level:
            initial["year_level"] = year_level
            initial["name"] = services.next_section_letter(
                Program.objects.filter(pk=program_id).first(),
                Major.objects.filter(pk=major_id).first() if major_id else None,
                academic_year,
                int(year_level),
            )
        form = ProgramHeadSectionForm(user=request.user, initial=initial)
        return render(request, "partials/_entity_form_modal.html", {"form": form, "modal_title": "Add Section"})

    form = ProgramHeadSectionForm(request.POST, user=request.user)
    if form.is_valid():
        section = form.save(commit=False)
        section.academic_year = academic_year
        section.save()
        _log_academic_setup_change(
            AcademicSetupChangeLog.ModelName.SECTION,
            section,
            AcademicSetupChangeLog.Action.CREATED,
            request.user,
            is_admin_override=False,
        )
        return trigger_response("refreshSections", toast="Section created.")
    return render(request, "partials/_entity_form_modal.html", {"form": form, "modal_title": "Add Section"})


@role_required(PROGRAM_HEAD)
def ph_section_edit(request, pk):
    section = get_object_or_404(Section, pk=pk)
    _section_in_scope_or_403(request, section)

    if request.method != "POST":
        form = ProgramHeadSectionForm(instance=section, user=request.user)
        return render(request, "partials/_entity_form_modal.html", {"form": form, "modal_title": "Edit Section"})

    form = ProgramHeadSectionForm(request.POST, instance=section, user=request.user)
    if form.is_valid():
        section = form.save(commit=False)
        section.academic_year = _active_academic_year()
        section.save()
        _log_academic_setup_change(
            AcademicSetupChangeLog.ModelName.SECTION,
            section,
            AcademicSetupChangeLog.Action.UPDATED,
            request.user,
            is_admin_override=False,
        )
        return trigger_response("refreshSections", toast="Section updated.")
    return render(request, "partials/_entity_form_modal.html", {"form": form, "modal_title": "Edit Section"})


@role_required(PROGRAM_HEAD)
def ph_section_delete(request, pk):
    """Section has no is_active field (confirmed against the model — admin's
    own SectionDeleteView has no deactivate fallback either), so this is a
    straight delete with the same ProtectedError handling
    core.crud.EntityDeleteView gives admin pages, replicated by hand."""
    section = get_object_or_404(Section, pk=pk)
    _section_in_scope_or_403(request, section)

    if request.method != "POST":
        return render(
            request, "partials/_confirm_delete_modal.html", {"object": section, "label": str(section), "protect_error": ""}
        )

    label = str(section)
    section_pk, program, major = section.pk, section.program, section.major
    try:
        section.delete()
    except ProtectedError:
        return render(
            request,
            "partials/_confirm_delete_modal.html",
            {
                "object": section,
                "label": label,
                "protect_error": "This section has classes or students using it.",
                "can_deactivate": False,
            },
        )
    AcademicSetupChangeLog.objects.create(
        model_name=AcademicSetupChangeLog.ModelName.SECTION,
        object_id=section_pk,
        object_repr=label,
        action=AcademicSetupChangeLog.Action.DEACTIVATED,
        program=program,
        major=major,
        actor=request.user,
        is_admin_override=False,
        details={"note": "deleted"},
    )
    return trigger_response("refreshSections", toast=f"{label} deleted.")


def _can_manage_section(user, section):
    if user.is_admin_role:
        return True
    return scoping.is_in_scope(user, section.program_id, section.major_id)


_TERM_ORDER = {"FIRST": 0, "SECOND": 1, "SUMMER": 2}


def _section_students_semester(request, section):
    """The semester this page manages membership for -- ?semester=<id> if
    given and valid for this section's academic year, else the active
    semester if it belongs to this academic year, else the first semester
    that exists for it."""
    semester_id = request.GET.get("semester") or request.POST.get("semester")
    qs = Semester.objects.filter(academic_year=section.academic_year)
    if semester_id:
        semester = qs.filter(pk=semester_id).first()
        if semester:
            return semester
    active = qs.filter(is_active=True).first()
    return active or qs.order_by("term").first()


def _previous_semester_same_section(semester):
    """The semester immediately before `semester` IN THE SAME academic
    year (1st Sem -> 2nd Sem's previous is 1st Sem) -- "Copy from previous
    semester" is deliberately scoped to the same section/academic year,
    not a cross-year copy (that's the AY wizard's Promote job instead)."""
    order = _TERM_ORDER.get(semester.term)
    if order is None or order == 0:
        return None
    candidates = Semester.objects.filter(academic_year=semester.academic_year).exclude(pk=semester.pk)
    earlier = [s for s in candidates if _TERM_ORDER.get(s.term, 99) < order]
    return max(earlier, key=lambda s: _TERM_ORDER.get(s.term, -1)) if earlier else None


@role_required(ADMIN, PROGRAM_HEAD)
def section_students(request, pk):
    """A section's student list FOR ONE SEMESTER, with a "Move to
    section…" bulk action restricted to other sections sharing the same
    program/major/year_level (moving across year levels is the AY
    wizard's/Promote's job, not this one), "Add students", "Remove", and
    "Copy from previous semester"."""
    section = get_object_or_404(Section.objects.select_related("program", "major", "academic_year"), pk=pk)
    if not _can_manage_section(request.user, section):
        raise PermissionDenied("This section is not under your program.")

    semester = _section_students_semester(request, section)
    semesters = Semester.objects.filter(academic_year=section.academic_year).order_by("term")

    target_sections = (
        Section.objects.filter(
            program=section.program, major=section.major, academic_year=section.academic_year, year_level=section.year_level
        )
        .exclude(pk=section.pk)
        .order_by("name")
    )
    memberships = (
        SectionMembership.objects.filter(section=section, semester=semester)
        .select_related("student")
        .order_by("student__last_name", "student__first_name")
        if semester
        else SectionMembership.objects.none()
    )
    member_ids = set(memberships.values_list("student_id", flat=True))
    addable_students = (
        User.objects.filter(
            role=User.Role.STUDENT,
            is_active=True,
            student_profile__program=section.program,
            student_profile__major=section.major,
            student_profile__status=StudentProfile.Status.ACTIVE,
        )
        .exclude(pk__in=member_ids)
        .order_by("last_name", "first_name")
        if semester
        else User.objects.none()
    )
    previous_semester = _previous_semester_same_section(semester) if semester else None
    return render(
        request,
        "academics/section_students.html",
        {
            "page_title": f"Students — {section}",
            "section": section,
            "semester": semester,
            "semesters": semesters,
            "memberships": memberships,
            "addable_students": addable_students,
            "target_sections": target_sections,
            "previous_semester": previous_semester,
        },
    )


@role_required(ADMIN, PROGRAM_HEAD)
def section_students_move(request, pk):
    section = get_object_or_404(Section, pk=pk)
    if not _can_manage_section(request.user, section):
        raise PermissionDenied("This section is not under your program.")
    if request.method != "POST":
        raise PermissionDenied

    semester = get_object_or_404(Semester, pk=request.POST.get("semester"))
    target_id = request.POST.get("target_section")
    target_section = get_object_or_404(
        Section.objects.filter(
            program=section.program, major=section.major, academic_year=section.academic_year, year_level=section.year_level
        ),
        pk=target_id,
    )
    student_ids = request.POST.getlist("student_ids")
    moved = services.move_students_to_section(
        student_ids, target_section, semester, request.user, is_admin_override=request.user.is_admin_role
    )
    return trigger_response("refreshSectionStudents", toast=f"Moved {moved} student{'s' if moved != 1 else ''} to {target_section}.")


@role_required(ADMIN, PROGRAM_HEAD)
def section_students_add(request, pk):
    section = get_object_or_404(Section, pk=pk)
    if not _can_manage_section(request.user, section):
        raise PermissionDenied("This section is not under your program.")
    if request.method != "POST":
        raise PermissionDenied

    semester = get_object_or_404(Semester, pk=request.POST.get("semester"))
    student_ids = request.POST.getlist("student_ids")
    added = services.move_students_to_section(
        student_ids, section, semester, request.user, is_admin_override=request.user.is_admin_role
    )
    return trigger_response("refreshSectionStudents", toast=f"Added {added} student{'s' if added != 1 else ''} to {section}.")


@role_required(ADMIN, PROGRAM_HEAD)
def section_students_remove(request, pk):
    section = get_object_or_404(Section, pk=pk)
    if not _can_manage_section(request.user, section):
        raise PermissionDenied("This section is not under your program.")
    if request.method != "POST":
        raise PermissionDenied

    semester = get_object_or_404(Semester, pk=request.POST.get("semester"))
    student_ids = request.POST.getlist("student_ids")
    removed = services.remove_section_membership(student_ids, semester, request.user)
    return trigger_response("refreshSectionStudents", toast=f"Removed {removed} student{'s' if removed != 1 else ''} from {section}.")


@role_required(ADMIN, PROGRAM_HEAD)
def section_students_copy_previous(request, pk):
    section = get_object_or_404(Section, pk=pk)
    if not _can_manage_section(request.user, section):
        raise PermissionDenied("This section is not under your program.")

    semester = get_object_or_404(Semester, pk=request.POST.get("semester") or request.GET.get("semester"))
    previous_semester = _previous_semester_same_section(semester)
    if previous_semester is None:
        raise PermissionDenied("No earlier semester to copy from.")

    if request.method != "POST":
        previous_members = SectionMembership.objects.filter(section=section, semester=previous_semester).select_related("student")
        return render(
            request,
            "academics/_section_copy_previous_confirm.html",
            {"section": section, "semester": semester, "previous_semester": previous_semester, "previous_members": previous_members},
        )

    added = services.copy_section_membership_to_semester(section, previous_semester, semester, request.user)
    return trigger_response("refreshSectionStudents", toast=f"Copied {added} student{'s' if added != 1 else ''} from {previous_semester}.")


@role_required(ADMIN, PROGRAM_HEAD)
def section_promote(request, pk):
    """Promote selected students from `section` (e.g. BSED-ENG 1-A) into
    a target section the caller picks (typically BSED-ENG 2-A in a newer
    academic year) for a target semester they pick -- a lighter, Program-
    Head-reachable counterpart to the AY wizard's system-wide promotion
    step, for moving one section at a time. Irregulars (already placed in
    the target semester) are pre-unchecked, never silently moved."""
    section = get_object_or_404(Section, pk=pk)
    if not _can_manage_section(request.user, section):
        raise PermissionDenied("This section is not under your program.")

    semester = get_object_or_404(Semester, pk=request.POST.get("semester") or request.GET.get("semester"))

    target_section_id = request.POST.get("target_section") or request.GET.get("target_section")
    if not target_section_id or "target_semester" not in request.POST:
        target_sections = (
            Section.objects.filter(program=section.program, major=section.major)
            .exclude(academic_year=section.academic_year)
            .select_related("academic_year")
            .order_by("-academic_year__start_year", "name")
        )
        target_semesters = []
        if target_section_id:
            target_section_candidate = Section.objects.filter(pk=target_section_id).first()
            if target_section_candidate:
                target_semesters = Semester.objects.filter(academic_year=target_section_candidate.academic_year).order_by("term")
        return render(
            request,
            "academics/_section_promote_pick_target.html",
            {
                "section": section,
                "semester": semester,
                "target_sections": target_sections,
                "selected_target_section_id": int(target_section_id) if target_section_id else None,
                "target_semesters": target_semesters,
            },
        )

    target_section = get_object_or_404(Section, pk=target_section_id)
    target_semester = get_object_or_404(Semester, pk=request.POST.get("target_semester"))

    if "confirm" not in request.POST:
        rows = services.preview_promote_students(section, semester, target_section, target_semester)
        return render(
            request,
            "academics/_section_promote_confirm.html",
            {
                "section": section,
                "semester": semester,
                "target_section": target_section,
                "target_semester": target_semester,
                "rows": rows,
            },
        )

    student_ids = request.POST.getlist("student_ids")
    promoted = services.commit_promote_students(student_ids, target_section, target_semester, request.user)
    return trigger_response(
        "refreshSectionStudents", toast=f"Promoted {promoted} student{'s' if promoted != 1 else ''} to {target_section}."
    )


# ---------------------------------------------------------------------------
# Subjects — prospectus-style, shared by Admin (every program/major, via a
# selector + the Override banner) and Program Head (their own scope only,
# via a segmented major-filter). The catalog itself stays shared (a subject
# code is unique school-wide) — where it sits in a program/major's
# prospectus is a CurriculumEntry, never a field on Subject itself.
# ---------------------------------------------------------------------------


class SubjectToggleActiveView(RoleRequiredMixin, ToggleActiveView):
    """Deactivates the catalog subject entirely (admin only) — distinct
    from "remove from curriculum," which only detaches one program/major's
    placement and leaves the subject (and its other placements) intact."""

    allowed_roles = (ADMIN,)
    model = Subject
    refresh_event = "refreshSubjects"


def _build_pills(user):
    """One pill per major in the user's scope ("English", "Social
    Studies" — display names, not codes); a program with no majors at
    all (e.g. TCP) gets one pill for the program itself instead. The
    program-level "every major with no head of its own" scope tuple
    never gets its own pill once the program actually has majors — that
    would be an always-empty view (no CurriculumEntry can have
    major=None under a program that has majors)."""
    scope = scoping.scope_for(user)
    pills = []
    for program_id in sorted({p for p, _ in scope}):
        program = Program.objects.get(pk=program_id)
        majors = list(Major.objects.filter(program=program, is_active=True).order_by("code"))
        if majors:
            for major in majors:
                if scoping.is_in_scope(user, program_id, major.id):
                    pills.append({"label": major.name.title(), "program": program, "major": major})
        else:
            pills.append({"label": program.code, "program": program, "major": None})
    return pills


def _resolve_program_major_from_request(request, user, pills=None):
    """Resolves the (program, major-or-None) pair a Subjects prospectus
    request is showing. Admin: any program/major from ?program=/?major=
    (or the first active program if neither given). Program Head: must
    match one of their own pills — 403 otherwise — defaulting to the
    first pill if neither param is given."""
    program_id = request.GET.get("program") or request.POST.get("program")
    major_id = request.GET.get("major") or request.POST.get("major")

    if user.is_admin_role:
        program = (
            get_object_or_404(Program, pk=program_id)
            if program_id
            else Program.objects.filter(is_active=True).order_by("code").first()
        )
        major = get_object_or_404(Major, pk=major_id) if major_id else None
        return program, major

    if program_id:
        program = get_object_or_404(Program, pk=program_id)
        major = get_object_or_404(Major, pk=major_id) if major_id else None
        if not scoping.is_in_scope(user, program.id, major.id if major else None):
            raise PermissionDenied("This program/major is not under your scope.")
        return program, major

    if pills is None:
        pills = _build_pills(user)
    if not pills:
        return None, None
    first = pills[0]
    return first["program"], first["major"]


def _subject_prospectus_context(program, major, query="", term_filter="ALL", year_level_filter="ALL"):
    """One card per year level (plus one no-year-level card for a TCP-
    style major/program) each with a 1st/2nd Sem[/Summer] sub-table of
    CurriculumEntry rows, a per-sub-table unit total, and a "Shared"
    badge listing any OTHER program/major that also places the same
    subject — all computed in a small, fixed number of queries rather
    than per-row. `term_filter`/`year_level_filter` narrow which rows
    render; `has_summer`/`available_year_levels` are computed from the
    UNFILTERED set so the filter controls themselves don't disappear
    once a narrowing choice is made."""
    base_qs = CurriculumEntry.objects.filter(program=program, major=major).select_related("subject")
    if query:
        base_qs = base_qs.filter(Q(subject__code__icontains=query) | Q(subject__title__icontains=query))
    all_entries = list(base_qs)

    has_summer = any(e.term == Term.SUMMER for e in all_entries)
    available_year_levels = sorted({e.year_level for e in all_entries if e.year_level is not None})

    entries = all_entries
    if term_filter and term_filter != "ALL":
        entries = [e for e in entries if e.term == term_filter]
    if year_level_filter and year_level_filter != "ALL":
        yl = int(year_level_filter)
        entries = [e for e in entries if e.year_level == yl]
    entries.sort(key=lambda e: (e.year_level or 0, e.term, e.subject.code))

    subject_count = len({e.subject_id for e in entries})
    total_units = sum((e.subject.units for e in entries), Decimal("0"))

    subject_ids = [e.subject_id for e in entries]
    other_placements = (
        CurriculumEntry.objects.filter(subject_id__in=subject_ids)
        .exclude(program=program, major=major)
        .select_related("program", "major")
    )
    shared_labels = {}
    for other in other_placements:
        label = f"{other.program.code}-{other.major.code}" if other.major else other.program.code
        shared_labels.setdefault(other.subject_id, set()).add(label)

    year_levels = sorted({e.year_level for e in entries if e.year_level is not None})
    has_no_year_level_rows = any(e.year_level is None for e in entries)

    def term_tables(year_level):
        group = [e for e in entries if e.year_level == year_level]
        tables = []
        for term_value, term_label in Term.choices:
            if term_filter and term_filter != "ALL" and term_value != term_filter:
                continue
            rows = [e for e in group if e.term == term_value]
            if not rows and term_value == Term.SUMMER:
                continue
            tables.append(
                {
                    "value": term_value,
                    "label": term_label,
                    "rows": rows,
                    "total_units": sum((r.subject.units for r in rows), Decimal("0")),
                }
            )
        return tables

    cards = [{"year_level": yl, "term_tables": term_tables(yl)} for yl in year_levels]
    if has_no_year_level_rows or not year_levels:
        cards.append({"year_level": None, "term_tables": term_tables(None)})

    summary = {
        "has_summer": has_summer,
        "available_year_levels": available_year_levels,
        "subject_count": subject_count,
        "total_units": total_units,
    }
    return cards, shared_labels, summary


def _resolve_semester_from_request(request):
    """Academic Year + Semester filter (Subjects/Classes pages) — defaults
    to the ACTIVE semester, kept in the URL via ?ay=<academic_year_id>&
    sem_term=<term>. Falls back to the active semester (or None) if the
    requested combination doesn't exist, rather than 404ing."""
    ay_id = request.GET.get("ay") or request.POST.get("ay")
    sem_term = request.GET.get("sem_term") or request.POST.get("sem_term")
    if ay_id and sem_term:
        semester = Semester.objects.filter(academic_year_id=ay_id, term=sem_term).select_related("academic_year").first()
        if semester:
            return semester
    return Semester.objects.filter(is_active=True).select_related("academic_year").first()


@role_required(ADMIN, PROGRAM_HEAD)
def subjects_home(request):
    is_admin = request.user.is_admin_role
    pills = None if is_admin else _build_pills(request.user)
    program, major = _resolve_program_major_from_request(request, request.user, pills=pills)

    context = {"page_title": "Subjects", "is_admin": is_admin, "program": program, "major": major}
    if program is None:
        context["no_scope"] = True
        return render(request, "academics/subjects.html", context)

    selected_semester = _resolve_semester_from_request(request)
    # The Semester dropdown is the only term control now -- it drives both
    # which semester's offerings show AND which curriculum term is listed
    # (no separate "All terms" pill row any more).
    term_filter = selected_semester.term if selected_semester else "ALL"
    year_level_filter = request.GET.get("year_level", "ALL")
    query = request.GET.get("q", "").strip()

    cards, shared_labels, summary = _subject_prospectus_context(
        program, major, query, term_filter=term_filter, year_level_filter=year_level_filter
    )

    offering_term = selected_semester.term if selected_semester else None
    semester_locked = services.is_semester_locked(selected_semester)
    offering_ok = services.offering_allowed(selected_semester)
    offered_by_subject_id = {}
    if selected_semester:
        offered_by_subject_id = {
            so.subject_id: so
            for so in SubjectOffering.objects.filter(semester=selected_semester, program=program, major=major)
        }
    units_by_entry_id = {}
    for card in cards:
        for table in card["term_tables"]:
            table["is_offering_term"] = bool(selected_semester) and table["value"] == offering_term
            offerable_ids = []
            for entry in table["rows"]:
                entry.offering = offered_by_subject_id.get(entry.subject_id)
                units_by_entry_id[str(entry.pk)] = float(entry.subject.units)
                if table["is_offering_term"] and entry.offering is None:
                    offerable_ids.append(entry.pk)
            table["offerable_ids"] = offerable_ids

    context.update(
        {
            "cards": cards,
            "shared_labels": shared_labels,
            "query": query,
            "term_filter": term_filter,
            "year_level_filter": year_level_filter,
            "term_choices": Term.choices,
            "academic_years": AcademicYear.objects.all(),
            "selected_semester": selected_semester,
            "selected_ay_id": selected_semester.academic_year_id if selected_semester else None,
            "selected_sem_term": selected_semester.term if selected_semester else "",
            "semester_term_choices": Term.choices,
            "semester_locked": semester_locked,
            "offering_ok": offering_ok,
            "units_by_entry_id": units_by_entry_id,
            **summary,
        }
    )

    if is_admin:
        context["programs"] = Program.objects.filter(is_active=True).order_by("code")
        context["majors"] = Major.objects.filter(program=program, is_active=True).order_by("code")
    else:
        context["editable_subject_ids"] = set(
            scoping.subjects_editable_by(request.user).values_list("id", flat=True)
        )
        for pill in pills:
            pill["active"] = program.id == pill["program"].id and (
                (major.id if major else None) == (pill["major"].id if pill["major"] else None)
            )
        context["pills"] = pills

    template = "academics/_subjects_prospectus.html" if is_htmx(request) else "academics/subjects.html"
    return render(request, template, context)


@role_required(ADMIN, PROGRAM_HEAD)
def subject_search(request):
    query = request.GET.get("q", "").strip()
    qs = Subject.objects.filter(is_active=True)
    if query:
        qs = qs.filter(Q(code__icontains=query) | Q(title__icontains=query))
    options = [(s.pk, str(s)) for s in qs.order_by("code")[:20]]
    return render(request, "partials/_searchable_select_options.html", {"options": options})


# ---------------------------------------------------------------------------
# Subject Offering — a Program Head (or Admin, for any program) checks a
# box next to curriculum subjects to "offer" them for a semester; offering
# auto-creates one class per active section of that program/major/
# year_level and fills its roster. Preview (session-stashed, same pattern
# as offerings_import/the AY wizard) -> one confirm screen (missing
# sections + a Combine/Separate choice per shared-subject conflict) ->
# commit, all rendered into the shared #modal-content.
# ---------------------------------------------------------------------------

_OFFERING_PREVIEW_SESSION_KEY = "subject_offering_preview"
_MANAGE_SECTIONS_SESSION_KEY = "subject_offering_manage"


def _build_matrix_groups(plan_rows):
    """Pivots flat (subject, section) plan_rows into the editable matrix:
    one group per (program, major, year_level) -- a group's sections are
    resolved purely from that scope (build_offering_rows), so every
    subject row in a group shares the exact same section columns -- each
    holding one row per subject with a `cells` list in that column order."""
    groups = {}
    order = []
    for row in plan_rows:
        key = (row["program"].id, row["major"].id if row["major"] else None, row["year_level"])
        if key not in groups:
            groups[key] = {
                "program": row["program"],
                "major": row["major"],
                "year_level": row["year_level"],
                "sections": [],
                "_section_ids_seen": set(),
                "_subject_rows": {},
            }
            order.append(key)
        group = groups[key]
        if row["section"].id not in group["_section_ids_seen"]:
            group["_section_ids_seen"].add(row["section"].id)
            group["sections"].append(row["section"])
        subj_key = row["subject"].id
        if subj_key not in group["_subject_rows"]:
            group["_subject_rows"][subj_key] = {
                "subject": row["subject"],
                "curriculum_entry": row.get("curriculum_entry"),
                "cells": [],
            }
        group["_subject_rows"][subj_key]["cells"].append(row)

    result = []
    for key in order:
        group = groups[key]
        group["subject_rows"] = list(group["_subject_rows"].values())
        del group["_subject_rows"]
        del group["_section_ids_seen"]
        result.append(group)
    return result


def _flatten_matrix_rows(groups):
    """Assigns each subject row a flat `row_index` shared by the template
    (checkbox/toggle field names `sections_<i>`/`combine_<i>`) and the
    session stash (so the commit view can map posted field names back to
    the right row without trusting any posted subject/program/section id
    outside what was actually previewed)."""
    flat = []
    for group in groups:
        for row in group["subject_rows"]:
            row["row_index"] = len(flat)
            flat.append(row)
    return flat


def _serialize_matrix_rows(flat_rows):
    serialized = []
    for row in flat_rows:
        first_cell = row["cells"][0]
        serialized.append(
            {
                "subject_id": row["subject"].pk,
                "curriculum_entry_id": row["curriculum_entry"].pk if row.get("curriculum_entry") else None,
                "program_id": first_cell["program"].pk,
                "major_id": first_cell["major"].pk if first_cell["major"] else None,
                "year_level": first_cell["year_level"],
                "cells": [
                    {
                        "section_id": cell["section"].pk,
                        "already_offered": cell["already_offered"],
                        "conflict_class_id": cell["conflict_class"].pk if cell["conflict_class"] else None,
                    }
                    for cell in row["cells"]
                ],
            }
        )
    return serialized


def _plan_rows_from_posted_matrix(stashed_rows, post_data):
    """Reads back `sections_<i>`/`combine_<i>` for every stashed row,
    skipping already_offered cells (nothing new to do there) and cells
    that were never ticked. Shared by subject_offering_commit and
    subject_offering_manage's "add newly-ticked sections" half."""
    plan_rows = []
    for i, row in enumerate(stashed_rows):
        ticked = {int(x) for x in post_data.getlist(f"sections_{i}") if x.isdigit()}
        combine = post_data.get(f"combine_{i}") == "on"
        subject = Subject.objects.get(pk=row["subject_id"])
        program = Program.objects.get(pk=row["program_id"])
        major = Major.objects.get(pk=row["major_id"]) if row["major_id"] else None
        for cell in row["cells"]:
            if cell["already_offered"] or cell["section_id"] not in ticked:
                continue
            plan_rows.append(
                {
                    "subject": subject,
                    "program": program,
                    "major": major,
                    "year_level": row["year_level"],
                    "section": Section.objects.get(pk=cell["section_id"]),
                    "conflict_class": (
                        ClassOffering.objects.filter(pk=cell["conflict_class_id"]).first()
                        if cell["conflict_class_id"]
                        else None
                    ),
                    "already_offered": False,
                    "combine": combine,
                }
            )
    return plan_rows


def _offering_confirm_response(request, preview, program, major, selected_semester, next_url):
    groups = _build_matrix_groups(preview["plan_rows"])
    flat_rows = _flatten_matrix_rows(groups)
    request.session[_OFFERING_PREVIEW_SESSION_KEY] = {
        "semester_id": selected_semester.pk,
        "rows": _serialize_matrix_rows(flat_rows),
        "next_url": next_url,
    }
    section_count = len({cell["section"].id for row in flat_rows for cell in row["cells"]})
    return render(
        request,
        "academics/_subject_offering_confirm.html",
        {
            "groups": groups,
            "missing_section_rows": preview["missing_section_rows"],
            "already_offered_rows": preview["already_offered_rows"],
            "program": program,
            "major": major,
            "semester": selected_semester,
            "section_count": section_count,
        },
    )


@role_required(ADMIN, PROGRAM_HEAD)
def subject_offering_preview(request):
    """"Offer selected" / "Offer all" — POST a list of CurriculumEntry ids,
    get back one confirm screen. Nothing is written yet."""
    from django.contrib import messages as django_messages

    program, major = _resolve_program_major_from_request(request, request.user)
    if program is None:
        raise PermissionDenied("You have no program/major in scope.")
    selected_semester = _resolve_semester_from_request(request)
    if selected_semester is None or not services.offering_allowed(selected_semester):
        raise PermissionDenied("Offering is not allowed for this semester.")

    next_url = request.POST.get("next") or reverse("academics:subjects")

    # Defense in depth — only entries actually offerable in this program/
    # major's scope for this term may be previewed, regardless of what a
    # tampered request's entry_ids contain.
    offerable_ids = {e.pk for e in services.offerable_subjects_for(program, major, selected_semester)}
    entry_ids = [int(i) for i in request.POST.getlist("entry_ids") if i.isdigit() and int(i) in offerable_ids]
    if not entry_ids:
        django_messages.error(request, "Select at least one offerable subject.")
        return redirect(next_url)

    preview = preview_subject_offerings(entry_ids, selected_semester)
    return _offering_confirm_response(request, preview, program, major, selected_semester, next_url)


@role_required(ADMIN, PROGRAM_HEAD)
def subject_offering_adhoc(request):
    """"Offer another subject…" — any active subject, even one outside
    this program/major's curriculum for this term, offered with an
    explicit warning."""
    program, major = _resolve_program_major_from_request(request, request.user)
    if program is None:
        raise PermissionDenied("You have no program/major in scope.")
    selected_semester = _resolve_semester_from_request(request)
    if selected_semester is None or not services.offering_allowed(selected_semester):
        raise PermissionDenied("Offering is not allowed for this semester.")

    if request.method != "POST":
        form = AdhocOfferingForm()
        return render(
            request,
            "academics/_subject_offering_adhoc_modal.html",
            {"form": form, "program": program, "major": major, "semester": selected_semester},
        )

    form = AdhocOfferingForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "academics/_subject_offering_adhoc_modal.html",
            {"form": form, "program": program, "major": major, "semester": selected_semester},
        )

    subject = form.cleaned_data["subject"]
    year_level = form.cleaned_data["year_level"]
    preview = preview_adhoc_offering(subject, program, major, year_level, selected_semester)
    next_url = reverse("academics:subjects") if request.user.is_admin_role else reverse("academics:ph_subjects")
    return _offering_confirm_response(request, preview, program, major, selected_semester, next_url)


@role_required(ADMIN, PROGRAM_HEAD)
def subject_offering_commit(request):
    stashed = request.session.get(_OFFERING_PREVIEW_SESSION_KEY)
    if not stashed:
        response = render(
            request,
            "academics/_subject_offering_confirm.html",
            {"groups": [], "missing_section_rows": [], "already_offered_rows": [], "error": "Your preview expired — try again."},
        )
        response["HX-Retarget"] = "#modal-content"
        response["HX-Reswap"] = "innerHTML"
        return response

    semester = get_object_or_404(Semester, pk=stashed["semester_id"])
    if not services.offering_allowed(semester):
        raise PermissionDenied("Offering is not allowed for this semester.")

    plan_rows = _plan_rows_from_posted_matrix(stashed["rows"], request.POST)
    del request.session[_OFFERING_PREVIEW_SESSION_KEY]

    if not plan_rows:
        return trigger_response("refreshSubjects", toast="Nothing offered. No sections were selected.")

    is_admin_override = request.user.is_admin_role
    result = commit_subject_offerings(plan_rows, semester, request.user, is_admin_override=is_admin_override)
    toast = (
        f"{result['offerings_created']} subject(s) offered · {result['classes_created']} class(es) created, "
        f"{result['students_added']} student(s) added."
    )
    return trigger_response("refreshSubjects", toast=toast)


@role_required(ADMIN, PROGRAM_HEAD)
def subject_offering_manage(request, pk):
    """"Manage sections" — re-opens the same matrix for one already-offered
    subject, pre-checked to match current coverage. Ticking a new section
    adds a class (or joins the row's combine group) the same way a fresh
    offer does; unticking an already-covered section withdraws just that
    section via withdraw_offering_section, skip-with-reason if blocked."""
    offering = get_object_or_404(SubjectOffering, pk=pk)
    if not request.user.is_admin_role and not scoping.is_in_scope(request.user, offering.program_id, offering.major_id):
        raise PermissionDenied("This offering is not under your program.")
    if services.is_semester_locked(offering.semester):
        raise PermissionDenied("This semester is closed.")

    preview = services.preview_manage_sections(offering)
    groups = _build_matrix_groups(preview["plan_rows"])
    flat_rows = _flatten_matrix_rows(groups)

    if request.method != "POST":
        request.session[_MANAGE_SECTIONS_SESSION_KEY] = {
            "offering_id": offering.pk,
            "rows": _serialize_matrix_rows(flat_rows),
        }
        return render(
            request,
            "academics/_subject_offering_manage.html",
            {"offering": offering, "groups": groups, "semester": offering.semester},
        )

    stashed = request.session.get(_MANAGE_SECTIONS_SESSION_KEY)
    if not stashed or stashed["offering_id"] != offering.pk:
        response = render(
            request,
            "academics/_subject_offering_manage.html",
            {"offering": offering, "groups": [], "semester": offering.semester, "error": "Your session expired — reopen Manage Sections."},
        )
        response["HX-Retarget"] = "#modal-content"
        response["HX-Reswap"] = "innerHTML"
        return response

    stashed_rows = stashed["rows"]
    added_rows = _plan_rows_from_posted_matrix(stashed_rows, request.POST)
    withdrawn_count = 0
    skip_reasons = []
    for i, row in enumerate(stashed_rows):
        ticked = {int(x) for x in request.POST.getlist(f"sections_{i}") if x.isdigit()}
        for cell in row["cells"]:
            if cell["already_offered"] and cell["section_id"] not in ticked:
                section = Section.objects.get(pk=cell["section_id"])
                ok, reason = services.withdraw_offering_section(offering, section, request.user)
                if ok:
                    withdrawn_count += 1
                else:
                    skip_reasons.append(reason)

    if added_rows:
        commit_subject_offerings(added_rows, offering.semester, request.user, is_admin_override=request.user.is_admin_role)
    del request.session[_MANAGE_SECTIONS_SESSION_KEY]

    parts = []
    if added_rows:
        parts.append(f"added {len(added_rows)} section(s)")
    if withdrawn_count:
        parts.append(f"withdrew {withdrawn_count} section(s)")
    if skip_reasons:
        parts.append(f"{len(skip_reasons)} skipped: {'; '.join(skip_reasons)}")
    toast = ("; ".join(parts) if parts else "No changes.").capitalize()
    return trigger_response("refreshSubjects", toast=toast)


@role_required(ADMIN, PROGRAM_HEAD)
def subject_offering_withdraw(request, pk):
    offering = get_object_or_404(SubjectOffering, pk=pk)
    if not request.user.is_admin_role and not scoping.is_in_scope(request.user, offering.program_id, offering.major_id):
        raise PermissionDenied("This offering is not under your program.")

    if request.method != "POST":
        return render(request, "academics/_subject_offering_withdraw_confirm.html", {"offering": offering})

    ok, reason = withdraw_offering(offering, request.user)
    if ok:
        return trigger_response("refreshSubjects", toast="Offering withdrawn.")
    return render(
        request, "academics/_subject_offering_withdraw_confirm.html", {"offering": offering, "error": reason}
    )


@role_required(ADMIN, PROGRAM_HEAD)
def subject_offering_bulk_withdraw(request):
    """One withdraw-many endpoint for all three bulk-withdraw entry points:
    an explicit `offering_ids` list (the selection-aware sticky bar), or a
    `scope` token resolved server-side — "year_level:<N>" for a card's
    ⋯ menu, "all" for the toolbar — matching the "never trust a scope the
    client computed, resolve it again here" pattern the rest of this
    module already follows (e.g. subject_offering_preview's offerable_ids
    re-check). GET/unconfirmed POST renders a preview; POST with
    confirmed=1 actually withdraws."""
    program, major = _resolve_program_major_from_request(request, request.user)
    if program is None:
        raise PermissionDenied("You have no program/major in scope.")
    selected_semester = _resolve_semester_from_request(request)
    if selected_semester is None:
        raise PermissionDenied("No semester selected.")

    data = request.POST if request.method == "POST" else request.GET
    offering_ids = [int(i) for i in data.getlist("offering_ids") if i.isdigit()]
    scope = data.get("scope", "")

    qs = SubjectOffering.objects.filter(semester=selected_semester, program=program, major=major).select_related("subject")
    if offering_ids:
        qs = qs.filter(pk__in=offering_ids)
    elif scope.startswith("year_level:"):
        qs = qs.filter(year_level=int(scope.split(":", 1)[1]))
    elif scope == "all":
        # The toolbar's "Withdraw all" respects whatever year_level filter
        # is currently active on the page; a card's own ⋯ menu action uses
        # the explicit "year_level:<N>" token above instead, independent
        # of the page filter.
        year_level_param = data.get("year_level")
        if year_level_param and year_level_param != "ALL":
            qs = qs.filter(year_level=int(year_level_param))
    else:
        raise PermissionDenied("Nothing to withdraw.")
    offerings = list(qs)

    if request.method != "POST" or request.POST.get("confirmed") != "1":
        return render(
            request,
            "academics/_subject_offering_bulk_withdraw_confirm.html",
            {"offerings": offerings, "offering_ids": [o.pk for o in offerings], "scope": scope},
        )

    class_counts = {o.pk: o.class_offerings.count() for o in offerings}
    withdrawn, skipped = services.withdraw_offerings_bulk(offerings, request.user)
    classes_withdrawn = sum(class_counts[offering_id] for offering_id in withdrawn)

    toast = f"Withdrew {len(withdrawn)} subject{'' if len(withdrawn) == 1 else 's'} ({classes_withdrawn} class{'' if classes_withdrawn == 1 else 'es'})."
    if skipped:
        toast += f" {len(skipped)} skipped: " + "; ".join(reason for _, reason in skipped)
    return trigger_response("refreshSubjects", toast=toast)


def _subject_add_search_results(query, program, major, limit=8):
    """Ordered/tagged dropdown rows for the Add Subject modal's typeahead:
    subjects already placed in THIS program/major first, then subjects
    shared across more than one program (GE/PEd/Theo/NSTP/PATHFit-style),
    then everything else. A row already placed in this exact program/
    major is tagged with where, and disabled (can't be re-added — it
    would violate CurriculumEntry's one-slot-per-program/major rule)."""
    qs = Subject.objects.filter(is_active=True)
    if query:
        qs = qs.filter(Q(code__icontains=query) | Q(title__icontains=query))
    candidates = list(qs.order_by("code")[:50])
    candidate_ids = [s.id for s in candidates]

    same_scope_ids = set(
        CurriculumEntry.objects.filter(program=program, major=major, subject_id__in=candidate_ids).values_list(
            "subject_id", flat=True
        )
    )
    program_sets = {}
    for subject_id, program_id in CurriculumEntry.objects.filter(subject_id__in=candidate_ids).values_list(
        "subject_id", "program_id"
    ):
        program_sets.setdefault(subject_id, set()).add(program_id)
    existing_entries = {
        e.subject_id: e
        for e in CurriculumEntry.objects.filter(program=program, major=major, subject_id__in=candidate_ids)
    }

    def sort_key(s):
        in_scope = 0 if s.id in same_scope_ids else 1
        shared = 0 if len(program_sets.get(s.id, set())) > 1 else 1
        return (in_scope, shared, s.code)

    candidates.sort(key=sort_key)
    results = []
    for s in candidates[:limit]:
        entry = existing_entries.get(s.id)
        results.append(
            {
                "subject": s,
                "disabled": entry is not None,
                "already_in": services.slot_label(entry.year_level, entry.term) if entry else None,
            }
        )
    return results


def _subject_add_context(program, major, year_level, term, form=None):
    form = form or SubjectAddForm()
    code_input = (form.data.get("code", "") if form.is_bound else "").strip()
    matched_subject = services.find_subject_by_normalized_code(code_input) if code_input else None
    mode = "existing" if matched_subject else ("new" if code_input else None)
    search_results = _subject_add_search_results(code_input, program, major) if mode == "new" else []
    return {
        "form": form,
        "program": program,
        "major": major,
        "year_level": year_level,
        "year_level_choices": YEAR_LEVEL_CHOICES,
        "term": term,
        "term_choices": Term.choices,
        "slot_label": services.slot_label(year_level, term),
        "scope_label": services.scope_label(program, major),
        "code_input": code_input,
        "matched_subject": matched_subject,
        "mode": mode,
        "search_results": search_results,
    }


@role_required(ADMIN, PROGRAM_HEAD)
def subject_add(request):
    program, major = _resolve_program_major_from_request(request, request.user)
    if program is None:
        raise PermissionDenied("You have no program/major in scope.")

    year_level_raw = request.GET.get("year_level") or request.POST.get("year_level") or ""
    year_level = int(year_level_raw) if year_level_raw else None
    term = request.GET.get("term") or request.POST.get("term") or Term.FIRST

    if request.method != "POST":
        form = SubjectAddForm(request.GET) if "code" in request.GET else None
        return render(
            request, "academics/_subject_add_modal.html", _subject_add_context(program, major, year_level, term, form)
        )

    form = SubjectAddForm(request.POST)
    if not form.is_valid():
        return render(
            request, "academics/_subject_add_modal.html", _subject_add_context(program, major, year_level, term, form)
        )

    matched = form.cleaned_data["matched_subject"]
    is_admin_override = request.user.is_admin_role

    if matched is not None:
        duplicate_error = services.subject_duplicate_error(matched, program, major, year_level, term)
        if duplicate_error:
            form.add_error(None, duplicate_error)
            return render(
                request,
                "academics/_subject_add_modal.html",
                _subject_add_context(program, major, year_level, term, form),
            )
        subject = matched
        verb = "added to the curriculum"
    else:
        subject = Subject.objects.create(
            code=form.cleaned_data["code"].strip(), title=form.cleaned_data["title"], units=form.cleaned_data["units"]
        )
        verb = "created and added"

    CurriculumEntry.objects.create(program=program, major=major, year_level=year_level, term=term, subject=subject)
    _log_academic_setup_change(
        AcademicSetupChangeLog.ModelName.SUBJECT,
        subject,
        AcademicSetupChangeLog.Action.ADDED_TO_CURRICULUM,
        request.user,
        is_admin_override=is_admin_override,
        program=program,
        major=major,
    )
    return trigger_response("refreshSubjects", toast=f"{subject.code} {verb}.")


def _find_code_conflict(code, exclude_pk):
    """Any OTHER subject whose code normalizes to the same value — None
    if there's no conflict."""
    target = services.normalize_code(code)
    for other in Subject.objects.exclude(pk=exclude_pk):
        if services.normalize_code(other.code) == target:
            return other
    return None


@role_required(ADMIN, PROGRAM_HEAD)
def subject_edit(request, pk):
    subject = get_object_or_404(Subject, pk=pk)
    original_code = subject.code  # ModelForm.is_valid() mutates form.instance (== subject) in place
    is_admin = request.user.is_admin_role
    if not is_admin and not scoping.subjects_editable_by(request.user).filter(pk=subject.pk).exists():
        raise PermissionDenied("This subject is shared. Ask the Admin to edit it.")

    form_class = AdminSubjectForm if is_admin else SubjectEditForm
    code_locked = services.subject_used_in_released_grades(subject)

    def _context(form):
        return {"form": form, "subject": subject, "is_admin": is_admin, "code_locked": code_locked}

    if request.method != "POST":
        form = form_class(instance=subject)
        if code_locked:
            form.fields["code"].disabled = True
        return render(request, "academics/_subject_edit_modal.html", _context(form))

    form = form_class(request.POST, instance=subject)
    if code_locked:
        form.fields["code"].disabled = True
    if not form.is_valid():
        return render(request, "academics/_subject_edit_modal.html", _context(form))

    code_changed = services.normalize_code(original_code) != services.normalize_code(form.cleaned_data["code"])
    if code_changed:
        conflict = _find_code_conflict(form.cleaned_data["code"], subject.pk)
        if conflict is not None:
            form.add_error("code", f"A subject with code {conflict.code} already exists.")
            return render(request, "academics/_subject_edit_modal.html", _context(form))

    subject = form.save()
    _log_academic_setup_change(
        AcademicSetupChangeLog.ModelName.SUBJECT,
        subject,
        AcademicSetupChangeLog.Action.UPDATED,
        request.user,
        is_admin_override=is_admin,
    )
    return trigger_response("refreshSubjects", toast="Subject updated.")


@role_required(ADMIN)
def subject_correct_code(request, pk):
    """Admin-only escape hatch past subject_edit's released-grades code
    lock — requires a reason, always logged as an admin override."""
    subject = get_object_or_404(Subject, pk=pk)

    if request.method != "POST":
        form = SubjectCodeCorrectionForm(initial={"code": subject.code})
        return render(request, "academics/_subject_correct_code_modal.html", {"form": form, "subject": subject})

    form = SubjectCodeCorrectionForm(request.POST)
    if not form.is_valid():
        return render(request, "academics/_subject_correct_code_modal.html", {"form": form, "subject": subject})

    new_code = form.cleaned_data["code"].strip()
    conflict = _find_code_conflict(new_code, subject.pk)
    if conflict is not None:
        form.add_error("code", f"A subject with code {conflict.code} already exists.")
        return render(request, "academics/_subject_correct_code_modal.html", {"form": form, "subject": subject})

    old_code = subject.code
    subject.code = new_code
    subject.save(update_fields=["code"])
    _log_academic_setup_change(
        AcademicSetupChangeLog.ModelName.SUBJECT,
        subject,
        AcademicSetupChangeLog.Action.CODE_CORRECTED,
        request.user,
        is_admin_override=True,
        old_code=old_code,
        new_code=new_code,
        reason=form.cleaned_data["reason"],
    )
    return trigger_response("refreshSubjects", toast=f"Code corrected: {old_code} → {new_code}.")


@role_required(ADMIN, PROGRAM_HEAD)
def subject_remove_from_curriculum(request, pk):
    entry = get_object_or_404(CurriculumEntry.objects.select_related("subject", "program", "major"), pk=pk)
    is_admin = request.user.is_admin_role
    if not is_admin and not scoping.is_in_scope(request.user, entry.program_id, entry.major_id):
        raise PermissionDenied("This curriculum entry is not under your scope.")

    active_semester = Semester.objects.filter(is_active=True).first()
    blocked = False
    if active_semester:
        class_filter = Q(subject=entry.subject, semester=active_semester, sections__program=entry.program)
        if entry.major_id:
            class_filter &= Q(sections__major=entry.major)
        else:
            class_filter &= Q(sections__major__isnull=True)
        blocked = ClassOffering.objects.filter(class_filter).exists()

    if request.method != "POST" or blocked:
        return render(request, "academics/_subject_remove_confirm.html", {"entry": entry, "blocked": blocked})

    _log_academic_setup_change(
        AcademicSetupChangeLog.ModelName.SUBJECT,
        entry.subject,
        AcademicSetupChangeLog.Action.REMOVED_FROM_CURRICULUM,
        request.user,
        is_admin_override=is_admin,
        program=entry.program,
        major=entry.major,
    )
    entry.delete()
    return trigger_response("refreshSubjects", toast=f"{entry.subject.code} removed from the curriculum.")


# ---------------------------------------------------------------------------
# Classes (ClassOffering) — admin CRUD. One class can serve several
# sections at once (e.g. a shared General Education subject), so filtering
# "by program/major/year" goes through the sections M2M.
# ---------------------------------------------------------------------------


class ClassListView(RoleRequiredMixin, EntityListView):
    allowed_roles = (ADMIN,)
    model = ClassOffering
    list_template = "academics/classes.html"
    table_template = "academics/_classes_table.html"
    table_id = "classes-table"
    page_title = "Classes"
    search_fields = ["subject__code__icontains", "subject__title__icontains"]
    refresh_event = "refreshClasses"

    def apply_filters(self, request, qs):
        qs = qs.prefetch_related("sections__program", "sections__major").select_related(
            "subject", "semester", "instructor"
        ).annotate(
            roster_size=Count(
                "roster_entries", filter=Q(roster_entries__status=ClassRosterEntry.Status.ACTIVE), distinct=True
            )
        )
        semester_param = request.GET.get("semester")
        if semester_param == "all":
            pass
        elif semester_param:
            qs = qs.filter(semester_id=semester_param)
        else:
            active = Semester.objects.filter(is_active=True).first()
            if active:
                qs = qs.filter(semester_id=active.id)

        program = request.GET.get("program")
        if program:
            qs = qs.filter(sections__program_id=program)

        instructor = request.GET.get("instructor")
        if instructor:
            qs = qs.filter(instructor_id=instructor)

        return qs.distinct()

    def get_extra_context(self, request):
        return {
            "programs": Program.objects.all(),
            "semesters": Semester.objects.select_related("academic_year").all(),
            "instructors": User.objects.filter(role=INSTRUCTOR).order_by("last_name", "first_name"),
        }


class ClassFormView(RoleRequiredMixin, EntityFormView):
    """Admin's existing Classes CRUD form — the instructor field on it is
    an "admin override" of what's normally the Program Head's call (see
    academics:program_head_classes / academics:teaching_loads). A change
    to that one field goes through the same check/log/notify path as the
    dedicated assign-instructor flow, instead of just `form.save()`, so
    both paths behave identically (blocked once the sheet is submitted,
    logged, notified)."""

    allowed_roles = (ADMIN,)
    model = ClassOffering
    form_class = ClassOfferingForm
    refresh_event = "refreshClasses"
    modal_title_create = "Add Class"
    modal_title_edit = "Edit Class"

    def _url(self, pk):
        return reverse("academics:class_edit", args=[pk]) if pk else reverse("academics:class_create")

    def get(self, request, pk=None):
        obj = self.get_object(pk)
        selected_sections = _selected_sections_from_request(request, Section.objects.all())
        form = self.form_class(instance=obj, selected_sections=selected_sections)
        if selected_sections is not None:
            form.initial["sections"] = [s.pk for s in selected_sections]
        _wire_live_subject_regroup(form, self._url(pk))
        return render(request, self.form_template, self.get_context(request, form, obj))

    def post(self, request, pk=None):
        obj = self.get_object(pk)
        is_create = obj is None
        if obj is not None:
            _require_semester_unlocked(obj)
        old_instructor = obj.instructor if obj else None
        form = self.form_class(request.POST, instance=obj)
        if not form.is_valid():
            _wire_live_subject_regroup(form, self._url(pk))
            return render(request, self.form_template, self.get_context(request, form, obj))

        if is_create and services.is_semester_locked(form.cleaned_data.get("semester")):
            form.add_error(None, "This semester is closed and read-only.")
            _wire_live_subject_regroup(form, self._url(pk))
            return render(request, self.form_template, self.get_context(request, form, obj))

        new_instructor = form.cleaned_data.get("instructor")
        instructor_changed = obj is not None and (
            (old_instructor.id if old_instructor else None) != (new_instructor.id if new_instructor else None)
        )
        if instructor_changed:
            try:
                from .services import check_instructor_change_allowed

                check_instructor_change_allowed(obj)
            except ValidationError as exc:
                form.add_error(None, exc.messages[0])
                return render(request, self.form_template, self.get_context(request, form, obj))

        saved = form.save()

        if instructor_changed:
            log_and_notify_instructor_change(obj, old_instructor, new_instructor, request.user, is_admin_override=True)

        _log_academic_setup_change(
            AcademicSetupChangeLog.ModelName.CLASS,
            saved,
            AcademicSetupChangeLog.Action.CREATED if is_create else AcademicSetupChangeLog.Action.UPDATED,
            request.user,
            is_admin_override=True,
        )

        verb = "updated" if obj else "created"
        return trigger_response(self.refresh_event, toast=f"Class {verb}.")


class ClassDeleteView(RoleRequiredMixin, EntityDeleteView):
    allowed_roles = (ADMIN,)
    model = ClassOffering
    refresh_event = "refreshClasses"
    deactivate_url_name = "academics:class_toggle_active"
    protect_message = "This class has a roster using it."


class ClassToggleActiveView(RoleRequiredMixin, ToggleActiveView):
    allowed_roles = (ADMIN,)
    model = ClassOffering
    refresh_event = "refreshClasses"


# ---------------------------------------------------------------------------
# Class roster (read-only for everyone except the "Import class list"
# action) — shared by admin, the owning program head, and the assigned
# instructor. Object-level check: wrong program head/instructor gets 403.
# ---------------------------------------------------------------------------


def _can_manage_roster(user, class_offering):
    """ADMIN can manage any class's roster; an INSTRUCTOR only their own;
    a PROGRAM_HEAD only a class with at least one of their own in-scope
    sections (shared classes are manageable by every head sharing them)."""
    if user.is_admin_role:
        return True
    if user.is_instructor:
        return class_offering.instructor_id == user.id
    if user.is_program_head:
        return class_offering.sections.filter(pk__in=scoping.sections_in_scope(user)).exists()
    return False


def _get_class_offering_for_viewer(request, pk):
    class_offering = get_object_or_404(
        ClassOffering.objects.select_related("subject", "semester", "instructor").prefetch_related(
            "sections__program"
        ),
        pk=pk,
    )
    user = request.user
    if user.is_program_head and not class_offering.sections.filter(pk__in=scoping.sections_in_scope(user)).exists():
        raise PermissionDenied("This class is not under your program.")
    if user.is_instructor and class_offering.instructor_id != user.id:
        raise PermissionDenied("This class is not assigned to you.")
    return class_offering


@role_required(ADMIN, PROGRAM_HEAD, INSTRUCTOR)
def class_roster(request, pk):
    class_offering = _get_class_offering_for_viewer(request, pk)
    roster_entries = class_offering.roster_entries.select_related("student", "student__student_profile")
    assignment_logs = class_offering.assignment_logs.select_related("old_instructor", "new_instructor", "changed_by")[:10]
    is_owner = request.user.is_instructor and class_offering.instructor_id == request.user.id

    roster_entries = list(roster_entries)
    memberships_by_student_id = {
        m.student_id: m.section
        for m in SectionMembership.objects.filter(
            semester=class_offering.semester, student_id__in=[e.student_id for e in roster_entries]
        ).select_related("section")
    }
    for entry in roster_entries:
        entry.membership_section = memberships_by_student_id.get(entry.student_id)

    pending_requests = []
    if is_owner:
        pending_requests = list(
            class_offering.join_requests.filter(status=ClassJoinRequest.Status.PENDING)
            .select_related("student", "student__student_profile")
            .order_by("requested_at")
        )
        pending_memberships = {
            m.student_id: m.section
            for m in SectionMembership.objects.filter(
                semester=class_offering.semester, student_id__in=[r.student_id for r in pending_requests]
            ).select_related("section")
        }
        for join_request in pending_requests:
            join_request.section_match = services.join_request_section_match(join_request)
            join_request.membership_section = pending_memberships.get(join_request.student_id)
    return render(
        request,
        "academics/class_roster.html",
        {
            "page_title": f"Class List — {class_offering}",
            "class_offering": class_offering,
            "roster_entries": roster_entries,
            "can_manage": _can_manage_roster(request.user, class_offering),
            "is_owner": is_owner,
            "pending_requests": pending_requests,
            "join_code": services.ensure_join_code(class_offering) if is_owner else None,
            "assignment_logs": assignment_logs,
        },
    )


# ---------------------------------------------------------------------------
# Class join codes — instructor side (invite card + pending requests on the
# Class List page above); the student side (join modal, confirmation, /
# join/<code>/) lives in its own section further down.
# ---------------------------------------------------------------------------


def _require_owner_instructor(request, pk):
    class_offering = get_object_or_404(ClassOffering, pk=pk)
    if not (request.user.is_instructor and class_offering.instructor_id == request.user.id):
        raise PermissionDenied("This class is not assigned to you.")
    return class_offering


@role_required(INSTRUCTOR)
def class_join_reset_code(request, pk):
    class_offering = _require_owner_instructor(request, pk)
    if request.method != "POST":
        return render(request, "academics/_join_reset_confirm.html", {"class_offering": class_offering})
    services.reset_join_code(class_offering, request.user)
    return trigger_response("refreshRoster", toast="Join code reset. The old code no longer works.")


@role_required(INSTRUCTOR)
def class_join_toggle(request, pk):
    class_offering = _require_owner_instructor(request, pk)
    if request.method != "POST":
        raise PermissionDenied
    services.set_join_enabled(class_offering, not class_offering.join_enabled, request.user)
    return trigger_response("refreshRoster")


@role_required(INSTRUCTOR)
def class_join_qr(request, pk):
    """Server-side SVG QR code for this class's join URL — no external
    service, no PIL (qrcode's SvgPathImage factory renders pure vector
    paths)."""
    import qrcode
    import qrcode.image.svg

    class_offering = _require_owner_instructor(request, pk)
    code = services.ensure_join_code(class_offering)
    join_url = request.build_absolute_uri(reverse("academics:join_with_code", args=[code]))
    img = qrcode.make(join_url, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    buffer = io.BytesIO()
    img.save(buffer)
    return HttpResponse(buffer.getvalue(), content_type="image/svg+xml")


@role_required(INSTRUCTOR)
def class_join_request_decide(request, pk):
    """Approve/Reject one pending request — POST action=approve|reject
    (+ optional reason for reject)."""
    join_request = get_object_or_404(ClassJoinRequest, pk=pk)
    class_offering = join_request.class_offering
    if not (request.user.is_instructor and class_offering.instructor_id == request.user.id):
        raise PermissionDenied("This class is not assigned to you.")
    if request.method != "POST":
        raise PermissionDenied

    action = request.POST.get("action")
    try:
        if action == "approve":
            services.approve_join_request(join_request, request.user)
            toast = f"{join_request.student.full_name} approved."
        elif action == "reject":
            reason = request.POST.get("reason") or request.headers.get("HX-Prompt", "")
            services.reject_join_request(join_request, request.user, reason)
            toast = f"{join_request.student.full_name}'s request declined."
        else:
            raise PermissionDenied("Unknown action.")
    except ValidationError as exc:
        from django.contrib import messages as django_messages

        django_messages.error(request, exc.messages[0])
        return trigger_response("refreshRoster")

    return trigger_response("refreshRoster", toast=toast)


@role_required(INSTRUCTOR)
def class_join_requests_bulk_decide(request, pk):
    class_offering = _require_owner_instructor(request, pk)
    if request.method != "POST":
        raise PermissionDenied

    action = request.POST.get("action")
    request_ids = [int(i) for i in request.POST.getlist("request_ids") if i.isdigit()]
    join_requests = ClassJoinRequest.objects.filter(
        pk__in=request_ids, class_offering=class_offering, status=ClassJoinRequest.Status.PENDING
    )
    decided, skipped = services.bulk_decide_join_requests(
        join_requests, request.user, approve=(action == "approve"), reason=request.POST.get("reason", "")
    )
    toast = f"{decided} request{'s' if decided != 1 else ''} {'approved' if action == 'approve' else 'declined'}."
    if skipped:
        toast += f" {len(skipped)} skipped."
    return trigger_response("refreshRoster", toast=toast)


# ---------------------------------------------------------------------------
# My Classes (instructor) / Classes (program head) — read-only
# ---------------------------------------------------------------------------


@role_required(INSTRUCTOR)
def my_classes(request):
    active = Semester.objects.filter(is_active=True).first()
    qs = ClassOffering.objects.none()
    if active:
        qs = (
            ClassOffering.objects.filter(instructor=request.user, semester=active)
            .select_related("subject")
            .prefetch_related("sections")
            .annotate(
                roster_size=Count(
                    "roster_entries", filter=Q(roster_entries__status=ClassRosterEntry.Status.ACTIVE), distinct=True
                ),
                pending_join_count=Count(
                    "join_requests", filter=Q(join_requests__status=ClassJoinRequest.Status.PENDING), distinct=True
                ),
            )
        )
    return render(
        request,
        "academics/my_classes.html",
        {"page_title": "My Classes", "classes": qs, "active_semester_set": bool(active)},
    )


def _program_head_class_queryset(user, active):
    """Classes under a program this user heads, for the active semester —
    shared by the teaching-load Classes page and its unassigned count."""
    if active is None:
        return ClassOffering.objects.none()
    return (
        scoping.classes_in_scope(user, semester=active)
        .select_related("subject", "instructor")
        .prefetch_related("sections")
        .annotate(
            roster_size=Count(
                "roster_entries", filter=Q(roster_entries__status=ClassRosterEntry.Status.ACTIVE), distinct=True
            ),
            pending_join_count=Count(
                "join_requests", filter=Q(join_requests__status=ClassJoinRequest.Status.PENDING), distinct=True
            ),
        )
        .distinct()
    )


@role_required(PROGRAM_HEAD)
def program_head_classes(request):
    """Teaching-load manager for a Program Head's own program(s): inline-
    editable instructor/room/schedule per class (class_update_field), an
    "Unassigned only" filter, and a sticky-bar bulk action (assign
    instructor / set room / set schedule) over the checked rows."""
    active = Semester.objects.filter(is_active=True).first()
    qs = _program_head_class_queryset(request.user, active)

    if request.GET.get("unassigned") == "1":
        qs = qs.filter(instructor__isnull=True)

    classes = list(qs)
    for c in classes:
        c.row_actions = _class_row_actions(c)
    return render(
        request,
        "academics/program_head_classes.html",
        {
            "page_title": "Classes",
            "classes": classes,
            "class_ids_json": [c.pk for c in classes],
            "active_semester_set": bool(active),
            "instructors": User.objects.filter(role=INSTRUCTOR, is_active=True).order_by("last_name", "first_name"),
        },
    )


@role_required(PROGRAM_HEAD)
def ph_class_create(request):
    active = Semester.objects.filter(is_active=True).first()
    if active is None:
        raise PermissionDenied("No active semester is set.")
    url = reverse("academics:ph_class_create")

    if request.method != "POST":
        selected_sections = _selected_sections_from_request(request, scoping.sections_in_scope(request.user))
        form = ProgramHeadClassOfferingForm(
            user=request.user,
            academic_year=active.academic_year,
            selected_sections=selected_sections,
            term=active.term,
        )
        if selected_sections is not None:
            form.initial["sections"] = [s.pk for s in selected_sections]
        _wire_live_subject_regroup(form, url)
        return render(request, "partials/_entity_form_modal.html", {"form": form, "modal_title": "Add Class"})

    form = ProgramHeadClassOfferingForm(
        request.POST, user=request.user, academic_year=active.academic_year, term=active.term
    )
    if form.is_valid():
        class_offering = form.save(commit=False)
        class_offering.semester = active
        class_offering.save()
        form.save_m2m()
        _log_academic_setup_change(
            AcademicSetupChangeLog.ModelName.CLASS,
            class_offering,
            AcademicSetupChangeLog.Action.CREATED,
            request.user,
            is_admin_override=False,
        )
        return trigger_response("refreshClasses", toast="Class created.")
    _wire_live_subject_regroup(form, url)
    return render(request, "partials/_entity_form_modal.html", {"form": form, "modal_title": "Add Class"})


@role_required(PROGRAM_HEAD)
def ph_class_edit(request, pk):
    class_offering = get_object_or_404(ClassOffering, pk=pk)
    if not class_offering.sections.filter(pk__in=scoping.sections_in_scope(request.user)).exists():
        raise PermissionDenied("This class is not under your program.")
    _require_semester_unlocked(class_offering)
    active = Semester.objects.filter(is_active=True).first()
    url = reverse("academics:ph_class_edit", args=[pk])

    if request.method != "POST":
        selected_sections = _selected_sections_from_request(request, scoping.sections_in_scope(request.user))
        form = ProgramHeadClassOfferingForm(
            instance=class_offering,
            user=request.user,
            academic_year=class_offering.semester.academic_year,
            selected_sections=selected_sections,
            term=class_offering.semester.term,
        )
        if selected_sections is not None:
            form.initial["sections"] = [s.pk for s in selected_sections]
        _wire_live_subject_regroup(form, url)
        return render(request, "partials/_entity_form_modal.html", {"form": form, "modal_title": "Edit Class"})

    old_instructor = class_offering.instructor
    form = ProgramHeadClassOfferingForm(
        request.POST,
        instance=class_offering,
        user=request.user,
        academic_year=class_offering.semester.academic_year,
        term=class_offering.semester.term,
    )
    if not form.is_valid():
        _wire_live_subject_regroup(form, url)
        return render(request, "partials/_entity_form_modal.html", {"form": form, "modal_title": "Edit Class"})

    new_instructor = form.cleaned_data.get("instructor")
    instructor_changed = (old_instructor.id if old_instructor else None) != (new_instructor.id if new_instructor else None)
    if instructor_changed:
        try:
            check_instructor_change_allowed(class_offering)
        except ValidationError as exc:
            form.add_error(None, exc.messages[0])
            return render(request, "partials/_entity_form_modal.html", {"form": form, "modal_title": "Edit Class"})

    class_offering = form.save()
    _log_academic_setup_change(
        AcademicSetupChangeLog.ModelName.CLASS,
        class_offering,
        AcademicSetupChangeLog.Action.UPDATED,
        request.user,
        is_admin_override=False,
    )
    if instructor_changed:
        log_and_notify_instructor_change(class_offering, old_instructor, new_instructor, request.user, is_admin_override=False)
    return trigger_response("refreshClasses", toast="Class updated.")


@role_required(PROGRAM_HEAD)
def ph_class_join(request):
    active = Semester.objects.filter(is_active=True).first()
    if active is None:
        raise PermissionDenied("No active semester is set.")

    own_sections = scoping.sections_in_scope(request.user).filter(academic_year=active.academic_year)
    candidate_classes = ClassOffering.objects.filter(semester=active).exclude(sections__in=own_sections).distinct()

    if request.method != "POST":
        form = JoinClassForm(class_queryset=candidate_classes, sections_queryset=own_sections)
        return render(request, "partials/_entity_form_modal.html", {"form": form, "modal_title": "Join Existing Class"})

    form = JoinClassForm(request.POST, class_queryset=candidate_classes, sections_queryset=own_sections)
    if form.is_valid():
        class_offering = form.cleaned_data["class_offering"]
        sections = list(form.cleaned_data["sections"])
        class_offering.sections.add(*sections)
        _log_academic_setup_change(
            AcademicSetupChangeLog.ModelName.CLASS,
            class_offering,
            AcademicSetupChangeLog.Action.SECTION_JOINED,
            request.user,
            is_admin_override=False,
            section_ids=[s.pk for s in sections],
        )
        return trigger_response("refreshClasses", toast=f"Joined {class_offering}.")
    return render(request, "partials/_entity_form_modal.html", {"form": form, "modal_title": "Join Existing Class"})


@role_required(PROGRAM_HEAD)
def ph_class_leave(request, pk):
    class_offering = get_object_or_404(ClassOffering, pk=pk)
    own_sections_in_class = class_offering.sections.filter(pk__in=scoping.sections_in_scope(request.user))
    if not own_sections_in_class.exists():
        raise PermissionDenied("You have no sections in this class.")
    _require_semester_unlocked(class_offering)
    blocked = services.class_has_scores_or_submitted_sheet(class_offering)

    if request.method != "POST":
        return render(
            request,
            "academics/_ph_class_leave_confirm.html",
            {"class_offering": class_offering, "sections": own_sections_in_class, "blocked": blocked},
        )

    if blocked:
        return render(
            request,
            "academics/_ph_class_leave_confirm.html",
            {"class_offering": class_offering, "sections": own_sections_in_class, "blocked": True},
        )

    section_ids = list(own_sections_in_class.values_list("pk", flat=True))
    offering = class_offering.offering
    class_offering.sections.remove(*own_sections_in_class)
    _log_academic_setup_change(
        AcademicSetupChangeLog.ModelName.CLASS,
        class_offering,
        AcademicSetupChangeLog.Action.SECTION_LEFT,
        request.user,
        is_admin_override=False,
        section_ids=section_ids,
    )
    if class_offering.sections.count() == 0:
        class_offering.is_active = False
        class_offering.save(update_fields=["is_active"])
        _log_academic_setup_change(
            AcademicSetupChangeLog.ModelName.CLASS,
            class_offering,
            AcademicSetupChangeLog.Action.DEACTIVATED,
            request.user,
            is_admin_override=False,
            reason="last section removed",
        )
        services.sync_offering_after_section_change(offering)
    return trigger_response("refreshClasses", toast=f"Left {class_offering}.")


# ---------------------------------------------------------------------------
# Teaching assignment — Program Head assigns/changes an instructor per
# class; Admin can too, as a logged "admin override" (see ClassFormView
# above for the admin Classes CRUD form's own path to the same logging).
# ---------------------------------------------------------------------------


def _can_assign_instructor(user, class_offering):
    if user.is_admin_role:
        return True
    return user.is_program_head and class_offering.sections.filter(pk__in=scoping.sections_in_scope(user)).exists()


@role_required(ADMIN, PROGRAM_HEAD)
def class_assign_instructor(request, pk):
    class_offering = get_object_or_404(
        ClassOffering.objects.select_related("instructor", "subject").prefetch_related("sections__program"), pk=pk
    )
    if not _can_assign_instructor(request.user, class_offering):
        raise PermissionDenied("This class is not under your program.")
    is_admin_override = request.user.is_admin_role

    if request.method != "POST":
        form = TeachingAssignmentForm(initial={"instructor": class_offering.instructor_id})
        return render(
            request,
            "academics/_assign_instructor_modal.html",
            {"class_offering": class_offering, "form": form, "is_admin_override": is_admin_override},
        )

    form = TeachingAssignmentForm(request.POST)
    if form.is_valid():
        try:
            assign_instructor(
                class_offering,
                form.cleaned_data["instructor"],
                request.user,
                is_admin_override=is_admin_override,
                reason=form.cleaned_data.get("reason", ""),
            )
        except ValidationError as exc:
            form.add_error(None, exc.messages[0])

    if form.errors:
        return render(
            request,
            "academics/_assign_instructor_modal.html",
            {"class_offering": class_offering, "form": form, "is_admin_override": is_admin_override},
        )

    return trigger_response("refreshClasses", toast=f"Instructor updated for {class_offering}.")


_CLASS_INLINE_FIELDS = ("instructor", "room", "schedule")


def _class_label(class_offering):
    sections = ", ".join(s.short_label for s in class_offering.sections.all())
    return f"{class_offering.display_code} · {sections}" if sections else class_offering.display_code


def _class_row_actions(class_offering):
    """The Program Head Classes row's "..." menu -- a plain actions list for
    the shared partials/_overflow_menu.html, same shape every other
    "..." menu in the system uses."""
    return [
        {"label": "Students", "href": reverse("academics:class_roster", args=[class_offering.pk])},
        {"label": "Edit", "hx_get": reverse("academics:ph_class_edit", args=[class_offering.pk])},
        {
            "label": "Withdraw this section",
            "hx_get": reverse("academics:ph_class_leave", args=[class_offering.pk]),
            "extra_classes": "text-red-700 hover:bg-red-50",
        },
    ]


@role_required(ADMIN, PROGRAM_HEAD)
def class_update_field(request, pk):
    """The Classes page's per-row inline-edit endpoint (room, schedule,
    instructor) — change/blur POSTs field+value, re-renders just that
    <tr> plus an out-of-band refresh of the "N classes need an
    instructor" banner, and fires a toast (success or, on a refusal,
    error — the row's own fields simply revert to their saved values,
    nothing is swapped into an inconsistent state). hx-include="this" on
    every inline control keeps this request scoped to that one element —
    without it, htmx serializes the whole enclosing page as if it were
    one giant form, and every row's same-named field collides. An
    instructor change still goes through assign_instructor so audit
    logging, notifications, and the submitted-sheet block are identical
    to the modal-based class_assign_instructor path above."""
    class_offering = get_object_or_404(
        ClassOffering.objects.select_related("instructor", "subject", "semester").prefetch_related("sections__program"),
        pk=pk,
    )
    if not _can_assign_instructor(request.user, class_offering):
        raise PermissionDenied("This class is not under your program.")
    if request.method != "POST":
        raise PermissionDenied

    field = request.POST.get("field")
    value = request.POST.get("value", "").strip()
    error = None
    toast = None

    if field not in _CLASS_INLINE_FIELDS:
        raise PermissionDenied("Unknown field.")

    if field == "instructor":
        instructor = User.objects.filter(pk=value, role=INSTRUCTOR, is_active=True).first() if value else None
        try:
            assign_instructor(
                class_offering, instructor, request.user, is_admin_override=request.user.is_admin_role
            )
            toast = f"{instructor.full_name} assigned to {_class_label(class_offering)}." if instructor else f"{_class_label(class_offering)} unassigned."
        except ValidationError as exc:
            error = exc.messages[0]
    else:
        try:
            _require_semester_unlocked(class_offering)
            setattr(class_offering, field, value)
            class_offering.save(update_fields=[field])
            toast = f"{field.capitalize()} updated for {_class_label(class_offering)}."
        except PermissionDenied as exc:
            error = str(exc)

    class_offering.refresh_from_db()
    class_offering.row_actions = _class_row_actions(class_offering)
    row_html = render_to_string(
        "academics/_classes_row.html",
        {
            "class_offering": class_offering,
            "error": error,
            "instructors": User.objects.filter(role=INSTRUCTOR, is_active=True).order_by("last_name", "first_name"),
        },
        request=request,
    )

    response = HttpResponse(row_html)
    silent = request.POST.get("silent") == "1"
    if error or not silent:
        response["HX-Trigger"] = json.dumps({"toast": {"message": error or toast, "level": "error" if error else "success"}})
    return response


# ---------------------------------------------------------------------------
# Teaching Loads — per-instructor summary for the active semester (Program
# Head: their own program(s); Admin: all, with a program filter).
# ---------------------------------------------------------------------------


def _scope_programs_for_teaching_loads(request):
    if request.user.is_admin_role:
        program_id = request.GET.get("program")
        qs = Program.objects.all()
        return qs.filter(pk=program_id) if program_id else qs
    return scoping.programs_in_scope(request.user)


@role_required(ADMIN, PROGRAM_HEAD)
def teaching_loads(request):
    active = Semester.objects.filter(is_active=True).first()
    programs = _scope_programs_for_teaching_loads(request)
    instructor_id = request.GET.get("instructor")
    rows, unassigned = teaching_load_rows(active, programs, instructor_id=instructor_id)

    context = {
        "page_title": "Teaching Loads",
        "active_semester_set": bool(active),
        "rows": rows,
        "unassigned": unassigned,
        "programs": Program.objects.all() if request.user.is_admin_role else programs,
        "instructors": User.objects.filter(role=INSTRUCTOR, is_active=True).order_by("last_name", "first_name"),
        "program_filter": request.GET.get("program", ""),
        "instructor_filter": instructor_id or "",
    }
    return render(request, "academics/teaching_loads.html", context)


@role_required(ADMIN, PROGRAM_HEAD)
def teaching_loads_export(request):
    from reports.excel import workbook_response

    active = Semester.objects.filter(is_active=True).first()
    programs = _scope_programs_for_teaching_loads(request)
    instructor_id = request.GET.get("instructor")
    rows, unassigned = teaching_load_rows(active, programs, instructor_id=instructor_id)

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Teaching Loads"
    sheet.append(["Instructor", "Classes", "Total Units", "Total Students"])
    for row in rows:
        sheet.append([row["instructor"].full_name, len(row["classes"]), float(row["total_units"]), row["total_students"]])
    sheet.append([])
    sheet.append(["Unassigned classes"])
    for class_offering in unassigned:
        sheet.append([str(class_offering)])
    return workbook_response(workbook, f"TeachingLoads_{active}.xlsx" if active else "TeachingLoads.xlsx")


# ---------------------------------------------------------------------------
# Class Lists (admin) — pick a class, manage its roster. CITCI GradeTrack
# does not handle enrollment (that's the Registrar's process); this only
# stores each class's official student list for grading.
# ---------------------------------------------------------------------------


def _roster_context(class_offering):
    roster_entries = list(
        class_offering.roster_entries.select_related("student", "student__student_profile").order_by(
            "status", "student__last_name", "student__first_name"
        )
    )
    memberships_by_student_id = {
        m.student_id: m.section
        for m in SectionMembership.objects.filter(
            semester=class_offering.semester, student_id__in=[e.student_id for e in roster_entries]
        ).select_related("section")
    }
    for entry in roster_entries:
        entry.membership_section = memberships_by_student_id.get(entry.student_id)
    return {"class_offering": class_offering, "roster_entries": roster_entries}


@role_required(ADMIN, PROGRAM_HEAD)
def class_lists_home(request):
    active = Semester.objects.filter(is_active=True).first()
    scoped_classes = (
        ClassOffering.objects.all() if request.user.is_admin_role else scoping.classes_in_scope(request.user)
    )

    class_id = request.GET.get("class")
    class_offering = None
    if class_id:
        class_offering = get_object_or_404(scoped_classes, pk=class_id)
    elif active:
        class_offering = (
            scoped_classes.filter(semester=active)
            .order_by("-semester__academic_year__start_year", "subject__code")
            .first()
        )

    context = {
        "page_title": "Class Lists",
        "selected_class": class_offering,
        "class_search_url": reverse("academics:class_search"),
    }
    if class_offering:
        context.update(_roster_context(class_offering))

    if is_htmx(request):
        return render(request, "academics/_class_list_roster.html", context)
    return render(request, "academics/class_lists.html", context)


@role_required(ADMIN, PROGRAM_HEAD)
def class_list_add_section(request, pk):
    class_offering = get_object_or_404(ClassOffering, pk=pk)
    if not _can_manage_roster(request.user, class_offering):
        raise PermissionDenied("You can only manage your own classes' class lists.")
    _require_semester_unlocked(class_offering)
    section_id = request.POST.get("section")
    section = get_object_or_404(class_offering.sections, pk=section_id)
    students = User.objects.filter(
        role=User.Role.STUDENT,
        section_memberships__section=section,
        section_memberships__semester=class_offering.semester,
    )
    added_count, skipped_count = 0, 0
    for student in students:
        _, created = ClassRosterEntry.objects.get_or_create(
            student=student, class_offering=class_offering, defaults={"status": ClassRosterEntry.Status.ACTIVE}
        )
        if created:
            added_count += 1
        else:
            skipped_count += 1

    context = _roster_context(class_offering)
    context["summary"] = f"{added_count} added, {skipped_count} already on the list (skipped)."
    return render(request, "academics/_class_list_roster.html", context)


@role_required(ADMIN, PROGRAM_HEAD)
def class_list_add_students_form(request, pk):
    class_offering = get_object_or_404(ClassOffering, pk=pk)
    if not _can_manage_roster(request.user, class_offering):
        raise PermissionDenied("You can only manage your own classes' class lists.")
    already_listed_ids = class_offering.roster_entries.values_list("student_id", flat=True)
    available_students = (
        User.objects.filter(role=User.Role.STUDENT)
        .exclude(id__in=already_listed_ids)
        .exclude(student_profile__status=StudentProfile.Status.COMPLETED)
        .order_by("last_name", "first_name")
    )
    query = request.GET.get("q", "").strip()
    if query:
        available_students = available_students.filter(
            Q(first_name__icontains=query) | Q(last_name__icontains=query) | Q(id_number__icontains=query)
        )
    context = {"class_offering": class_offering, "available_students": available_students[:50], "query": query}
    if is_htmx(request) and "q" in request.GET:
        return render(request, "academics/_class_list_students_checklist.html", context)
    return render(request, "academics/_class_list_add_students_modal.html", context)


@role_required(ADMIN, PROGRAM_HEAD)
def class_list_add_students_submit(request, pk):
    class_offering = get_object_or_404(ClassOffering, pk=pk)
    if not _can_manage_roster(request.user, class_offering):
        raise PermissionDenied("You can only manage your own classes' class lists.")
    _require_semester_unlocked(class_offering)
    student_ids = request.POST.getlist("student_ids")
    for student_id in student_ids:
        ClassRosterEntry.objects.get_or_create(
            student_id=student_id, class_offering=class_offering, defaults={"status": ClassRosterEntry.Status.ACTIVE}
        )
    count = len(student_ids)
    return trigger_response("refreshRoster", toast=f"Added {count} student{'s' if count != 1 else ''} to the class list.")


@role_required(ADMIN, PROGRAM_HEAD)
def class_list_mark_dropped(request, pk):
    entry = get_object_or_404(ClassRosterEntry, pk=pk)
    if not _can_manage_roster(request.user, entry.class_offering):
        raise PermissionDenied("You can only manage your own classes' class lists.")
    _require_semester_unlocked(entry.class_offering)
    entry.status = ClassRosterEntry.Status.DROPPED
    entry.date_dropped = date.today()
    entry.save(update_fields=["status", "date_dropped"])
    context = _roster_context(entry.class_offering)
    return render(request, "academics/_class_list_roster.html", context)


@role_required(ADMIN, PROGRAM_HEAD)
def class_list_restore(request, pk):
    entry = get_object_or_404(ClassRosterEntry, pk=pk)
    if not _can_manage_roster(request.user, entry.class_offering):
        raise PermissionDenied("You can only manage your own classes' class lists.")
    _require_semester_unlocked(entry.class_offering)
    entry.status = ClassRosterEntry.Status.ACTIVE
    entry.date_dropped = None
    entry.save(update_fields=["status", "date_dropped"])
    context = _roster_context(entry.class_offering)
    return render(request, "academics/_class_list_roster.html", context)


# ---------------------------------------------------------------------------
# Import class list (ADMIN for any class; INSTRUCTOR for their own classes
# only). Upload -> preview (new / existing / already / invalid) -> confirm.
# The parsed preview is stashed in the session between the two requests.
# ---------------------------------------------------------------------------

_IMPORT_SESSION_KEY = "class_list_import_preview"


@role_required(ADMIN, PROGRAM_HEAD, INSTRUCTOR)
def class_list_import_template(request):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Class List"
    sheet.append(["ID Number", "Last Name", "First Name", "Middle Name"])
    sheet.append(["2026-0001", "Dela Cruz", "Juan", "Santos"])

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    response = HttpResponse(
        buffer.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="class_list_template.xlsx"'
    return response


@role_required(ADMIN, PROGRAM_HEAD, INSTRUCTOR)
def class_list_import_upload(request, pk):
    class_offering = get_object_or_404(ClassOffering, pk=pk)
    if not _can_manage_roster(request.user, class_offering):
        raise PermissionDenied("You can only import a class list for your own classes.")

    if request.method != "POST":
        return render(request, "academics/_class_list_import_modal.html", {"class_offering": class_offering})

    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return render(
            request,
            "academics/_class_list_import_modal.html",
            {"class_offering": class_offering, "error": "Choose a file first."},
        )

    try:
        index, data_rows = parse_roster_file(uploaded_file)
        preview = build_preview(class_offering, index, data_rows)
    except RosterImportError as exc:
        return render(
            request,
            "academics/_class_list_import_modal.html",
            {"class_offering": class_offering, "error": str(exc)},
        )

    request.session[_IMPORT_SESSION_KEY] = {"class_offering_id": class_offering.pk, "rows": preview}
    return render(
        request,
        "academics/_class_list_import_preview.html",
        {
            "class_offering": class_offering,
            "preview": preview,
            "new_count": sum(1 for r in preview if r["kind"] == "new"),
            "existing_count": sum(1 for r in preview if r["kind"] == "existing"),
            "already_count": sum(1 for r in preview if r["kind"] == "already"),
            "invalid_count": sum(1 for r in preview if r["kind"] == "invalid"),
        },
    )


@role_required(ADMIN, PROGRAM_HEAD, INSTRUCTOR)
def class_list_import_confirm(request, pk):
    class_offering = get_object_or_404(ClassOffering, pk=pk)
    if not _can_manage_roster(request.user, class_offering):
        raise PermissionDenied("You can only import a class list for your own classes.")
    _require_semester_unlocked(class_offering)

    stashed = request.session.get(_IMPORT_SESSION_KEY)
    if not stashed or stashed.get("class_offering_id") != class_offering.pk:
        response = render(
            request,
            "academics/_class_list_import_modal.html",
            {"class_offering": class_offering, "error": "Your preview expired — upload the file again."},
        )
        response["HX-Retarget"] = "#modal-content"
        response["HX-Reswap"] = "innerHTML"
        return response

    target_section_id = request.POST.get("target_section")
    if not target_section_id and class_offering.sections.count() == 1:
        target_section = class_offering.sections.first()
    else:
        target_section = get_object_or_404(class_offering.sections, pk=target_section_id)

    commit_import(class_offering, stashed["rows"], target_section)
    del request.session[_IMPORT_SESSION_KEY]
    # refreshRoster is picked up both by the Class Lists page's #roster-container
    # and by class_roster.html (read-only roster, reloads itself on this event).
    return trigger_response("refreshRoster", toast="Class list imported.")


# ---------------------------------------------------------------------------
# Import Class Offerings (ADMIN only) — upload an .xlsx or the Registrar's
# .docx -> preview (new subjects / new classes / shared classes / unknown
# instructors) -> confirm. Never auto-creates or auto-merges an instructor.
# ---------------------------------------------------------------------------

_OFFERINGS_IMPORT_SESSION_KEY = "offerings_import_preview"


@role_required(ADMIN, PROGRAM_HEAD)
def offerings_import_template(request):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Class Offerings"
    sheet.append(["Semester", "Program", "Major", "Year Level", "Course Code", "Description", "Units", "Room", "Schedule", "Instructor"])
    sheet.append(["FIRST", "BSED", "ENG", "1", "ENG101", "Introduction to Literature", "3", "Room 101", "MWF 8:00-9:00AM", ""])

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    response = HttpResponse(
        buffer.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="class_offerings_template.xlsx"'
    return response


@role_required(ADMIN, PROGRAM_HEAD)
def offerings_import(request):
    context = {
        "page_title": "Import Class Offerings",
        "semesters": Semester.objects.select_related("academic_year").all(),
        "active_semester": Semester.objects.filter(is_active=True).first(),
    }
    return render(request, "academics/offerings_import.html", context)


@role_required(ADMIN, PROGRAM_HEAD)
def offerings_import_upload(request):
    scope_user = None if request.user.is_admin_role else request.user
    semester_id = request.POST.get("semester")
    target_semester = get_object_or_404(Semester, pk=semester_id) if semester_id else None
    if target_semester is None:
        return render(
            request, "academics/_offerings_import_result.html", {"error": "Choose a target semester first."}
        )

    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return render(
            request,
            "academics/_offerings_import_result.html",
            {"error": "Choose a file first.", "target_semester": target_semester},
        )

    name = uploaded_file.name.lower()
    try:
        if name.endswith(".docx"):
            preview = parse_offerings_docx_for_preview(uploaded_file, target_semester, user=scope_user)
        else:
            index, data_rows = parse_offerings_xlsx(uploaded_file)
            preview = build_offerings_preview(index, data_rows, target_semester, user=scope_user)
    except SpreadsheetImportError as exc:
        return render(
            request,
            "academics/_offerings_import_result.html",
            {"error": str(exc), "target_semester": target_semester},
        )

    request.session[_OFFERINGS_IMPORT_SESSION_KEY] = {"semester_id": target_semester.pk, "classes": preview["classes"]}
    context = {"target_semester": target_semester, **preview}
    return render(request, "academics/_offerings_import_preview.html", context)


@role_required(ADMIN, PROGRAM_HEAD)
def offerings_import_confirm(request):
    scope_user = None if request.user.is_admin_role else request.user
    semester_id = request.POST.get("semester")
    target_semester = get_object_or_404(Semester, pk=semester_id) if semester_id else None

    stashed = request.session.get(_OFFERINGS_IMPORT_SESSION_KEY)
    if not stashed or not target_semester or stashed.get("semester_id") != target_semester.pk:
        return render(
            request,
            "academics/_offerings_import_result.html",
            {"error": "Your preview expired — upload the file again."},
        )

    try:
        counts = commit_offerings_import(stashed["classes"], target_semester, user=scope_user)
    except PermissionDenied:
        del request.session[_OFFERINGS_IMPORT_SESSION_KEY]
        return render(
            request,
            "academics/_offerings_import_result.html",
            {"error": "One or more rows are outside your scope — upload the file again."},
        )
    del request.session[_OFFERINGS_IMPORT_SESSION_KEY]
    return render(
        request,
        "academics/_offerings_import_result.html",
        {"target_semester": target_semester, "success": True, **counts},
    )


# ---------------------------------------------------------------------------
# Copy classes from previous semester (ADMIN only) — preview first; the
# instructor is always left Unassigned on the copy (Program Heads assign
# teaching loads).
# ---------------------------------------------------------------------------

_OFFERINGS_COPY_SESSION_KEY = "offerings_copy_preview"


@role_required(ADMIN)
def offerings_copy_previous(request):
    target_semester = Semester.objects.filter(is_active=True).first()
    if request.method != "POST":
        source = default_source_semester(target_semester) if target_semester else None
        return render(
            request,
            "academics/_offerings_copy_modal.html",
            {
                "target_semester": target_semester,
                "default_source": source,
                "semesters": Semester.objects.exclude(pk=getattr(target_semester, "pk", None)).select_related("academic_year"),
            },
        )

    source_id = request.POST.get("source_semester")
    source_semester = get_object_or_404(Semester, pk=source_id)
    if target_semester is None:
        return render(
            request,
            "academics/_offerings_copy_modal.html",
            {"error": "No active semester is set.", "semesters": Semester.objects.select_related("academic_year")},
        )

    preview_rows = build_copy_preview(source_semester, target_semester)
    request.session[_OFFERINGS_COPY_SESSION_KEY] = {
        "source_semester_id": source_semester.pk,
        "target_semester_id": target_semester.pk,
        "rows": [
            {
                "class_offering_id": row["class_offering"].pk,
                "target_section_ids": row["target_section_ids"],
                "can_copy": row["can_copy"],
            }
            for row in preview_rows
        ],
    }
    return render(
        request,
        "academics/_offerings_copy_preview.html",
        {"target_semester": target_semester, "source_semester": source_semester, "rows": preview_rows},
    )


@role_required(ADMIN)
def offerings_copy_previous_confirm(request):
    stashed = request.session.get(_OFFERINGS_COPY_SESSION_KEY)
    target_semester = Semester.objects.filter(is_active=True).first()
    if not stashed or not target_semester or stashed.get("target_semester_id") != target_semester.pk:
        return render(
            request,
            "academics/_offerings_copy_modal.html",
            {"error": "Your preview expired — start again.", "semesters": Semester.objects.select_related("academic_year")},
        )

    preview_rows = []
    for row in stashed["rows"]:
        class_offering = ClassOffering.objects.filter(pk=row["class_offering_id"]).first()
        if class_offering is None:
            continue
        preview_rows.append(
            {
                "class_offering": class_offering,
                "target_section_ids": row["target_section_ids"],
                "can_copy": row["can_copy"],
            }
        )

    counts = commit_copy(preview_rows, target_semester)
    del request.session[_OFFERINGS_COPY_SESSION_KEY]
    return trigger_response(
        "refreshClasses",
        toast=f"Copied {counts['created']} class(es)." + (f" {counts['skipped']} skipped (no matching section)." if counts["skipped"] else ""),
    )


# ---------------------------------------------------------------------------
# New Academic Year wizard (ADMIN only) — 4 plain-page steps, session-backed
# like the import flows above. Only step 4's POST writes to the database,
# in one transaction. Past semesters' grades/sections are never touched.
# ---------------------------------------------------------------------------

_AY_WIZARD_SESSION_KEY = "ay_wizard"
_AY_WIZARD_STEPS = [(1, "New Year"), (2, "Sections"), (3, "Promote Students"), (4, "Summary")]


@role_required(ADMIN)
def ay_wizard_step1(request):
    academic_years = AcademicYear.objects.all()
    if request.method != "POST":
        request.session.pop(_AY_WIZARD_SESSION_KEY, None)
        return render(request, "academics/ay_wizard_step1.html", {"academic_years": academic_years, "active": 1, "steps": _AY_WIZARD_STEPS})

    try:
        start_year = int(request.POST.get("start_year", ""))
    except ValueError:
        return render(
            request,
            "academics/ay_wizard_step1.html",
            {"academic_years": academic_years, "error": "Enter a valid starting year.", "active": 1, "steps": _AY_WIZARD_STEPS},
        )

    term_values = request.POST.getlist("terms")
    if not term_values:
        return render(
            request,
            "academics/ay_wizard_step1.html",
            {"academic_years": academic_years, "error": "Select at least one semester to create.", "active": 1, "steps": _AY_WIZARD_STEPS},
        )

    preview = step1_preview(start_year)
    if preview["already_exists"]:
        return render(
            request,
            "academics/ay_wizard_step1.html",
            {"academic_years": academic_years, "error": f"A.Y. {start_year}–{start_year + 1} already exists.", "active": 1, "steps": _AY_WIZARD_STEPS},
        )

    source_id = request.POST.get("source_academic_year")
    source_academic_year = get_object_or_404(AcademicYear, pk=source_id) if source_id else academic_years.first()
    if source_academic_year is None:
        return render(
            request,
            "academics/ay_wizard_step1.html",
            {"academic_years": academic_years, "error": "No existing academic year to copy the section structure from.", "active": 1, "steps": _AY_WIZARD_STEPS},
        )

    from django.utils.dateparse import parse_date

    from .semester_validation import duration_warning, ranges_overlap, validate_date_range

    term_dates = {}
    field_errors = []
    for term in term_values:
        start_raw = request.POST.get(f"start_{term}", "").strip()
        end_raw = request.POST.get(f"end_{term}", "").strip()
        start = parse_date(start_raw) if start_raw else None
        end = parse_date(end_raw) if end_raw else None
        term_dates[term] = (start.isoformat() if start else None, end.isoformat() if end else None)
        errors = validate_date_range(start, end, start_year, start_year + 1)
        for field, message in errors.items():
            field_errors.append(f"{Term(term).label} {field.replace('_', ' ')}: {message}")

    for i, term_a in enumerate(term_values):
        start_a, end_a = term_dates[term_a]
        if not (start_a and end_a):
            continue
        start_a, end_a = date.fromisoformat(start_a), date.fromisoformat(end_a)
        for term_b in term_values[i + 1 :]:
            start_b, end_b = term_dates[term_b]
            if not (start_b and end_b):
                continue
            start_b, end_b = date.fromisoformat(start_b), date.fromisoformat(end_b)
            if ranges_overlap(start_a, end_a, start_b, end_b):
                field_errors.append(f"{Term(term_a).label} and {Term(term_b).label} dates overlap.")

    if field_errors:
        return render(
            request,
            "academics/ay_wizard_step1.html",
            {"academic_years": academic_years, "error": " ".join(field_errors), "active": 1, "steps": _AY_WIZARD_STEPS},
        )

    warnings = []
    for term in term_values:
        start_raw, end_raw = term_dates[term]
        if start_raw and end_raw:
            warning = duration_warning(term, date.fromisoformat(start_raw), date.fromisoformat(end_raw))
            if warning:
                warnings.append(f"{Term(term).label}: {warning}")

    request.session[_AY_WIZARD_SESSION_KEY] = {
        "start_year": start_year,
        "term_values": term_values,
        "term_dates": term_dates,
        "source_academic_year_id": source_academic_year.pk,
        "warnings": warnings,
    }
    return redirect("academics:ay_wizard_step2")


@role_required(ADMIN)
def ay_wizard_step2(request):
    stashed = request.session.get(_AY_WIZARD_SESSION_KEY)
    if not stashed:
        return redirect("academics:ay_wizard_step1")
    source_academic_year = get_object_or_404(AcademicYear, pk=stashed["source_academic_year_id"])
    sections = step2_preview_sections(source_academic_year)

    if request.method == "POST":
        stashed["sections"] = sections
        request.session[_AY_WIZARD_SESSION_KEY] = stashed
        return redirect("academics:ay_wizard_step3")

    return render(
        request,
        "academics/ay_wizard_step2.html",
        {
            "start_year": stashed["start_year"],
            "source_academic_year": source_academic_year,
            "sections": sections,
            "warnings": stashed.get("warnings", []),
            "active": 2,
            "steps": _AY_WIZARD_STEPS,
        },
    )


@role_required(ADMIN)
def ay_wizard_step3(request):
    stashed = request.session.get(_AY_WIZARD_SESSION_KEY)
    if not stashed or "sections" not in stashed:
        return redirect("academics:ay_wizard_step1")
    source_academic_year = get_object_or_404(AcademicYear, pk=stashed["source_academic_year_id"])
    rows = step3_preview_promotions(source_academic_year, stashed["sections"])

    if request.method == "POST":
        excluded_ids = sorted({int(pid) for pid in request.POST.getlist("exclude")})
        stashed["excluded_profile_ids"] = excluded_ids
        request.session[_AY_WIZARD_SESSION_KEY] = stashed
        return redirect("academics:ay_wizard_step4")

    return render(
        request,
        "academics/ay_wizard_step3.html",
        {"start_year": stashed["start_year"], "rows": rows, "active": 3, "steps": _AY_WIZARD_STEPS},
    )


@role_required(ADMIN)
def ay_wizard_step4(request):
    stashed = request.session.get(_AY_WIZARD_SESSION_KEY)
    if not stashed or "sections" not in stashed:
        return redirect("academics:ay_wizard_step1")
    source_academic_year = get_object_or_404(AcademicYear, pk=stashed["source_academic_year_id"])
    rows = step3_preview_promotions(source_academic_year, stashed["sections"])
    excluded_ids = set(stashed.get("excluded_profile_ids", []))
    for row in rows:
        row["excluded"] = row["profile_id"] in excluded_ids

    if request.method == "POST":
        result = step4_commit(
            stashed["start_year"],
            stashed["term_values"],
            stashed["sections"],
            rows,
            request.user,
            term_dates=stashed.get("term_dates"),
            source_academic_year=source_academic_year,
        )
        del request.session[_AY_WIZARD_SESSION_KEY]
        return render(request, "academics/ay_wizard_done.html", result)

    context = {
        "start_year": stashed["start_year"],
        "sections": stashed["sections"],
        "promote_count": sum(1 for r in rows if not r["excluded"] and not r["will_complete"] and not r["unresolved"]),
        "complete_count": sum(1 for r in rows if not r["excluded"] and r["will_complete"]),
        "excluded_count": sum(1 for r in rows if r["excluded"]),
        "unresolved_count": sum(1 for r in rows if not r["excluded"] and r["unresolved"]),
        "active": 4,
        "steps": _AY_WIZARD_STEPS,
    }
    return render(request, "academics/ay_wizard_step4.html", context)


# ---------------------------------------------------------------------------
# Searchable-select endpoints (core.widgets.SearchableSelectWidget) — each
# renders partials/_searchable_select_options.html with a list of (pk, label).
# ---------------------------------------------------------------------------


@role_required(ADMIN)
def instructor_search(request):
    query = request.GET.get("q", "").strip()
    qs = User.objects.filter(role=INSTRUCTOR, is_active=True)
    if query:
        qs = qs.filter(Q(first_name__icontains=query) | Q(last_name__icontains=query) | Q(username__icontains=query))
    options = [(u.pk, u.full_name) for u in qs.order_by("last_name", "first_name")[:20]]
    return render(request, "partials/_searchable_select_options.html", {"options": options})


@role_required(ADMIN, PROGRAM_HEAD)
def class_search(request):
    query = request.GET.get("q", "").strip()
    if request.user.is_admin_role:
        qs = ClassOffering.objects.select_related("subject").prefetch_related("sections")
    else:
        qs = scoping.classes_in_scope(request.user).select_related("subject").prefetch_related("sections")
    if query:
        qs = qs.filter(Q(subject__code__icontains=query) | Q(subject__title__icontains=query))
    options = [(c.pk, str(c)) for c in qs.order_by("-semester__academic_year__start_year", "subject__code")[:20]]
    return render(request, "partials/_searchable_select_options.html", {"options": options})


# ---------------------------------------------------------------------------
# Class join codes — student side. /join/<code>/ is the single entry point
# for both the typed-code modal (redirected here) and a scanned QR code;
# GET shows a confirmation screen, POST actually files the request.
# ---------------------------------------------------------------------------


@role_required(STUDENT)
def student_my_classes(request):
    active = Semester.objects.filter(is_active=True).first()
    roster_entries = ClassRosterEntry.objects.none()
    join_requests = ClassJoinRequest.objects.none()
    if active:
        roster_entries = (
            ClassRosterEntry.objects.filter(
                student=request.user, class_offering__semester=active, status=ClassRosterEntry.Status.ACTIVE
            )
            .select_related("class_offering__subject", "class_offering__instructor")
            .prefetch_related("class_offering__sections")
        )
        join_requests = (
            ClassJoinRequest.objects.filter(student=request.user, class_offering__semester=active)
            .filter(status__in=[ClassJoinRequest.Status.PENDING, ClassJoinRequest.Status.REJECTED])
            .select_related("class_offering__subject", "class_offering__instructor")
            .prefetch_related("class_offering__sections")
        )
    return render(
        request,
        "academics/student_my_classes.html",
        {
            "page_title": "My Classes",
            "active_semester_set": bool(active),
            "roster_entries": roster_entries,
            "join_requests": join_requests,
            "join_form": JoinCodeForm(),
        },
    )


@role_required(STUDENT)
def student_join_modal(request):
    if request.method != "POST":
        return render(request, "academics/_join_modal.html", {"form": JoinCodeForm()})
    form = JoinCodeForm(request.POST)
    if not form.is_valid():
        return render(request, "academics/_join_modal.html", {"form": form})
    code = form.cleaned_data["code"].strip().upper()
    response = HttpResponse(status=204)
    response["HX-Redirect"] = reverse("academics:join_with_code", args=[code])
    return response


@role_required(STUDENT)
def student_join_cancel(request, pk):
    join_request = get_object_or_404(ClassJoinRequest, pk=pk)
    try:
        services.cancel_join_request(join_request, request.user)
    except PermissionError:
        raise PermissionDenied("Not your request.")
    except ValidationError as exc:
        from django.contrib import messages as django_messages

        django_messages.error(request, exc.messages[0])
    return trigger_response("refreshMyClasses", toast="Request cancelled.")


@role_required(STUDENT)
def join_with_code(request, code):
    """GET: resolve the code and show a confirmation screen (subject,
    section, instructor, semester) before anything is submitted — the
    page a scanned QR *or* the typed-code modal both land on. POST:
    actually files the join request. Wrong-code attempts (not eligibility
    failures on an otherwise-valid code) count toward the rate limit."""
    if not services.check_join_rate_limit(request.user):
        return render(
            request,
            "academics/join_confirm.html",
            {"error": "Too many attempts — please try again in a few minutes.", "code": code},
        )

    try:
        class_offering = services.resolve_join_code(code)
    except ValidationError as exc:
        services.record_join_attempt(request.user)
        return render(request, "academics/join_confirm.html", {"error": exc.messages[0], "code": code})

    if request.method == "POST":
        try:
            services.request_to_join(class_offering, request.user)
        except ValidationError as exc:
            return render(
                request,
                "academics/join_confirm.html",
                {"error": exc.messages[0], "class_offering": class_offering, "code": code},
            )
        return render(request, "academics/join_submitted.html", {"class_offering": class_offering})

    error = None
    try:
        services.check_join_eligibility(class_offering, request.user)
    except ValidationError as exc:
        error = exc.messages[0]
    return render(
        request, "academics/join_confirm.html", {"class_offering": class_offering, "code": code, "error": error}
    )
