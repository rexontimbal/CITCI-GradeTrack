from django.urls import path

from . import views

app_name = "academics"

urlpatterns = [
    # Academic Years & Semesters
    path("terms/", views.terms, name="terms"),
    path("terms/academic-years/table/", views.academic_years_table, name="academic_years_table"),
    path("terms/semesters/table/", views.semesters_table, name="semesters_table"),
    path("terms/academic-years/create/", views.AcademicYearFormView.as_view(), name="academic_year_create"),
    path("terms/academic-years/<int:pk>/edit/", views.AcademicYearFormView.as_view(), name="academic_year_edit"),
    path("terms/academic-years/<int:pk>/delete/", views.AcademicYearDeleteView.as_view(), name="academic_year_delete"),
    path("terms/semesters/create/", views.SemesterFormView.as_view(), name="semester_create"),
    path("terms/semesters/<int:pk>/edit/", views.SemesterFormView.as_view(), name="semester_edit"),
    path("terms/semesters/<int:pk>/delete/", views.SemesterDeleteView.as_view(), name="semester_delete"),
    path("terms/semesters/<int:pk>/set-active/", views.SemesterSetActiveView.as_view(), name="semester_set_active"),

    # Programs
    path("programs/", views.ProgramListView.as_view(), name="programs"),
    path("programs/create/", views.ProgramFormView.as_view(), name="program_create"),
    path("programs/<int:pk>/edit/", views.ProgramFormView.as_view(), name="program_edit"),
    path("programs/<int:pk>/delete/", views.ProgramDeleteView.as_view(), name="program_delete"),
    path("programs/<int:pk>/toggle-active/", views.ProgramToggleActiveView.as_view(), name="program_toggle_active"),

    # Sections
    path("sections/", views.SectionListView.as_view(), name="sections"),
    path("sections/create/", views.SectionFormView.as_view(), name="section_create"),
    path("sections/<int:pk>/edit/", views.SectionFormView.as_view(), name="section_edit"),
    path("sections/<int:pk>/delete/", views.SectionDeleteView.as_view(), name="section_delete"),

    # Subjects
    path("subjects/", views.SubjectListView.as_view(), name="subjects"),
    path("subjects/create/", views.SubjectFormView.as_view(), name="subject_create"),
    path("subjects/<int:pk>/edit/", views.SubjectFormView.as_view(), name="subject_edit"),
    path("subjects/<int:pk>/delete/", views.SubjectDeleteView.as_view(), name="subject_delete"),
    path("subjects/<int:pk>/toggle-active/", views.SubjectToggleActiveView.as_view(), name="subject_toggle_active"),

    # Classes (admin CRUD)
    path("classes/", views.ClassListView.as_view(), name="classes"),
    path("classes/create/", views.ClassFormView.as_view(), name="class_create"),
    path("classes/<int:pk>/edit/", views.ClassFormView.as_view(), name="class_edit"),
    path("classes/<int:pk>/delete/", views.ClassDeleteView.as_view(), name="class_delete"),
    path("classes/<int:pk>/toggle-active/", views.ClassToggleActiveView.as_view(), name="class_toggle_active"),
    path("classes/<int:pk>/roster/", views.class_roster, name="class_roster"),

    # Read-only, role-specific class lists
    path("my-classes/", views.my_classes, name="my_classes"),
    path("program-head/classes/", views.program_head_classes, name="program_head_classes"),

    # Students (read-only, admin)
    path("students/", views.StudentListView.as_view(), name="students"),

    # Enrollment (admin)
    path("enrollment/", views.enrollment_home, name="enrollment"),
    path("enrollment/<int:pk>/enroll-section/", views.enrollment_enroll_section, name="enrollment_enroll_section"),
    path("enrollment/<int:pk>/add-students/", views.enrollment_add_students_form, name="enrollment_add_students_form"),
    path(
        "enrollment/<int:pk>/add-students/submit/",
        views.enrollment_add_students_submit,
        name="enrollment_add_students_submit",
    ),
    path("enrollment/drop/<int:pk>/", views.enrollment_drop, name="enrollment_drop"),
    path("enrollment/re-enroll/<int:pk>/", views.enrollment_reenroll, name="enrollment_reenroll"),
]
