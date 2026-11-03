from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.index, name="index"),
    path("settings/", views.settings_edit, name="settings"),
    path("submission-status/", views.submission_status, name="submission_status"),
    path("class-performance/", views.class_performance, name="class_performance"),
    path("failing-inc/", views.failing_inc, name="failing_inc"),
    path("programs/<int:pk>/grade-report.pdf", views.program_grade_report_pdf, name="program_grade_report_pdf"),
    path("sheets/<int:pk>/pdf/", views.grade_sheet_pdf, name="grade_sheet_pdf"),
    path("classes/<int:pk>/class-record.xlsx", views.class_record_excel, name="class_record_excel"),
    path("classes/<int:pk>/import/", views.class_record_import, name="class_record_import"),
    path("classes/<int:pk>/import/confirm/", views.class_record_import_confirm, name="class_record_import_confirm"),
]
