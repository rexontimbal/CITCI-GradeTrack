import io
from datetime import date

import openpyxl
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views import View

from accounts.decorators import role_required
from accounts.mixins import RoleRequiredMixin
from accounts.models import User
from core.crud import EntityDeleteView, EntityFormView, EntityListView, ToggleActiveView, trigger_response
from core.htmx import is_htmx

from .forms import AcademicYearForm, ClassOfferingForm, MajorForm, ProgramForm, SectionForm, SemesterForm, SubjectForm
from .models import (
    AcademicYear,
    ClassOffering,
    ClassRosterEntry,
    Major,
    Program,
    Section,
    Semester,
    Subject,
)
from .roster_import import RosterImportError, build_preview, commit_import, parse_roster_file

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
        {"semesters": Semester.objects.select_related("academic_year").all()},
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
        return trigger_response("refreshSemesters")


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
        qs = qs.select_related("program")
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
    allowed_roles = (ADMIN,)
    model = Section
    form_class = SectionForm
    refresh_event = "refreshSections"
    modal_title_create = "Add Section"
    modal_title_edit = "Edit Section"


class SectionDeleteView(RoleRequiredMixin, EntityDeleteView):
    allowed_roles = (ADMIN,)
    model = Section
    refresh_event = "refreshSections"
    protect_message = "This section has classes or students using it."


# ---------------------------------------------------------------------------
# Subjects
# ---------------------------------------------------------------------------


class SubjectListView(RoleRequiredMixin, EntityListView):
    allowed_roles = (ADMIN,)
    model = Subject
    list_template = "academics/subjects.html"
    table_template = "academics/_subjects_table.html"
    table_id = "subjects-table"
    page_title = "Subjects"
    search_fields = ["code__icontains", "title__icontains"]
    refresh_event = "refreshSubjects"

    def apply_filters(self, request, qs):
        qs = qs.select_related("program", "major")
        program = request.GET.get("program")
        year_level = request.GET.get("year_level")
        is_active = request.GET.get("is_active")
        if program:
            qs = qs.filter(program_id=program)
        if year_level:
            qs = qs.filter(year_level=year_level)
        if is_active in ("true", "false"):
            qs = qs.filter(is_active=(is_active == "true"))
        return qs

    def get_extra_context(self, request):
        return {"programs": Program.objects.all()}


class SubjectFormView(RoleRequiredMixin, EntityFormView):
    allowed_roles = (ADMIN,)
    model = Subject
    form_class = SubjectForm
    refresh_event = "refreshSubjects"
    modal_title_create = "Add Subject"
    modal_title_edit = "Edit Subject"


class SubjectDeleteView(RoleRequiredMixin, EntityDeleteView):
    allowed_roles = (ADMIN,)
    model = Subject
    refresh_event = "refreshSubjects"
    label_field = "code"
    deactivate_url_name = "academics:subject_toggle_active"
    protect_message = "This subject has classes using it."


class SubjectToggleActiveView(RoleRequiredMixin, ToggleActiveView):
    allowed_roles = (ADMIN,)
    model = Subject
    refresh_event = "refreshSubjects"


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
    allowed_roles = (ADMIN,)
    model = ClassOffering
    form_class = ClassOfferingForm
    refresh_event = "refreshClasses"
    modal_title_create = "Add Class"
    modal_title_edit = "Edit Class"


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
    """ADMIN can manage any class's roster; an INSTRUCTOR only their own."""
    return user.is_admin_role or (user.is_instructor and class_offering.instructor_id == user.id)


def _get_class_offering_for_viewer(request, pk):
    class_offering = get_object_or_404(
        ClassOffering.objects.select_related("subject", "semester", "instructor").prefetch_related(
            "sections__program"
        ),
        pk=pk,
    )
    user = request.user
    if user.is_program_head and not class_offering.sections.filter(program__program_head_id=user.id).exists():
        raise PermissionDenied("This class is not under your program.")
    if user.is_instructor and class_offering.instructor_id != user.id:
        raise PermissionDenied("This class is not assigned to you.")
    return class_offering


