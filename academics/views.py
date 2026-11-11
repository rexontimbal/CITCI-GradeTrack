import io
import json
from datetime import date
from decimal import Decimal

import openpyxl
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, ProtectedError, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
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
    AdminSubjectForm,
    BulkAssignInstructorForm,
    ClassOfferingForm,
    CurriculumEntryExistingSubjectForm,
    JoinClassForm,
    MajorForm,
    ProgramForm,
    ProgramHeadClassOfferingForm,
    ProgramHeadSectionForm,
    SectionForm,
    SemesterForm,
    SubjectEditForm,
    SubjectQuickCreateForm,
    TeachingAssignmentForm,
)
from .models import (
    AcademicSetupChangeLog,
    AcademicYear,
    ClassOffering,
    ClassRosterEntry,
    CurriculumEntry,
    Major,
    Program,
    Section,
    Semester,
    StudentProfile,
    Subject,
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
    default_source_semester,
    log_and_notify_instructor_change,
    notify_program_head_assignment,
    teaching_load_rows,
)

ADMIN = User.Role.ADMIN
PROGRAM_HEAD = User.Role.PROGRAM_HEAD
INSTRUCTOR = User.Role.INSTRUCTOR


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


class SectionListView(RoleRequiredMixin, EntityListView):
    allowed_roles = (ADMIN,)
    model = Section
    list_template = "academics/sections.html"
    table_template = "academics/_sections_table.html"
    table_id = "sections-table"
    page_title = "Sections"
    search_fields = ["name__icontains", "program__code__icontains"]
    refresh_event = "refreshSections"

    def apply_filters(self, request, qs):
        qs = qs.select_related("program", "major", "academic_year")
        program = request.GET.get("program")
        academic_year = request.GET.get("academic_year")
        year_level = request.GET.get("year_level")
        if program:
            qs = qs.filter(program_id=program)
        if academic_year:
            qs = qs.filter(academic_year_id=academic_year)
        if year_level:
            qs = qs.filter(year_level=year_level)
        return qs

    def get_extra_context(self, request):
        return {"programs": Program.objects.all(), "academic_years": AcademicYear.objects.all()}


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


@role_required(PROGRAM_HEAD)
def ph_sections(request):
    academic_year = _active_academic_year()
    sections = (
        scoping.sections_in_scope(request.user).filter(academic_year=academic_year).select_related("program", "major")
        if academic_year
        else Section.objects.none()
    )
    return render(
        request,
        "academics/ph_sections.html",
        {"page_title": "Sections", "sections": sections, "active_semester_set": bool(academic_year)},
    )


def _section_in_scope_or_403(request, section):
    if not scoping.is_in_scope(request.user, section.program_id, section.major_id):
        raise PermissionDenied("This section is not under your program.")


@role_required(PROGRAM_HEAD)
def ph_section_create(request):
    academic_year = _active_academic_year()
    if academic_year is None:
        raise PermissionDenied("No active semester is set.")

    if request.method != "POST":
        form = ProgramHeadSectionForm(user=request.user)
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


def _resolve_program_major_from_request(request, user):
    """Resolves the (program, major-or-None) pair a Subjects prospectus
    request is showing. Admin: any program/major from ?program=/?major=
    (or the first active program if neither given). Program Head: must be
    within scope_for(user) — 403 otherwise — defaulting to the first scope
    tuple if neither param is given."""
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

    scope = scoping.scope_for(user)
    if not scope:
        return None, None
    if program_id:
        program = get_object_or_404(Program, pk=program_id)
        major = get_object_or_404(Major, pk=major_id) if major_id else None
        if not scoping.is_in_scope(user, program.id, major.id if major else None):
            raise PermissionDenied("This program/major is not under your scope.")
        return program, major

    first_program_id, first_major_id = sorted(scope, key=lambda t: (t[0], t[1] or 0))[0]
    program = Program.objects.get(pk=first_program_id)
    major = Major.objects.get(pk=first_major_id) if first_major_id else None
    return program, major


def _subject_prospectus_context(program, major, query=""):
    """One card per year level (plus one no-year-level card for a TCP-
    style major/program) each with a 1st/2nd Sem[/Summer] sub-table of
    CurriculumEntry rows, a per-sub-table unit total, and a "Shared"
    badge listing any OTHER program/major that also places the same
    subject — all computed in a small, fixed number of queries rather
    than per-row."""
    entries = CurriculumEntry.objects.filter(program=program, major=major).select_related("subject")
    if query:
        entries = entries.filter(Q(subject__code__icontains=query) | Q(subject__title__icontains=query))
    entries = list(entries.order_by("year_level", "term", "subject__code"))

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

    return cards, shared_labels


