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
    path("users/", views.users, name="users"),
]
