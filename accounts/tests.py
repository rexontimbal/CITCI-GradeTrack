from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import User


def make_user(role, username, **extra):
    user = User.objects.create_user(username=username, password="pw12345!", role=role, **extra)
    user.must_change_password = False
    user.privacy_consent_at = timezone.now()
    user.save()
    return user


class LoginTests(TestCase):
    def setUp(self):
        self.student = make_user(User.Role.STUDENT, "stud1")

    def test_login_page_loads(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CITCI GradeTrack")

    def test_login_succeeds_and_redirects_to_dashboard(self):
        response = self.client.post(
            reverse("accounts:login"), {"username": "stud1", "password": "pw12345!"}
        )
        self.assertRedirects(response, reverse("dashboard:home"))

    def test_login_fails_with_wrong_password(self):
        response = self.client.post(
            reverse("accounts:login"), {"username": "stud1", "password": "wrong"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)


class ForcedFirstLoginStepsTests(TestCase):
    def test_new_account_is_redirected_to_password_change(self):
        User.objects.create_user(username="newbie", password="pw12345!", role=User.Role.STUDENT)
        self.client.login(username="newbie", password="pw12345!")
        response = self.client.get(reverse("dashboard:home"))
        self.assertRedirects(response, reverse("accounts:force_password_change"))


class RoleMenuVisibilityTests(TestCase):
    def setUp(self):
        self.admin = make_user(User.Role.ADMIN, "admin1")
        self.student = make_user(User.Role.STUDENT, "stud2")

    def test_admin_dashboard_shows_admin_only_menu_item(self):
        self.client.login(username="admin1", password="pw12345!")
        response = self.client.get(reverse("dashboard:home"))
        self.assertContains(response, "Users")
        self.assertContains(response, "Forecast Model")

    def test_student_dashboard_does_not_show_admin_menu_item(self):
        self.client.login(username="stud2", password="pw12345!")
        response = self.client.get(reverse("dashboard:home"))
        self.assertNotContains(response, "Forecast Model")
        self.assertContains(response, "My Grades")


class RoleAccessDeniedTests(TestCase):
    def setUp(self):
        self.student = make_user(User.Role.STUDENT, "stud3")

    def test_student_gets_403_on_admin_only_page(self):
        self.client.login(username="stud3", password="pw12345!")
        response = self.client.get(reverse("accounts:users"))
        self.assertEqual(response.status_code, 403)

    def test_student_gets_403_on_forecast_model_page(self):
        self.client.login(username="stud3", password="pw12345!")
        response = self.client.get(reverse("forecasting:model"))
        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_redirected_to_login(self):
        response = self.client.get(reverse("accounts:users"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)