@role_required(ADMIN, PROGRAM_HEAD)
def subjects_home(request):
    is_admin = request.user.is_admin_role
    program, major = _resolve_program_major_from_request(request, request.user)

    context = {"page_title": "Subjects", "is_admin": is_admin, "program": program, "major": major}
    if program is None:
        context["no_scope"] = True
        return render(request, "academics/subjects.html", context)

    query = request.GET.get("q", "").strip()
    cards, shared_labels = _subject_prospectus_context(program, major, query)
    context.update({"cards": cards, "shared_labels": shared_labels, "query": query})

    if is_admin:
        context["programs"] = Program.objects.filter(is_active=True).order_by("code")
        context["majors"] = Major.objects.filter(program=program, is_active=True).order_by("code")
    else:
        context["editable_subject_ids"] = set(
            scoping.subjects_editable_by(request.user).values_list("id", flat=True)
        )
        scope = scoping.scope_for(request.user)
        pills = []
        for program_id, major_id in sorted(scope, key=lambda t: (t[0], t[1] or 0)):
            label = Major.objects.get(pk=major_id).name if major_id else Program.objects.get(pk=program_id).code
            pills.append(
                {
                    "label": label,
                    "program_id": program_id,
                    "major_id": major_id or "",
                    "active": program.id == program_id and (major.id if major else None) == major_id,
                }
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


def _subject_add_context(program, major, year_level, term, existing_form=None, create_form=None):
    return {
        "existing_form": existing_form or CurriculumEntryExistingSubjectForm(),
        "create_form": create_form or SubjectQuickCreateForm(),
        "program": program,
        "major": major,
        "year_level": year_level,
        "term": term,
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
        return render(
            request, "academics/_subject_add_modal.html", _subject_add_context(program, major, year_level, term)
        )

    is_admin_override = request.user.is_admin_role
    mode = request.POST.get("mode")
    if mode == "existing":
        form = CurriculumEntryExistingSubjectForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                "academics/_subject_add_modal.html",
                _subject_add_context(program, major, year_level, term, existing_form=form),
            )
        subject = form.cleaned_data["subject"]
    else:
        form = SubjectQuickCreateForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                "academics/_subject_add_modal.html",
                _subject_add_context(program, major, year_level, term, create_form=form),
            )
        subject = form.save()

    entry, created = CurriculumEntry.objects.get_or_create(
        program=program, major=major, year_level=year_level, term=term, subject=subject
    )
    if created:
        _log_academic_setup_change(
            AcademicSetupChangeLog.ModelName.SUBJECT,
            subject,
            AcademicSetupChangeLog.Action.ADDED_TO_CURRICULUM,
            request.user,
            is_admin_override=is_admin_override,
            program=program,
            major=major,
        )
        toast = f"{subject.code} added to the curriculum."
    else:
        toast = f"{subject.code} is already in this curriculum slot."
    return trigger_response("refreshSubjects", toast=toast)


@role_required(ADMIN, PROGRAM_HEAD)
def subject_edit(request, pk):
    subject = get_object_or_404(Subject, pk=pk)
    is_admin = request.user.is_admin_role
    if not is_admin and not scoping.subjects_editable_by(request.user).filter(pk=subject.pk).exists():
        raise PermissionDenied("This subject is shared — ask the Admin to edit it.")

    form_class = AdminSubjectForm if is_admin else SubjectEditForm
    if request.method != "POST":
        form = form_class(instance=subject)
        return render(request, "partials/_entity_form_modal.html", {"form": form, "modal_title": "Edit Subject"})

    form = form_class(request.POST, instance=subject)
    if form.is_valid():
        subject = form.save()
        _log_academic_setup_change(
            AcademicSetupChangeLog.ModelName.SUBJECT,
            subject,
            AcademicSetupChangeLog.Action.UPDATED,
            request.user,
            is_admin_override=is_admin,
        )
        return trigger_response("refreshSubjects", toast="Subject updated.")
    return render(request, "partials/_entity_form_modal.html", {"form": form, "modal_title": "Edit Subject"})


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

    def post(self, request, pk=None):
        obj = self.get_object(pk)
        is_create = obj is None
        old_instructor = obj.instructor if obj else None
        form = self.form_class(request.POST, instance=obj)
        if not form.is_valid():
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
    roster_entries = class_offering.roster_entries.select_related("student", "student__student_profile__section")
    assignment_logs = class_offering.assignment_logs.select_related("old_instructor", "new_instructor", "changed_by")[:10]
    return render(
        request,
        "academics/class_roster.html",
        {
            "page_title": f"Roster — {class_offering}",
            "class_offering": class_offering,
            "roster_entries": roster_entries,
            "can_manage": _can_manage_roster(request.user, class_offering),
            "assignment_logs": assignment_logs,
        },
    )


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
                )
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
            )
        )
        .distinct()
    )


