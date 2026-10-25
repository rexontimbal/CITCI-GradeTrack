from datetime import date

from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render
from django.views import View

from accounts.decorators import role_required
from accounts.mixins import RoleRequiredMixin
from accounts.models import User
from core.crud import EntityDeleteView, EntityFormView, EntityListView, ToggleActiveView, trigger_response
from core.htmx import is_htmx

from .forms import AcademicYearForm, ClassOfferingForm, ProgramForm, SectionForm, SemesterForm, SubjectForm
from .models import AcademicYear, ClassOffering, Enrollment, Program, Section, Semester, StudentProfile, Subject

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
    protect_message = "This program has sections, subjects, or students using it."


class ProgramToggleActiveView(RoleRequiredMixin, ToggleActiveView):
    allowed_roles = (ADMIN,)
    model = Program
    refresh_event = "refreshPrograms"


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
        qs = qs.select_related("program", "academic_year")
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
    protect_message = "This section has classes or enrolled students using it."


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
        qs = qs.select_related("program")
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
# Classes (ClassOffering) — admin CRUD
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
        qs = qs.select_related("subject", "section", "section__program", "semester", "instructor").annotate(
            enrolled=Count("enrollments", filter=Q(enrollments__status=Enrollment.Status.ENROLLED))
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
            qs = qs.filter(section__program_id=program)

        instructor = request.GET.get("instructor")
        if instructor:
            qs = qs.filter(instructor_id=instructor)

        return qs

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
    protect_message = "This class has enrollments using it."


class ClassToggleActiveView(RoleRequiredMixin, ToggleActiveView):
    allowed_roles = (ADMIN,)
    model = ClassOffering
    refresh_event = "refreshClasses"


# ---------------------------------------------------------------------------
# Class roster (read-only) — shared by admin, the owning program head, and
# the assigned instructor. Object-level check: wrong program head/instructor
# gets 403, never just a redirect.
# ---------------------------------------------------------------------------


@role_required(ADMIN, PROGRAM_HEAD, INSTRUCTOR)
def class_roster(request, pk):
    class_offering = get_object_or_404(
        ClassOffering.objects.select_related("subject", "section", "section__program", "semester", "instructor"),
        pk=pk,
    )
    user = request.user
    if user.is_program_head and class_offering.section.program.program_head_id != user.id:
        raise PermissionDenied("This class is not under your program.")
    if user.is_instructor and class_offering.instructor_id != user.id:
        raise PermissionDenied("This class is not assigned to you.")

    enrollments = class_offering.enrollments.select_related("student").order_by(
        "student__last_name", "student__first_name"
    )
    return render(
        request,
        "academics/class_roster.html",
        {
            "page_title": f"Roster — {class_offering}",
            "class_offering": class_offering,
            "enrollments": enrollments,
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
            .select_related("subject", "section")
            .annotate(enrolled=Count("enrollments", filter=Q(enrollments__status=Enrollment.Status.ENROLLED)))
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
            ClassOffering.objects.filter(section__program__program_head=request.user, semester=active)
            .select_related("subject", "section", "instructor")
            .annotate(enrolled=Count("enrollments", filter=Q(enrollments__status=Enrollment.Status.ENROLLED)))
        )
    return render(
        request,
        "academics/program_head_classes.html",
        {"page_title": "Classes", "classes": qs, "active_semester_set": bool(active)},
    )


# ---------------------------------------------------------------------------
# Students (read-only list, reached from the admin "Users" menu item until
# full user management is built in a later phase)
# ---------------------------------------------------------------------------


class StudentListView(RoleRequiredMixin, EntityListView):
    allowed_roles = (ADMIN,)
    model = StudentProfile
    list_template = "academics/students.html"
    table_template = "academics/_students_table.html"
    table_id = "students-table"
    page_title = "Students"
    search_fields = ["user__first_name__icontains", "user__last_name__icontains", "user__id_number__icontains"]
    refresh_event = "refreshStudents"

    def apply_filters(self, request, qs):
        qs = qs.select_related("user", "program", "section")
        program = request.GET.get("program")
        year_level = request.GET.get("year_level")
        section = request.GET.get("section")
        if program:
            qs = qs.filter(program_id=program)
        if year_level:
            qs = qs.filter(year_level=year_level)
        if section:
            qs = qs.filter(section_id=section)
        return qs

    def get_extra_context(self, request):
        return {"programs": Program.objects.all(), "sections": Section.objects.select_related("program")}


# ---------------------------------------------------------------------------
# Enrollment (admin) — pick a class, manage its roster
# ---------------------------------------------------------------------------


def _roster_context(class_offering):
    enrollments = class_offering.enrollments.select_related("student").order_by(
        "status", "student__last_name", "student__first_name"
    )
    return {"class_offering": class_offering, "enrollments": enrollments}


@role_required(ADMIN)
def enrollment_home(request):
    active = Semester.objects.filter(is_active=True).first()
    classes = ClassOffering.objects.select_related("subject", "section").order_by(
        "-semester__academic_year__start_year", "subject__code"
    )
    class_id = request.GET.get("class")
    class_offering = None
    if class_id:
        class_offering = get_object_or_404(ClassOffering, pk=class_id)
    elif active:
        class_offering = classes.filter(semester=active).first()

    context = {
        "page_title": "Enrollment",
        "classes": classes,
        "selected_class": class_offering,
    }
    if class_offering:
        context.update(_roster_context(class_offering))

    if is_htmx(request):
        return render(request, "academics/_enrollment_roster.html", context)
    return render(request, "academics/enrollment.html", context)


@role_required(ADMIN)
def enrollment_enroll_section(request, pk):
    class_offering = get_object_or_404(ClassOffering, pk=pk)
    students = User.objects.filter(role=User.Role.STUDENT, student_profile__section=class_offering.section)
    enrolled_count, skipped_count = 0, 0
    for student in students:
        _, created = Enrollment.objects.get_or_create(
            student=student, class_offering=class_offering, defaults={"status": Enrollment.Status.ENROLLED}
        )
        if created:
            enrolled_count += 1
        else:
            skipped_count += 1

    context = _roster_context(class_offering)
    context["summary"] = f"{enrolled_count} enrolled, {skipped_count} already enrolled (skipped)."
    return render(request, "academics/_enrollment_roster.html", context)


@role_required(ADMIN)
def enrollment_add_students_form(request, pk):
    class_offering = get_object_or_404(ClassOffering, pk=pk)
    already_enrolled_ids = class_offering.enrollments.values_list("student_id", flat=True)
    available_students = (
        User.objects.filter(role=User.Role.STUDENT)
        .exclude(id__in=already_enrolled_ids)
        .order_by("last_name", "first_name")
    )
    return render(
        request,
        "academics/_enrollment_add_students_modal.html",
        {"class_offering": class_offering, "available_students": available_students},
    )


@role_required(ADMIN)
def enrollment_add_students_submit(request, pk):
    class_offering = get_object_or_404(ClassOffering, pk=pk)
    student_ids = request.POST.getlist("student_ids")
    for student_id in student_ids:
        Enrollment.objects.get_or_create(
            student_id=student_id, class_offering=class_offering, defaults={"status": Enrollment.Status.ENROLLED}
        )
    return trigger_response("refreshRoster")


@role_required(ADMIN)
def enrollment_drop(request, pk):
    enrollment = get_object_or_404(Enrollment, pk=pk)
    enrollment.status = Enrollment.Status.DROPPED
    enrollment.date_dropped = date.today()
    enrollment.save(update_fields=["status", "date_dropped"])
    context = _roster_context(enrollment.class_offering)
    return render(request, "academics/_enrollment_roster.html", context)


@role_required(ADMIN)
def enrollment_reenroll(request, pk):
    enrollment = get_object_or_404(Enrollment, pk=pk)
    enrollment.status = Enrollment.Status.ENROLLED
    enrollment.date_dropped = None
    enrollment.save(update_fields=["status", "date_dropped"])
    context = _roster_context(enrollment.class_offering)
    return render(request, "academics/_enrollment_roster.html", context)
