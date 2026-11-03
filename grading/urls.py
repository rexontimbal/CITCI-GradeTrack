from django.urls import path

from . import views

app_name = "grading"

urlpatterns = [
    # Admin — Grading Templates
    path("templates/", views.GradingTemplateListView.as_view(), name="templates"),
    path("templates/create/", views.GradingTemplateFormView.as_view(), name="template_create"),
    path("templates/<int:pk>/edit/", views.GradingTemplateFormView.as_view(), name="template_edit"),
    path("templates/<int:pk>/delete/", views.GradingTemplateDeleteView.as_view(), name="template_delete"),
    path(
        "templates/<int:pk>/toggle-active/",
        views.GradingTemplateToggleActiveView.as_view(),
        name="template_toggle_active",
    ),
    path("templates/<int:pk>/set-default/", views.template_set_default, name="template_set_default"),
    path("templates/<int:pk>/components/", views.template_components, name="template_components"),
    path(
        "templates/<int:template_pk>/components/create/",
        views.GradingComponentFormView.as_view(),
        name="component_create",
    ),
    path("components/<int:pk>/edit/", views.GradingComponentFormView.as_view(), name="component_edit"),
    path("components/<int:pk>/delete/", views.GradingComponentDeleteView.as_view(), name="component_delete"),
    # Class grading page
    path("classes/<int:pk>/", views.class_grading, name="class_grading"),
    path("classes/<int:pk>/change-template/", views.class_change_template, name="class_change_template"),
    # Setup tab
    path("classes/<int:pk>/components/save/", views.class_components_save, name="class_components_save"),
    path("classes/<int:class_pk>/items/create/", views.AssessmentItemFormView.as_view(), name="item_create"),
    path("items/<int:pk>/edit/", views.AssessmentItemFormView.as_view(), name="item_edit"),
    path("items/<int:pk>/delete/", views.item_delete, name="item_delete"),
    # Class Record tab
    path("cells/<int:roster_entry_pk>/<int:item_pk>/save/", views.save_cell, name="save_cell"),
    path("items/<int:pk>/fill-column/", views.fill_column, name="fill_column"),
    path("roster-entries/<int:pk>/mark-incomplete/", views.mark_incomplete, name="mark_incomplete"),
    # Other roles (kept from the placeholder phase)
    path("my-grades/", views.my_grades, name="my_grades"),
    path("my-progress/", views.my_progress, name="my_progress"),
]
