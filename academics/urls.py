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
    path("sections/", views.sections_home, name="sections"),
    path("sections/create/", views.SectionFormView.as_view(), name="section_create"),
    path("sections/<int:pk>/edit/", views.SectionFormView.as_view(), name="section_edit"),
    path("sections/<int:pk>/delete/", views.SectionDeleteView.as_view(), name="section_delete"),
    path("sections/<int:pk>/students/", views.section_students, name="section_students"),
    path("sections/<int:pk>/students/move/", views.section_students_move, name="section_students_move"),

    # Sections (Program Head — scoped to their own program/major)
    path("my-program/sections/", views.sections_home, name="ph_sections"),
    path("my-program/sections/create/", views.ph_section_create, name="ph_section_create"),
    path("my-program/sections/<int:pk>/edit/", views.ph_section_edit, name="ph_section_edit"),
    path("my-program/sections/<int:pk>/delete/", views.ph_section_delete, name="ph_section_delete"),

    # Subjects — prospectus-style, shared view logic for admin (every
    # program/major) and Program Head (scoped). ph_subjects is a thin
    # alias so the Program Head sidebar keeps its own URL name.
    path("subjects/", views.subjects_home, name="subjects"),
    path("subjects/add/", views.subject_add, name="subject_add"),
    path("subjects/<int:pk>/edit/", views.subject_edit, name="subject_edit"),
    path("subjects/<int:pk>/correct-code/", views.subject_correct_code, name="subject_correct_code"),
    path("subjects/<int:pk>/toggle-active/", views.SubjectToggleActiveView.as_view(), name="subject_toggle_active"),
    path(
        "curriculum-entries/<int:pk>/remove/",
        views.subject_remove_from_curriculum,
        name="subject_remove_from_curriculum",
    ),
    path("search/subjects/", views.subject_search, name="subject_search"),

    # Subject Offering — check a box next to a curriculum subject to
    # "offer" it for a semester; auto-creates classes + fills rosters.
    path("subjects/offer/preview/", views.subject_offering_preview, name="subject_offering_preview"),
    path("subjects/offer/adhoc/", views.subject_offering_adhoc, name="subject_offering_adhoc"),
    path("subjects/offer/commit/", views.subject_offering_commit, name="subject_offering_commit"),
    path("subjects/offerings/<int:pk>/withdraw/", views.subject_offering_withdraw, name="subject_offering_withdraw"),
    path("subjects/offerings/<int:pk>/manage/", views.subject_offering_manage, name="subject_offering_manage"),
    path("subjects/offerings/bulk-withdraw/", views.subject_offering_bulk_withdraw, name="subject_offering_bulk_withdraw"),

    # Subjects (Program Head — same prospectus view, scoped by default)
    path("my-program/subjects/", views.subjects_home, name="ph_subjects"),

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
    path("program-head/classes/create/", views.ph_class_create, name="ph_class_create"),
    path("program-head/classes/<int:pk>/edit/", views.ph_class_edit, name="ph_class_edit"),
    path("program-head/classes/join/", views.ph_class_join, name="ph_class_join"),
    path("program-head/classes/<int:pk>/leave/", views.ph_class_leave, name="ph_class_leave"),

    # Teaching assignment (Program Head; Admin as a logged override)
    path("classes/<int:pk>/assign-instructor/", views.class_assign_instructor, name="class_assign_instructor"),
    path("classes/bulk-assign-instructor/", views.class_bulk_assign_instructor, name="class_bulk_assign_instructor"),
    path("classes/<int:pk>/update-field/", views.class_update_field, name="class_update_field"),
    path("teaching-loads/", views.teaching_loads, name="teaching_loads"),
    path("teaching-loads/export.xlsx", views.teaching_loads_export, name="teaching_loads_export"),

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

    # Import Class Offerings + Copy classes from previous semester (admin)
    path("offerings/import/template/", views.offerings_import_template, name="offerings_import_template"),
    path("offerings/import/", views.offerings_import, name="offerings_import"),
    path("offerings/import/upload/", views.offerings_import_upload, name="offerings_import_upload"),
    path("offerings/import/confirm/", views.offerings_import_confirm, name="offerings_import_confirm"),
    path("offerings/copy/", views.offerings_copy_previous, name="offerings_copy_previous"),
    path("offerings/copy/confirm/", views.offerings_copy_previous_confirm, name="offerings_copy_previous_confirm"),

    # New Academic Year wizard (admin)
    path("ay-wizard/step1/", views.ay_wizard_step1, name="ay_wizard_step1"),
    path("ay-wizard/step2/", views.ay_wizard_step2, name="ay_wizard_step2"),
    path("ay-wizard/step3/", views.ay_wizard_step3, name="ay_wizard_step3"),
    path("ay-wizard/step4/", views.ay_wizard_step4, name="ay_wizard_step4"),

    # Searchable-select endpoints
    path("search/instructors/", views.instructor_search, name="instructor_search"),
    path("search/classes/", views.class_search, name="class_search"),
]
