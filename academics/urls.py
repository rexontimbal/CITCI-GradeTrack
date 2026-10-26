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

    # Majors
    path("majors/", views.MajorListView.as_view(), name="majors"),
    path("majors/create/", views.MajorFormView.as_view(), name="major_create"),
    path("majors/<int:pk>/edit/", views.MajorFormView.as_view(), name="major_edit"),
    path("majors/<int:pk>/delete/", views.MajorDeleteView.as_view(), name="major_delete"),

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

    # Class Lists (admin) — CITCI GradeTrack does not handle enrollment;
    # this only manages each class's official roster for grading.
    path("class-lists/", views.class_lists_home, name="class_lists"),
    path("class-lists/<int:pk>/add-section/", views.class_list_add_section, name="class_list_add_section"),
    path("class-lists/<int:pk>/add-students/", views.class_list_add_students_form, name="class_list_add_students_form"),
    path(
        "class-lists/<int:pk>/add-students/submit/",
        views.class_list_add_students_submit,
        name="class_list_add_students_submit",
    ),
    path("class-lists/mark-dropped/<int:pk>/", views.class_list_mark_dropped, name="class_list_mark_dropped"),
    path("class-lists/restore/<int:pk>/", views.class_list_restore, name="class_list_restore"),

    # Import class list (shared by admin's Class Lists page and an
    # instructor's own class roster)
    path("class-lists/import/template/", views.class_list_import_template, name="class_list_import_template"),
    path("classes/<int:pk>/import/", views.class_list_import_upload, name="class_list_import_upload"),
    path("classes/<int:pk>/import/confirm/", views.class_list_import_confirm, name="class_list_import_confirm"),
]
