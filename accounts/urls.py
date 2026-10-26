from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("profile/", views.profile, name="profile"),
    path("help/", views.help_page, name="help"),
    path("password/change/", views.force_password_change, name="force_password_change"),
    path("privacy-consent/", views.privacy_consent, name="privacy_consent"),

    path("users/", views.UserListView.as_view(), name="users"),
    path("users/create/", views.user_form, name="user_create"),
    path("users/<int:pk>/edit/", views.user_form, name="user_edit"),
    path("users/<int:pk>/reset-password/", views.user_reset_password, name="user_reset_password"),
    path("users/<int:pk>/toggle-active/", views.user_toggle_active, name="user_toggle_active"),
    path("users/<int:pk>/unlock/", views.user_unlock, name="user_unlock"),

    path("users/import/students/template/", views.import_students_template, name="import_students_template"),
    path("users/import/students/", views.import_students, name="import_students"),
    path("users/import/students/confirm/", views.import_students_confirm, name="import_students_confirm"),
    path("users/import/instructors/template/", views.import_instructors_template, name="import_instructors_template"),
    path("users/import/instructors/", views.import_instructors, name="import_instructors"),
    path("users/import/instructors/confirm/", views.import_instructors_confirm, name="import_instructors_confirm"),
]