@role_required(ADMIN, PROGRAM_HEAD, INSTRUCTOR)
def class_roster(request, pk):
    class_offering = _get_class_offering_for_viewer(request, pk)
    roster_entries = class_offering.roster_entries.select_related("student", "student__student_profile__section")
    return render(
        request,
        "academics/class_roster.html",
        {
            "page_title": f"Roster — {class_offering}",
            "class_offering": class_offering,
            "roster_entries": roster_entries,
            "can_manage": _can_manage_roster(request.user, class_offering),
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


@role_required(PROGRAM_HEAD)
def program_head_classes(request):
    active = Semester.objects.filter(is_active=True).first()
    qs = ClassOffering.objects.none()
    if active:
        qs = (
            ClassOffering.objects.filter(sections__program__program_head=request.user, semester=active)
            .select_related("subject", "instructor")
            .prefetch_related("sections")
            .annotate(
                roster_size=Count(
                    "roster_entries", filter=Q(roster_entries__status=ClassRosterEntry.Status.ACTIVE), distinct=True
                )
            )
            .distinct()
        )
    return render(
        request,
        "academics/program_head_classes.html",
        {"page_title": "Classes", "classes": qs, "active_semester_set": bool(active)},
    )


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


@role_required(ADMIN)
def class_lists_home(request):
    active = Semester.objects.filter(is_active=True).first()
    class_id = request.GET.get("class")
    class_offering = None
    if class_id:
        class_offering = get_object_or_404(ClassOffering, pk=class_id)
    elif active:
        class_offering = (
            ClassOffering.objects.filter(semester=active)
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


@role_required(ADMIN)
def class_list_add_section(request, pk):
    class_offering = get_object_or_404(ClassOffering, pk=pk)
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


@role_required(ADMIN)
def class_list_add_students_form(request, pk):
    class_offering = get_object_or_404(ClassOffering, pk=pk)
    already_listed_ids = class_offering.roster_entries.values_list("student_id", flat=True)
    available_students = (
        User.objects.filter(role=User.Role.STUDENT)
        .exclude(id__in=already_listed_ids)
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


@role_required(ADMIN)
def class_list_add_students_submit(request, pk):
    class_offering = get_object_or_404(ClassOffering, pk=pk)
    student_ids = request.POST.getlist("student_ids")
    for student_id in student_ids:
        ClassRosterEntry.objects.get_or_create(
            student_id=student_id, class_offering=class_offering, defaults={"status": ClassRosterEntry.Status.ACTIVE}
        )
    return trigger_response("refreshRoster")


@role_required(ADMIN)
def class_list_mark_dropped(request, pk):
    entry = get_object_or_404(ClassRosterEntry, pk=pk)
    entry.status = ClassRosterEntry.Status.DROPPED
    entry.date_dropped = date.today()
    entry.save(update_fields=["status", "date_dropped"])
    context = _roster_context(entry.class_offering)
    return render(request, "academics/_class_list_roster.html", context)


@role_required(ADMIN)
def class_list_restore(request, pk):
    entry = get_object_or_404(ClassRosterEntry, pk=pk)
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


@role_required(ADMIN, INSTRUCTOR)
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


@role_required(ADMIN, INSTRUCTOR)
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


@role_required(ADMIN, INSTRUCTOR)
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
    return trigger_response("refreshRoster")


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


@role_required(ADMIN)
def class_search(request):
    query = request.GET.get("q", "").strip()
    qs = ClassOffering.objects.select_related("subject").prefetch_related("sections")
    if query:
        qs = qs.filter(Q(subject__code__icontains=query) | Q(subject__title__icontains=query))
    options = [(c.pk, str(c)) for c in qs.order_by("-semester__academic_year__start_year", "subject__code")[:20]]
    return render(request, "partials/_searchable_select_options.html", {"options": options})
