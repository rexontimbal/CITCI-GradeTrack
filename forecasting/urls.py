from django.urls import path

from . import views

app_name = "forecasting"

urlpatterns = [
    path("model/", views.model, name="model"),
    path("model/<int:pk>/activate/", views.model_activate, name="model_activate"),
    path("model/<int:pk>/report.pdf", views.model_report_pdf, name="model_report_pdf"),
    path("historical/", views.historical, name="historical"),
    path("historical/import/", views.historical_import_upload, name="historical_import"),
    path("historical/import/confirm/", views.historical_import_confirm, name="historical_import_confirm"),
    path("historical/<int:pk>/delete/", views.historical_delete, name="historical_delete"),
    path("historical/export-live/", views.historical_export_live, name="historical_export_live"),
    path("at-risk/", views.at_risk, name="at_risk"),
    path("at-risk/export.xlsx", views.at_risk_export, name="at_risk_export"),
    path("classes/<int:pk>/recompute/", views.recompute_class, name="recompute_class"),
    path("programs/<int:pk>/recompute/", views.recompute_program, name="recompute_program"),
    path("roster-entries/<int:pk>/forecast/", views.forecast_detail, name="forecast_detail"),
    path("roster-entries/<int:pk>/interventions/create/", views.intervention_create, name="intervention_create"),
]