@role_required(PROGRAM_HEAD)
def program_head_classes(request):
    """Teaching-load manager for a Program Head's own program(s): assign/
    change an instructor per class (academics:class_assign_instructor,
    opened in the shared modal), an "Unassigned only" filter, and a bulk
    "select several -> assign one instructor" action."""
    active = Semester.objects.filter(is_active=True).first()
    qs = _program_head_class_queryset(request.user, active)
    unassigned_count = qs.filter(instructor__isnull=True).count() if active else 0

    if request.GET.get("unassigned") == "1":
        qs = qs.filter(instructor__isnull=True)

    return render(
        request,
        "academics/program_head_classes.html",
        {
            "page_title": "Classes",
            "classes": qs,
            "active_semester_set": bool(active),
            "unassigned_count": unassigned_count,
            "unassigned_filter": request.GET.get("unassigned") == "1",
            "bulk_form": BulkAssignInstructorForm(),
        },
    )


@role_required(PROGRAM_HEAD)
def ph_class_create(request):
    active = Semester.objects.filter(is_active=True).first()
    if active is None:
        raise PermissionDenied("No active semester is set.")

    if request.method != "POST":
        form = ProgramHeadClassOfferingForm(user=request.user, academic_year=active.academic_year)
        return render(request, "partials/_entity_form_modal.html", {"form": form, "modal_title": "Add Class"})

    form = ProgramHeadClassOfferingForm(request.POST, user=request.user, academic_year=active.academic_year)
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
    return render(request, "partials/_entity_form_modal.html", {"form": form, "modal_title": "Add Class"})


@role_required(PROGRAM_HEAD)
def ph_class_edit(request, pk):
    class_offering = get_object_or_404(ClassOffering, pk=pk)
    if not class_offering.sections.filter(pk__in=scoping.sections_in_scope(request.user)).exists():
        raise PermissionDenied("This class is not under your program.")
    active = Semester.objects.filter(is_active=True).first()

    if request.method != "POST":
        form = ProgramHeadClassOfferingForm(
            instance=class_offering, user=request.user, academic_year=class_offering.semester.academic_year
        )
        return render(request, "partials/_entity_form_modal.html", {"form": form, "modal_title": "Edit Class"})

    old_instructor = class_offering.instructor
    form = ProgramHeadClassOfferingForm(
        request.POST, instance=class_offering, user=request.user, academic_year=class_offering.semester.academic_year
    )
    if not form.is_valid():
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

    if request.method != "POST":
        return render(
            request,
            "academics/_ph_class_leave_confirm.html",
            {"class_offering": class_offering, "sections": own_sections_in_class},
        )

    section_ids = list(own_sections_in_class.values_list("pk", flat=True))
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


@role_required(ADMIN, PROGRAM_HEAD)
def class_bulk_assign_instructor(request):
    """A plain (non-HTMX) form POST — checkboxes in a table don't need
    HTMX's modal/toast machinery, just messages + a redirect back."""
    from django.contrib import messages as django_messages
    from django.shortcuts import redirect

    redirect_to = "academics:classes" if request.user.is_admin_role else "academics:program_head_classes"
    if request.method != "POST":
        raise PermissionDenied

    form = BulkAssignInstructorForm(request.POST)
    if not form.is_valid():
        error_text = "; ".join(" ".join(errs) for errs in form.errors.values())
        django_messages.error(request, error_text or "Could not assign.")
        return redirect(redirect_to)

    class_ids = form.cleaned_data["class_ids"]
    instructor = form.cleaned_data["instructor"]
    is_admin_override = request.user.is_admin_role

    classes = ClassOffering.objects.filter(pk__in=class_ids)
    if not is_admin_override:
        classes = classes.filter(pk__in=scoping.classes_in_scope(request.user))

    assigned, blocked = 0, 0
    for class_offering in classes:
        try:
            result = assign_instructor(class_offering, instructor, request.user, is_admin_override=is_admin_override)
            if result is not None:
                assigned += 1
        except ValidationError:
            blocked += 1

    text = f"Assigned {instructor.full_name} to {assigned} class{'es' if assigned != 1 else ''}."
    if blocked:
        text += f" {blocked} already-submitted class{'es were' if blocked != 1 else ' was'} skipped."
    django_messages.success(request, text)
    return redirect(redirect_to)


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
    roster_entries = class_offering.roster_entries.select_related("student").order_by(
        "status", "student__last_name", "student__first_name"
    )
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
    section_id = request.POST.get("section")
    section = get_object_or_404(class_offering.sections, pk=section_id)
    students = User.objects.filter(role=User.Role.STUDENT, student_profile__section=section)
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
