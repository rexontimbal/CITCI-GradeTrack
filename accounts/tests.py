import io

import openpyxl
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from academics.models import AcademicYear, Program, Section

from .models import User
from .views import user_toggle_active


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
        self.client.force_login(User.objects.get(username="newbie"))
        response = self.client.get(reverse("dashboard:home"))
        self.assertRedirects(response, reverse("accounts:force_password_change"))


class RoleMenuVisibilityTests(TestCase):
    def setUp(self):
        self.admin = make_user(User.Role.ADMIN, "admin1")
        self.student = make_user(User.Role.STUDENT, "stud2")

    def test_admin_dashboard_shows_admin_only_menu_item(self):
        self.client.force_login(User.objects.get(username="admin1"))
        response = self.client.get(reverse("dashboard:home"))
        self.assertContains(response, "Users")
        self.assertContains(response, "Forecast Model")

    def test_student_dashboard_does_not_show_admin_menu_item(self):
        self.client.force_login(User.objects.get(username="stud2"))
        response = self.client.get(reverse("dashboard:home"))
        self.assertNotContains(response, "Forecast Model")
        self.assertContains(response, "My Grades")


class RoleAccessDeniedTests(TestCase):
    def setUp(self):
        self.student = make_user(User.Role.STUDENT, "stud3")

    def test_student_gets_403_on_admin_only_page(self):
        self.client.force_login(User.objects.get(username="stud3"))
        response = self.client.get(reverse("accounts:users"))
        self.assertEqual(response.status_code, 403)

    def test_student_gets_403_on_forecast_model_page(self):
        self.client.force_login(User.objects.get(username="stud3"))
        response = self.client.get(reverse("forecasting:model"))
        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_redirected_to_login(self):
        response = self.client.get(reverse("accounts:users"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)


class ForcedPasswordChangeAfterAdminActionTests(TestCase):
    """New/reset accounts must be forced through the password-change screen
    on their very next login, same as the Phase 1 forced-first-login flow."""

    def setUp(self):
        self.admin = make_user(User.Role.ADMIN, "admin_create")
        self.client.force_login(self.admin)

    def test_admin_created_user_must_change_password_on_first_login(self):
        response = self.client.post(
            reverse("accounts:user_create"),
            {
                "role": User.Role.INSTRUCTOR,
                "id_number": "EMP-9001",
                "last_name": "Reyes",
                "first_name": "Ana",
                "middle_name": "",
                "email": "",
                "username": "reyesa",
            },
        )
        self.assertEqual(response.status_code, 200)
        new_user = User.objects.get(username="reyesa")
        self.assertTrue(new_user.must_change_password)

        self.client.logout()
        dashboard_response = self.client.get(reverse("dashboard:home"))
        self.client.force_login(new_user)
        dashboard_response = self.client.get(reverse("dashboard:home"))
        self.assertRedirects(dashboard_response, reverse("accounts:force_password_change"))

    def test_reset_password_forces_change_on_next_login(self):
        target = make_user(User.Role.INSTRUCTOR, "needs_reset")
        self.assertFalse(target.must_change_password)

        response = self.client.post(reverse("accounts:user_reset_password", args=[target.pk]))
        self.assertEqual(response.status_code, 200)
        target.refresh_from_db()
        self.assertTrue(target.must_change_password)

        self.client.logout()
        self.client.force_login(target)
        dashboard_response = self.client.get(reverse("dashboard:home"))
        self.assertRedirects(dashboard_response, reverse("accounts:force_password_change"))


class ProfileEditRestrictionTests(TestCase):
    """Students (and every non-admin role) can only ever edit their own
    email from the Profile page — name/ID/role changes are admin-only, so
    the ProfileEmailForm simply has no fields for them."""

    def setUp(self):
        self.student = make_user(User.Role.STUDENT, "profile_stud", first_name="Original", id_number="2026-5001")
        self.client.force_login(self.student)

    def test_student_can_change_own_email(self):
        response = self.client.post(reverse("accounts:profile"), {"email": "new@example.com"})
        self.assertRedirects(response, reverse("accounts:profile"))
        self.student.refresh_from_db()
        self.assertEqual(self.student.email, "new@example.com")

    def test_student_cannot_change_own_name_or_id_number(self):
        self.client.post(
            reverse("accounts:profile"),
            {"email": "new2@example.com", "first_name": "Hacked", "id_number": "9999-9999"},
        )
        self.student.refresh_from_db()
        self.assertEqual(self.student.first_name, "Original")
        self.assertEqual(self.student.id_number, "2026-5001")


class SelfAndLastAdminDeactivationGuardTests(TestCase):
    def setUp(self):
        self.admin = make_user(User.Role.ADMIN, "sole_admin")
        self.client.force_login(self.admin)

    def test_admin_cannot_deactivate_own_account(self):
        response = self.client.post(reverse("accounts:user_toggle_active", args=[self.admin.pk]))
        self.assertEqual(response.status_code, 403)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_cannot_deactivate_the_last_active_admin(self):
        # Django logs an admin out automatically the moment their own
        # is_active flips to False (ModelBackend.get_user rejects them on
        # the next request), so the only way to exercise this guard is to
        # call the view directly with an in-memory request — a real HTTP
        # round trip can never reach this branch through a live session.
        other_admin = make_user(User.Role.ADMIN, "other_admin")
        self.admin.is_active = False
        self.admin.save(update_fields=["is_active"])

        request = RequestFactory().post(reverse("accounts:user_toggle_active", args=[other_admin.pk]))
        request.user = self.admin

        with self.assertRaises(PermissionDenied):
            user_toggle_active(request, pk=other_admin.pk)

        other_admin.refresh_from_db()
        self.assertTrue(other_admin.is_active)

    def test_can_deactivate_an_admin_when_another_remains_active(self):
        second_admin = make_user(User.Role.ADMIN, "second_admin")
        response = self.client.post(reverse("accounts:user_toggle_active", args=[second_admin.pk]))
        self.assertEqual(response.status_code, 204)
        second_admin.refresh_from_db()
        self.assertFalse(second_admin.is_active)


def _xlsx_upload(filename, rows):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return SimpleUploadedFile(
        filename, buffer.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


class BulkImportStudentsTests(TestCase):
    def setUp(self):
        self.admin = make_user(User.Role.ADMIN, "import_admin")
        self.client.force_login(self.admin)
        self.academic_year = AcademicYear.objects.create(start_year=2026)
        self.program = Program.objects.create(code="BSIT", name="BS Information Technology")
        Section.objects.create(program=self.program, academic_year=self.academic_year, year_level=1, name="A")
        from academics.models import Semester, Term

        Semester.objects.create(academic_year=self.academic_year, term=Term.FIRST, is_active=True)

    def _upload(self, rows):
        header = ["ID Number", "Last Name", "First Name", "Middle Name", "Program Code", "Major Code", "Year Level", "Email"]
        upload = _xlsx_upload("students.xlsx", [header, *rows])
        return self.client.post(reverse("accounts:import_students"), {"file": upload})

    def test_existing_id_number_is_updated_not_duplicated(self):
        make_user(User.Role.STUDENT, "2026-0001", id_number="2026-0001", last_name="OldName")
        response = self._upload([["2026-0001", "NewName", "Juan", "", "BSIT", "", "1", ""]])
        self.assertContains(response, "update")
        self.assertEqual(User.objects.filter(id_number="2026-0001").count(), 1)

        self.client.post(reverse("accounts:import_students_confirm"))
        self.assertEqual(User.objects.filter(id_number="2026-0001").count(), 1)
        self.assertEqual(User.objects.get(id_number="2026-0001").last_name, "NewName")

    def test_invalid_row_is_rejected_with_a_reason(self):
        response = self._upload([["2026-0002", "Santos", "", "", "BSIT", "", "1", ""]])
        self.assertContains(response, "Missing ID Number, Last Name, First Name, or Program Code.")

    def test_invalid_program_code_is_rejected_with_a_reason(self):
        response = self._upload([["2026-0003", "Santos", "Maria", "", "NOPE", "", "1", ""]])
        self.assertContains(response, "No program with code")


class LoginLockoutTests(TestCase):
    def setUp(self):
        self.student = make_user(User.Role.STUDENT, "lockout_stud")

    def test_account_locks_out_after_five_failed_logins(self):
        for _ in range(5):
            self.client.post(reverse("accounts:login"), {"username": "lockout_stud", "password": "wrong"})

        response = self.client.post(
            reverse("accounts:login"), {"username": "lockout_stud", "password": "pw12345!"}
        )
        self.assertEqual(response.status_code, 429)

    def test_admin_unlock_clears_the_lockout(self):
        for _ in range(5):
            self.client.post(reverse("accounts:login"), {"username": "lockout_stud", "password": "wrong"})

        admin = make_user(User.Role.ADMIN, "unlock_admin")
        self.client.force_login(admin)
        self.client.post(reverse("accounts:user_unlock", args=[self.student.pk]))
        self.client.logout()

        response = self.client.post(
            reverse("accounts:login"), {"username": "lockout_stud", "password": "pw12345!"}
        )
        self.assertRedirects(response, reverse("dashboard:home"))


class SearchableSelectSearchTests(TestCase):
    def setUp(self):
        self.admin = make_user(User.Role.ADMIN, "search_admin")
        self.client.force_login(self.admin)
        make_user(User.Role.INSTRUCTOR, "garibay_j", first_name="Juan", last_name="Garibay")
        make_user(User.Role.INSTRUCTOR, "santos_m", first_name="Maria", last_name="Santos")

    def test_instructor_search_returns_only_matching_results(self):
        response = self.client.get(reverse("academics:instructor_search"), {"q": "Garibay"})
        self.assertContains(response, "Garibay")
        self.assertNotContains(response, "Santos")
