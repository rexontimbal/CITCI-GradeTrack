import json
import os
from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

from .models import (
    AcademicYear,
    ClassJoinRequest,
    ClassOffering,
    ClassRosterEntry,
    CurriculumEntry,
    Major,
    Program,
    Section,
    Semester,
    SemesterStatus,
    StudentProfile,
    Subject,
    SubjectOffering,
    Term,
)


def make_user(role, username, **extra):
    user = User.objects.create_user(username=username, password="pw12345!", role=role, **extra)
    user.must_change_password = False
    user.privacy_consent_at = timezone.now()
    user.save()
    return user


class SingleActiveSemesterTests(TestCase):
    def setUp(self):
        self.academic_year = AcademicYear.objects.create(start_year=2026)

    def test_only_one_semester_can_be_active(self):
        first = Semester.objects.create(academic_year=self.academic_year, term=Term.FIRST, is_active=True)
        second = Semester.objects.create(academic_year=self.academic_year, term=Term.SECOND, is_active=True)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertTrue(second.is_active)
        self.assertEqual(Semester.objects.filter(is_active=True).count(), 1)

    def test_activating_a_semester_deactivates_the_previous_one_on_update(self):
        first = Semester.objects.create(academic_year=self.academic_year, term=Term.FIRST, is_active=True)
        second = Semester.objects.create(academic_year=self.academic_year, term=Term.SECOND, is_active=False)

        second.is_active = True
        second.save()

        first.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertEqual(Semester.objects.filter(is_active=True).count(), 1)


class SubmissionDeadlineFormTests(TestCase):
    def test_admin_can_set_and_clear_submission_deadline(self):
        from .forms import SemesterForm

        ay = AcademicYear.objects.create(start_year=2026)
        form = SemesterForm(
            data={
                "academic_year": ay.pk, "term": Term.FIRST,
                "submission_deadline": "2027-03-15T17:00",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        semester = form.save()
        self.assertIsNotNone(semester.submission_deadline)

        form2 = SemesterForm(
            data={"academic_year": ay.pk, "term": Term.FIRST, "submission_deadline": ""}, instance=semester
        )
        self.assertTrue(form2.is_valid(), form2.errors)
        semester2 = form2.save()
        self.assertIsNone(semester2.submission_deadline)


class SemesterDateValidationTests(TestCase):
    """SemesterForm.clean() rules: end after start, both dates within the
    academic year's two calendar years, no overlap with another semester
    of the same A.Y., and a non-blocking duration warning."""

    def setUp(self):
        self.ay = AcademicYear.objects.create(start_year=2027)  # A.Y. 2027-2028

    def _form(self, **overrides):
        from .forms import SemesterForm

        data = {"academic_year": self.ay.pk, "term": Term.FIRST}
        data.update(overrides)
        return SemesterForm(data=data)

    def test_end_before_start_is_rejected(self):
        form = self._form(start_date="2027-08-01", end_date="2027-07-01")
        self.assertFalse(form.is_valid())
        self.assertIn("end_date", form.errors)

    def test_end_equal_to_start_is_rejected(self):
        form = self._form(start_date="2027-08-01", end_date="2027-08-01")
        self.assertFalse(form.is_valid())
        self.assertIn("end_date", form.errors)

    def test_dates_outside_academic_year_are_rejected(self):
        form = self._form(start_date="2026-08-01", end_date="2026-12-01")
        self.assertFalse(form.is_valid())
        self.assertIn("start_date", form.errors)
        self.assertIn("end_date", form.errors)

    def test_dates_within_academic_year_are_accepted(self):
        form = self._form(start_date="2027-08-01", end_date="2027-12-15")
        self.assertTrue(form.is_valid(), form.errors)

    def test_december_of_second_calendar_year_is_within_range(self):
        form = self._form(term=Term.SECOND, start_date="2028-01-10", end_date="2028-05-30")
        self.assertTrue(form.is_valid(), form.errors)

    def test_overlapping_semester_in_same_academic_year_is_rejected(self):
        Semester.objects.create(
            academic_year=self.ay, term=Term.FIRST, start_date=date(2027, 8, 1), end_date=date(2027, 12, 15)
        )
        form = self._form(term=Term.SECOND, start_date="2027-12-01", end_date="2028-04-30")
        self.assertFalse(form.is_valid())
        self.assertIn("overlaps", form.errors["__all__"][0])

    def test_non_overlapping_semester_is_accepted(self):
        Semester.objects.create(
            academic_year=self.ay, term=Term.FIRST, start_date=date(2027, 8, 1), end_date=date(2027, 12, 15)
        )
        form = self._form(term=Term.SECOND, start_date="2028-01-10", end_date="2028-05-30")
        self.assertTrue(form.is_valid(), form.errors)

    def test_editing_a_semester_does_not_overlap_with_itself(self):
        sem = Semester.objects.create(
            academic_year=self.ay, term=Term.FIRST, start_date=date(2027, 8, 1), end_date=date(2027, 12, 15)
        )
        from .forms import SemesterForm

        form = SemesterForm(
            data={
                "academic_year": self.ay.pk, "term": Term.FIRST,
                "start_date": "2027-08-05", "end_date": "2027-12-20",
            },
            instance=sem,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_long_semester_warns_but_does_not_block(self):
        form = self._form(start_date="2027-08-01", end_date="2028-04-01")  # ~8 months
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNotNone(form.duration_warning)

    def test_long_summer_warns_at_a_shorter_threshold(self):
        form = self._form(term=Term.SUMMER, start_date="2028-04-01", end_date="2028-07-15")  # ~3.5 months
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNotNone(form.duration_warning)

    def test_ordinary_duration_has_no_warning(self):
        form = self._form(start_date="2027-08-01", end_date="2027-12-15")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.duration_warning)

    def test_blank_dates_are_allowed_and_unvalidated(self):
        form = self._form()
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.duration_warning)


class SemesterActivationFlowTests(TestCase):
    """View-level: status badges, the no-active-semester banner, the
    Set-as-active action, and the activate-now prompt shown after
    creating a semester while none is active."""

    def setUp(self):
        self.admin = make_user(User.Role.ADMIN, "sem_flow_admin")
        self.ay = AcademicYear.objects.create(start_year=2027)
        self.client.force_login(self.admin)

    def test_active_semester_shows_active_badge_no_button(self):
        Semester.objects.create(academic_year=self.ay, term=Term.FIRST, is_active=True)
        response = self.client.get(reverse("academics:terms"))
        self.assertContains(response, "Active")
        self.assertNotContains(response, "Set as active")

    def test_inactive_semester_shows_inactive_badge_and_button(self):
        Semester.objects.create(academic_year=self.ay, term=Term.FIRST, is_active=False)
        response = self.client.get(reverse("academics:terms"))
        self.assertContains(response, "Inactive")
        self.assertContains(response, "Set as active")

    def test_no_active_semester_shows_banner(self):
        Semester.objects.create(academic_year=self.ay, term=Term.FIRST, is_active=False)
        response = self.client.get(reverse("academics:terms"))
        self.assertContains(response, "No active semester yet")

    def test_banner_absent_once_a_semester_is_active(self):
        Semester.objects.create(academic_year=self.ay, term=Term.FIRST, is_active=True)
        response = self.client.get(reverse("academics:terms"))
        self.assertNotContains(response, "No active semester yet")

    def test_creating_first_semester_prompts_to_activate(self):
        response = self.client.post(
            reverse("academics:semester_create"),
            {"academic_year": self.ay.pk, "term": Term.FIRST},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Set as active semester?")
        semester = Semester.objects.get(academic_year=self.ay)
        self.assertFalse(semester.is_active)

    def test_creating_a_second_semester_does_not_prompt(self):
        Semester.objects.create(academic_year=self.ay, term=Term.FIRST, is_active=True)
        response = self.client.post(
            reverse("academics:semester_create"),
            {"academic_year": self.ay.pk, "term": Term.SECOND},
        )
        self.assertEqual(response.status_code, 204)

    def test_accepting_the_prompt_activates_the_semester(self):
        semester = Semester.objects.create(academic_year=self.ay, term=Term.FIRST, is_active=False)
        response = self.client.post(reverse("academics:semester_set_active", args=[semester.pk]))
        self.assertEqual(response.status_code, 204)
        semester.refresh_from_db()
        self.assertTrue(semester.is_active)


class AcademicYearTests(TestCase):
    def test_end_year_is_derived_from_start_year(self):
        ay = AcademicYear.objects.create(start_year=2026)
        self.assertEqual(ay.end_year, 2027)
        self.assertEqual(str(ay), "A.Y. 2026–2027")


class SectionSemesterValidationTests(TestCase):
    """ClassOffering.clean() can only check sections once the instance has a
    pk (M2M needs one) — the form-level check is what actually protects
    creation; see ClassOfferingForm.clean() in forms.py."""

    def setUp(self):
        self.ay_2026 = AcademicYear.objects.create(start_year=2026)
        self.ay_2027 = AcademicYear.objects.create(start_year=2027)
        self.program = Program.objects.create(code="BSIT", name="BS Information Technology")
        self.section_2026 = Section.objects.create(program=self.program, academic_year=self.ay_2026, year_level=1, name="A")
        self.section_2027 = Section.objects.create(program=self.program, academic_year=self.ay_2027, year_level=1, name="A")
        self.subject = Subject.objects.create(code="IT101", title="Intro to Computing", units=Decimal("3.0"))

    def test_class_offering_rejects_mismatched_academic_year_via_form(self):
        from .forms import ClassOfferingForm

        semester_2026 = Semester.objects.create(academic_year=self.ay_2026)
        form = ClassOfferingForm(
            data={
                "subject": self.subject.pk,
                "sections": [self.section_2027.pk],
                "semester": semester_2026.pk,
                "schedule": "",
                "room": "",
                "is_active": True,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("sections", form.errors)

    def test_class_offering_accepts_matching_academic_year_via_form(self):
        from .forms import ClassOfferingForm

        semester_2026 = Semester.objects.create(academic_year=self.ay_2026)
        form = ClassOfferingForm(
            data={
                "subject": self.subject.pk,
                "sections": [self.section_2026.pk],
                "semester": semester_2026.pk,
                "schedule": "",
                "room": "",
                "is_active": True,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        offering = form.save()
        self.assertEqual(list(offering.sections.all()), [self.section_2026])


class ClassListTests(TestCase):
    def setUp(self):
        self.ay = AcademicYear.objects.create(start_year=2026)
        self.semester = Semester.objects.create(academic_year=self.ay, term=Term.FIRST, is_active=True)
        self.program = Program.objects.create(code="BSIT", name="BS Information Technology")
        self.section = Section.objects.create(program=self.program, academic_year=self.ay, year_level=1, name="A")
        self.other_section = Section.objects.create(
            program=self.program, academic_year=self.ay, year_level=1, name="B"
        )
        self.subject = Subject.objects.create(code="IT101", title="Intro to Computing", units=Decimal("3.0"))
        self.class_offering = ClassOffering.objects.create(subject=self.subject, semester=self.semester)
        self.class_offering.sections.set([self.section])
        self.admin = make_user(User.Role.ADMIN, "admin1")

        self.students_in_section = []
        for i in range(3):
            student = make_user(User.Role.STUDENT, f"stud{i}")
            StudentProfile.objects.filter(user=student).update(program=self.program, section=self.section)
            self.students_in_section.append(student)

        # a student in a different section should NOT get swept in
        self.outside_student = make_user(User.Role.STUDENT, "outside_stud")
        StudentProfile.objects.filter(user=self.outside_student).update(
            program=self.program, section=self.other_section
        )

    def test_add_entire_section_skips_students_already_on_the_list(self):
        # pre-add one student manually
        ClassRosterEntry.objects.create(student=self.students_in_section[0], class_offering=self.class_offering)

        self.client.force_login(User.objects.get(username="admin1"))
        response = self.client.post(
            reverse("academics:class_list_add_section", args=[self.class_offering.pk]),
            {"section": self.section.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("2 added, 1 already on the list", response.content.decode())

        listed_ids = set(
            ClassRosterEntry.objects.filter(class_offering=self.class_offering).values_list("student_id", flat=True)
        )
        self.assertEqual(listed_ids, {s.id for s in self.students_in_section})
        self.assertNotIn(self.outside_student.id, listed_ids)

    def test_mark_dropped_keeps_the_roster_record(self):
        entry = ClassRosterEntry.objects.create(student=self.students_in_section[0], class_offering=self.class_offering)

        self.client.force_login(User.objects.get(username="admin1"))
        self.client.post(reverse("academics:class_list_mark_dropped", args=[entry.pk]))

        entry.refresh_from_db()
        self.assertEqual(entry.status, ClassRosterEntry.Status.DROPPED)
        self.assertEqual(entry.date_dropped, date.today())
        self.assertEqual(ClassRosterEntry.objects.count(), 1)  # still there, not deleted

    def test_restore_clears_drop_date(self):
        entry = ClassRosterEntry.objects.create(
            student=self.students_in_section[0],
            class_offering=self.class_offering,
            status=ClassRosterEntry.Status.DROPPED,
            date_dropped=date.today(),
        )
        self.client.force_login(User.objects.get(username="admin1"))
        self.client.post(reverse("academics:class_list_restore", args=[entry.pk]))

        entry.refresh_from_db()
        self.assertEqual(entry.status, ClassRosterEntry.Status.ACTIVE)
        self.assertIsNone(entry.date_dropped)


class SharedClassTests(TestCase):
    """One ClassOffering can serve multiple sections at once (e.g. a
    General Education subject shared across two majors)."""

    def setUp(self):
        self.ay = AcademicYear.objects.create(start_year=2026)
        self.semester = Semester.objects.create(academic_year=self.ay, term=Term.FIRST, is_active=True)
        self.program = Program.objects.create(code="BSED", name="Bachelor of Secondary Education")
        self.major_a = Major.objects.create(program=self.program, code="ENG", name="English")
        self.major_b = Major.objects.create(program=self.program, code="SS", name="Social Studies")
        self.section_a = Section.objects.create(program=self.program, major=self.major_a, academic_year=self.ay, year_level=1)
        self.section_b = Section.objects.create(program=self.program, major=self.major_b, academic_year=self.ay, year_level=1)
        self.subject = Subject.objects.create(code="GE 2", title="Purposive Communication", units=Decimal("3.0"))
        self.class_offering = ClassOffering.objects.create(subject=self.subject, semester=self.semester)
        self.class_offering.sections.set([self.section_a, self.section_b])

        self.student_a = make_user(User.Role.STUDENT, "student_a")
        StudentProfile.objects.filter(user=self.student_a).update(program=self.program, major=self.major_a, section=self.section_a)
        self.student_b = make_user(User.Role.STUDENT, "student_b")
        StudentProfile.objects.filter(user=self.student_b).update(program=self.program, major=self.major_b, section=self.section_b)

        ClassRosterEntry.objects.create(student=self.student_a, class_offering=self.class_offering)
        ClassRosterEntry.objects.create(student=self.student_b, class_offering=self.class_offering)

    def test_shared_class_roster_includes_students_from_both_sections(self):
        admin = make_user(User.Role.ADMIN, "admin_shared")
        self.client.force_login(User.objects.get(username="admin_shared"))
        response = self.client.get(reverse("academics:class_roster", args=[self.class_offering.pk]))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn(self.student_a.full_name, body)
        self.assertIn(self.student_b.full_name, body)

    def test_str_lists_every_section(self):
        self.assertIn("BSED-ENG 1", str(self.class_offering))
        self.assertIn("BSED-SS 1", str(self.class_offering))


class RoleAndObjectLevelAccessTests(TestCase):
    def setUp(self):
        self.ay = AcademicYear.objects.create(start_year=2026)
        self.semester = Semester.objects.create(academic_year=self.ay, term=Term.FIRST, is_active=True)
        self.program = Program.objects.create(code="BSIT", name="BS Information Technology")
        self.section = Section.objects.create(program=self.program, academic_year=self.ay, year_level=1, name="A")
        self.subject = Subject.objects.create(code="IT101", title="Intro to Computing", units=Decimal("3.0"))

        self.instructor1 = make_user(User.Role.INSTRUCTOR, "inst1")
        self.instructor2 = make_user(User.Role.INSTRUCTOR, "inst2")
        self.class_offering = ClassOffering.objects.create(subject=self.subject, semester=self.semester, instructor=self.instructor1)
        self.class_offering.sections.set([self.section])

        self.program_head_owner = make_user(User.Role.PROGRAM_HEAD, "ph_owner")
        self.program_head_other = make_user(User.Role.PROGRAM_HEAD, "ph_other")
        self.program.program_head = self.program_head_owner
        self.program.save()

        self.student = make_user(User.Role.STUDENT, "stud_role_test")

    def test_student_gets_403_on_admin_classes_page(self):
        self.client.force_login(User.objects.get(username="stud_role_test"))
        response = self.client.get(reverse("academics:classes"))
        self.assertEqual(response.status_code, 403)

    def test_instructor_cannot_open_another_instructors_roster(self):
        self.client.force_login(User.objects.get(username="inst2"))
        response = self.client.get(reverse("academics:class_roster", args=[self.class_offering.pk]))
        self.assertEqual(response.status_code, 403)

    def test_owning_instructor_can_open_their_own_roster(self):
        self.client.force_login(User.objects.get(username="inst1"))
        response = self.client.get(reverse("academics:class_roster", args=[self.class_offering.pk]))
        self.assertEqual(response.status_code, 200)

    def test_instructor_sees_only_own_classes_in_my_classes(self):
        other_subject = Subject.objects.create(code="IT102", title="Programming 1", units=Decimal("3.0"))
        other_class = ClassOffering.objects.create(subject=other_subject, semester=self.semester, instructor=self.instructor2)
        other_class.sections.set([self.section])

        self.client.force_login(User.objects.get(username="inst1"))
        response = self.client.get(reverse("academics:my_classes"))
        body = response.content.decode()
        self.assertIn("IT101", body)
        self.assertNotIn("IT102", body)

    def test_program_head_cannot_open_another_programs_class(self):
        self.client.force_login(User.objects.get(username="ph_other"))
        response = self.client.get(reverse("academics:class_roster", args=[self.class_offering.pk]))
        self.assertEqual(response.status_code, 403)

    def test_owning_program_head_can_open_the_roster(self):
        self.client.force_login(User.objects.get(username="ph_owner"))
        response = self.client.get(reverse("academics:class_roster", args=[self.class_offering.pk]))
        self.assertEqual(response.status_code, 200)


class StudentProfileSignalTests(TestCase):
    def test_creating_a_student_user_auto_creates_a_profile(self):
        user = make_user(User.Role.STUDENT, "autoprofile")
        self.assertTrue(StudentProfile.objects.filter(user=user).exists())

    def test_creating_a_non_student_user_does_not_create_a_profile(self):
        user = make_user(User.Role.INSTRUCTOR, "noprofile")
        self.assertFalse(StudentProfile.objects.filter(user=user).exists())


class RosterImportTests(TestCase):
    def setUp(self):
        self.ay = AcademicYear.objects.create(start_year=2026)
        self.semester = Semester.objects.create(academic_year=self.ay, term=Term.FIRST, is_active=True)
        self.program = Program.objects.create(code="BSIT", name="BS Information Technology")
        self.section = Section.objects.create(program=self.program, academic_year=self.ay, year_level=1, name="A")
        self.subject = Subject.objects.create(code="IT101", title="Intro to Computing", units=Decimal("3.0"))
        self.class_offering = ClassOffering.objects.create(subject=self.subject, semester=self.semester)
        self.class_offering.sections.set([self.section])

        self.existing_student = make_user(User.Role.STUDENT, "existing_imp", id_number="2026-9001")
        ClassRosterEntry.objects.create(student=self.existing_student, class_offering=self.class_offering)

    def test_preview_flags_new_existing_already_and_invalid_rows(self):
        from .roster_import import build_preview

        index = {"id number": 0, "last name": 1, "first name": 2, "middle name": 3}
        data_rows = [
            ("2026-9001", "Existing", "Student", ""),  # already on the list
            ("2026-9002", "Brand", "New", ""),  # new
            ("", "Missing", "IdNumber", ""),  # invalid
        ]
        preview = build_preview(self.class_offering, index, data_rows)
        kinds = {row["id_number"]: row["kind"] for row in preview if row["id_number"]}
        self.assertEqual(kinds["2026-9001"], "already")
        self.assertEqual(kinds["2026-9002"], "new")
        invalid_rows = [r for r in preview if r["kind"] == "invalid"]
        self.assertEqual(len(invalid_rows), 1)

    def test_commit_import_creates_user_and_roster_entry(self):
        from .roster_import import commit_import

        rows = [{"kind": "new", "id_number": "2026-9003", "first_name": "Juan", "last_name": "Dela Cruz", "middle_name": ""}]
        summary = commit_import(self.class_offering, rows, self.section)

        self.assertEqual(summary["created_users"], 1)
        self.assertEqual(summary["added_to_roster"], 1)
        new_user = User.objects.get(id_number="2026-9003")
        self.assertEqual(new_user.role, User.Role.STUDENT)
        self.assertTrue(new_user.must_change_password)
        self.assertTrue(ClassRosterEntry.objects.filter(student=new_user, class_offering=self.class_offering).exists())
        self.assertEqual(new_user.student_profile.section, self.section)


class DocxParserTests(TestCase):
    def test_group_shared_classes_merges_identical_offerings(self):
        from .management.commands.import_offerings_docx import group_shared_classes

        rows = [
            {
                "semester": "FIRST", "code": "GE 2", "description": "Purposive Communication", "units": "3",
                "instructor": "Mr. Garibay", "room": "204 HB", "schedule": "5-8 PM (Fri)",
                "program": "BSED", "major": "English", "year_level": 1,
            },
            {
                "semester": "FIRST", "code": "GE 2", "description": "Purposive Communication", "units": "3",
                "instructor": "Mr. Garibay", "room": "204 HB", "schedule": "5-8 PM (Fri)",
                "program": "BSED", "major": "Social Studies", "year_level": 1,
            },
        ]
        classes = group_shared_classes(rows)
        self.assertEqual(len(classes), 1)
        self.assertEqual(len(classes[0]["sections"]), 2)

    def test_group_shared_classes_keeps_different_schedules_separate(self):
        from .management.commands.import_offerings_docx import group_shared_classes

        rows = [
            {
                "semester": "FIRST", "code": "PEd 207", "description": "Assessment", "units": "3",
                "instructor": "Mr. Honrejas", "room": "205 HB", "schedule": "5-8 PM (Fri)",
                "program": "BSED", "major": "English", "year_level": 3,
            },
            {
                "semester": "FIRST", "code": "PEd 207", "description": "Assessment", "units": "3",
                "instructor": "Mr. Honrejas", "room": "205 HB", "schedule": "5-8 PM (Tue)",
                "program": "BSED", "major": "Social Studies", "year_level": 3,
            },
        ]
        classes = group_shared_classes(rows)
        self.assertEqual(len(classes), 2)

    def test_normalize_instructor_fixes_missing_space(self):
        from .management.commands.import_offerings_docx import normalize_instructor

        self.assertEqual(normalize_instructor("Mr.Monteros"), "Mr. Monteros")

    def test_normalize_schedule_balances_parentheses(self):
        from .management.commands.import_offerings_docx import normalize_schedule

        self.assertEqual(normalize_schedule("4-7 PM (Tue"), "4-7 PM (Tue)")

    def test_suspicious_pairs_catches_similar_names_without_merging(self):
        from .management.commands.import_offerings_docx import find_suspicious_name_pairs

        pairs = find_suspicious_name_pairs(["Mr. Garibay", "Ms. Garibay", "Mr. Caballa"])
        self.assertIn(("Mr. Garibay", "Ms. Garibay"), pairs)


class SeedCitciAcademicsIdempotencyTests(TestCase):
    """seed_citci_academics must be safe to re-run: no duplicate instructor
    accounts (garibay2, garibay3, ...) and no duplicate anything else."""

    def _counts(self):
        from grading.models import AssessmentItem, ClassGradingScheme, GradingTemplate, Score

        return {
            "users": User.objects.count(),
            "instructors": User.objects.filter(role=User.Role.INSTRUCTOR).count(),
            "students": User.objects.filter(role=User.Role.STUDENT).count(),
            "programs": Program.objects.count(),
            "majors": Major.objects.count(),
            "sections": Section.objects.count(),
            "subjects": Subject.objects.count(),
            "classes": ClassOffering.objects.count(),
            "roster_entries": ClassRosterEntry.objects.count(),
            "grading_templates": GradingTemplate.objects.count(),
            "grading_schemes": ClassGradingScheme.objects.count(),
            "assessment_items": AssessmentItem.objects.count(),
            "scores": Score.objects.count(),
        }

    def test_running_twice_does_not_duplicate_records(self):
        from io import StringIO

        from django.core.management import call_command

        call_command("seed_citci_academics", stdout=StringIO())
        counts_after_first_run = self._counts()

        call_command("seed_citci_academics", stdout=StringIO())
        counts_after_second_run = self._counts()

        self.assertEqual(counts_after_first_run, counts_after_second_run)
        # Specifically guard against the known "garibay2" duplicate-username bug.
        garibay_usernames = User.objects.filter(last_name="Mr. Garibay").values_list("username", flat=True)
        self.assertLessEqual(len(garibay_usernames), 1)


class TeachingAssignmentTestBase(TestCase):
    """Program heads assign teaching loads; admin can too, as a logged
    override. Shared fixture: two programs (each with a program head and
    an instructor), one unassigned class under program A."""

    def setUp(self):
        self.ay = AcademicYear.objects.create(start_year=2026)
        self.semester = Semester.objects.create(academic_year=self.ay, term=Term.FIRST, is_active=True)

        self.program_a = Program.objects.create(code="BSIT", name="BS Information Technology")
        self.program_b = Program.objects.create(code="BSED", name="BS Education")
        self.section_a = Section.objects.create(program=self.program_a, academic_year=self.ay, year_level=1, name="A")
        self.section_b = Section.objects.create(program=self.program_b, academic_year=self.ay, year_level=1, name="A")

        self.head_a = make_user(User.Role.PROGRAM_HEAD, "ta_head_a")
        self.head_b = make_user(User.Role.PROGRAM_HEAD, "ta_head_b")
        self.program_a.program_head = self.head_a
        self.program_a.save()
        self.program_b.program_head = self.head_b
        self.program_b.save()

        self.instructor1 = make_user(User.Role.INSTRUCTOR, "ta_inst1")
        self.instructor2 = make_user(User.Role.INSTRUCTOR, "ta_inst2")
        self.admin = make_user(User.Role.ADMIN, "ta_admin", is_staff=True, is_superuser=True)

        self.subject = Subject.objects.create(code="PEd 205", title="Physical Education", units=Decimal("2.0"))
        self.class_offering = ClassOffering.objects.create(subject=self.subject, semester=self.semester)
        self.class_offering.sections.set([self.section_a])

    def make_submitted_sheet(self, class_offering):
        from approvals.models import GradeSheet, GradeSheetStatus

        return GradeSheet.objects.create(class_offering=class_offering, status=GradeSheetStatus.SUBMITTED)


class UnassignedClassHandlingTests(TeachingAssignmentTestBase):
    """An unassigned class must never break a page it can legitimately
    appear on."""

    def test_unassigned_class_does_not_appear_in_any_instructors_my_classes(self):
        self.client.force_login(self.instructor1)
        response = self.client.get(reverse("academics:my_classes"))
        self.assertNotContains(response, "PEd 205")

    def test_program_head_classes_page_renders_unassigned_class_gracefully(self):
        self.client.force_login(self.head_a)
        response = self.client.get(reverse("academics:program_head_classes"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Unassigned")

    def test_class_roster_renders_for_an_unassigned_class(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("academics:class_roster", args=[self.class_offering.pk]))
        self.assertEqual(response.status_code, 200)


class AssignInstructorPermissionTests(TeachingAssignmentTestBase):
    def test_program_head_can_assign_within_their_own_program(self):
        self.client.force_login(self.head_a)
        response = self.client.post(
            reverse("academics:class_assign_instructor", args=[self.class_offering.pk]),
            {"instructor": self.instructor1.pk},
        )
        self.assertEqual(response.status_code, 204)
        self.class_offering.refresh_from_db()
        self.assertEqual(self.class_offering.instructor_id, self.instructor1.id)

    def test_program_head_of_a_different_program_gets_403(self):
        self.client.force_login(self.head_b)
        response = self.client.post(
            reverse("academics:class_assign_instructor", args=[self.class_offering.pk]),
            {"instructor": self.instructor1.pk},
        )
        self.assertEqual(response.status_code, 403)

    def test_instructor_role_gets_403(self):
        self.client.force_login(self.instructor1)
        response = self.client.get(reverse("academics:class_assign_instructor", args=[self.class_offering.pk]))
        self.assertEqual(response.status_code, 403)

    def test_assigning_a_class_that_does_not_exist_404s(self):
        self.client.force_login(self.head_a)
        response = self.client.get(reverse("academics:class_assign_instructor", args=[999999]))
        self.assertEqual(response.status_code, 404)

    def test_admin_can_assign_any_class_as_an_override(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("academics:class_assign_instructor", args=[self.class_offering.pk]),
            {"instructor": self.instructor1.pk},
        )
        self.assertEqual(response.status_code, 204)
        self.class_offering.refresh_from_db()
        self.assertEqual(self.class_offering.instructor_id, self.instructor1.id)
        log = self.class_offering.assignment_logs.get()
        self.assertTrue(log.is_admin_override)


class AssignInstructorBlockedAfterSubmissionTests(TeachingAssignmentTestBase):
    def test_blocked_once_grade_sheet_is_submitted(self):
        self.class_offering.instructor = self.instructor1
        self.class_offering.save()
        self.make_submitted_sheet(self.class_offering)

        self.client.force_login(self.head_a)
        response = self.client.post(
            reverse("academics:class_assign_instructor", args=[self.class_offering.pk]),
            {"instructor": self.instructor2.pk},
        )
        # Re-rendered with a form error, not a 204 success.
        self.assertEqual(response.status_code, 200)
        self.class_offering.refresh_from_db()
        self.assertEqual(self.class_offering.instructor_id, self.instructor1.id)

    def test_allowed_while_draft(self):
        from approvals.models import GradeSheet, GradeSheetStatus

        self.class_offering.instructor = self.instructor1
        self.class_offering.save()
        GradeSheet.objects.create(class_offering=self.class_offering, status=GradeSheetStatus.DRAFT)

        self.client.force_login(self.head_a)
        response = self.client.post(
            reverse("academics:class_assign_instructor", args=[self.class_offering.pk]),
            {"instructor": self.instructor2.pk},
        )
        self.assertEqual(response.status_code, 204)
        self.class_offering.refresh_from_db()
        self.assertEqual(self.class_offering.instructor_id, self.instructor2.id)


class ClassInlineFieldUpdateTests(TeachingAssignmentTestBase):
    """The Classes page's inline-edit endpoint (instructor/room/schedule),
    re-rendering just the one <tr> -- same convention as grading's
    save_cell, now applied to the Classes page per the redesign spec.

    Regression coverage for a real bug: every row's inline controls used
    to share the literal name="value" and all sat inside one page-wide
    <form> (the old bulk-assign box) -- htmx serializes the whole
    enclosing form by default, so a single change event posted every
    row's value under one colliding name, and Django's QueryDict.get()
    silently returned the LAST one (almost always blank). The fix removed
    that enclosing form and added hx-include="this" to each control, so a
    posted selection must now actually come back selected in the
    re-rendered <select> -- the first test below pins that down with
    assertInHTML on the actual <option selected> markup, not just a
    substring match (a substring match wouldn't have caught the bug,
    since the posted id does appear elsewhere in the <select>'s option
    list regardless of which one ended up selected)."""

    def test_instructor_selection_actually_persists_and_renders_selected(self):
        self.client.force_login(self.head_a)
        response = self.client.post(
            reverse("academics:class_update_field", args=[self.class_offering.pk]),
            {"field": "instructor", "value": self.instructor1.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.class_offering.refresh_from_db()
        self.assertEqual(self.class_offering.instructor_id, self.instructor1.id)
        self.assertInHTML(
            f'<option value="{self.instructor1.pk}" selected>{self.instructor1.full_name}</option>',
            response.content.decode(),
        )
        toast = json.loads(response.headers["HX-Trigger"])["toast"]
        self.assertEqual(toast["level"], "success")
        self.assertIn(self.instructor1.full_name, toast["message"])
        self.assertIn("PEd 205", toast["message"])

    def test_instructor_assignment_updates_unassigned_banner_out_of_band(self):
        self.client.force_login(self.head_a)
        response = self.client.post(
            reverse("academics:class_update_field", args=[self.class_offering.pk]),
            {"field": "instructor", "value": self.instructor1.pk},
        )
        self.assertNotIn("1 class need", response.content.decode())
        self.assertIn('id="unassigned-banner"', response.content.decode())
        self.assertIn("hx-swap-oob", response.content.decode())

    def test_updates_room_and_rerenders_row(self):
        self.client.force_login(self.head_a)
        response = self.client.post(
            reverse("academics:class_update_field", args=[self.class_offering.pk]),
            {"field": "room", "value": "Rm 301"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rm 301")
        self.class_offering.refresh_from_db()
        self.assertEqual(self.class_offering.room, "Rm 301")
        toast = json.loads(response.headers["HX-Trigger"])["toast"]
        self.assertEqual(toast["level"], "success")

    def test_updates_schedule(self):
        self.client.force_login(self.head_a)
        response = self.client.post(
            reverse("academics:class_update_field", args=[self.class_offering.pk]),
            {"field": "schedule", "value": "MWF 8:00-9:00"},
        )
        self.assertEqual(response.status_code, 200)
        self.class_offering.refresh_from_db()
        self.assertEqual(self.class_offering.schedule, "MWF 8:00-9:00")

    def test_updates_instructor_through_assign_instructor_service(self):
        self.client.force_login(self.head_a)
        response = self.client.post(
            reverse("academics:class_update_field", args=[self.class_offering.pk]),
            {"field": "instructor", "value": self.instructor1.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.class_offering.refresh_from_db()
        self.assertEqual(self.class_offering.instructor_id, self.instructor1.id)

    def test_blocked_once_grade_sheet_submitted_shows_inline_error_toast_and_reverts(self):
        self.class_offering.instructor = self.instructor1
        self.class_offering.save()
        self.make_submitted_sheet(self.class_offering)

        self.client.force_login(self.head_a)
        response = self.client.post(
            reverse("academics:class_update_field", args=[self.class_offering.pk]),
            {"field": "instructor", "value": self.instructor2.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.class_offering.refresh_from_db()
        self.assertEqual(self.class_offering.instructor_id, self.instructor1.id)
        self.assertInHTML(
            f'<option value="{self.instructor1.pk}" selected>{self.instructor1.full_name}</option>',
            response.content.decode(),
        )
        toast = json.loads(response.headers["HX-Trigger"])["toast"]
        self.assertEqual(toast["level"], "error")
        self.assertIn("submitted", toast["message"])

    def test_silent_bulk_mode_suppresses_success_toast_but_not_error_toast(self):
        self.client.force_login(self.head_a)
        response = self.client.post(
            reverse("academics:class_update_field", args=[self.class_offering.pk]),
            {"field": "room", "value": "Rm 301", "silent": "1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("HX-Trigger", response.headers)

        self.class_offering.instructor = self.instructor1
        self.class_offering.save()
        self.make_submitted_sheet(self.class_offering)
        response2 = self.client.post(
            reverse("academics:class_update_field", args=[self.class_offering.pk]),
            {"field": "instructor", "value": self.instructor2.pk, "silent": "1"},
        )
        self.assertIn("HX-Trigger", response2.headers)
        toast = json.loads(response2.headers["HX-Trigger"])["toast"]
        self.assertEqual(toast["level"], "error")

    def test_outside_program_head_gets_403(self):
        self.client.force_login(self.head_b)
        response = self.client.post(
            reverse("academics:class_update_field", args=[self.class_offering.pk]),
            {"field": "room", "value": "Rm 301"},
        )
        self.assertEqual(response.status_code, 403)

    def test_unknown_field_rejected(self):
        self.client.force_login(self.head_a)
        response = self.client.post(
            reverse("academics:class_update_field", args=[self.class_offering.pk]),
            {"field": "subject", "value": "haxx"},
        )
        self.assertEqual(response.status_code, 403)


class AssignInstructorNotificationAndLogTests(TeachingAssignmentTestBase):
    def test_new_and_previous_instructor_are_both_notified(self):
        from dashboard.models import Notification

        self.class_offering.instructor = self.instructor1
        self.class_offering.save()

        self.client.force_login(self.head_a)
        self.client.post(
            reverse("academics:class_assign_instructor", args=[self.class_offering.pk]),
            {"instructor": self.instructor2.pk},
        )

        self.assertTrue(Notification.objects.filter(recipient=self.instructor2, title="New teaching assignment").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.instructor1, title="Teaching assignment changed").exists())

    def test_assignment_is_logged_with_changed_by_and_no_override_flag_for_program_head(self):
        self.client.force_login(self.head_a)
        self.client.post(
            reverse("academics:class_assign_instructor", args=[self.class_offering.pk]),
            {"instructor": self.instructor1.pk},
        )
        log = self.class_offering.assignment_logs.get()
        self.assertEqual(log.changed_by, self.head_a)
        self.assertFalse(log.is_admin_override)
        self.assertIsNone(log.old_instructor)
        self.assertEqual(log.new_instructor, self.instructor1)

    def test_no_op_assignment_is_not_logged(self):
        self.class_offering.instructor = self.instructor1
        self.class_offering.save()

        self.client.force_login(self.head_a)
        self.client.post(
            reverse("academics:class_assign_instructor", args=[self.class_offering.pk]),
            {"instructor": self.instructor1.pk},
        )
        self.assertEqual(self.class_offering.assignment_logs.count(), 0)

    def test_admin_classes_edit_form_logs_as_override(self):
        """The admin's existing Classes CRUD edit form changes the same
        instructor field — it must go through the same logging path."""
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("academics:class_edit", args=[self.class_offering.pk]),
            {
                "subject": self.subject.pk,
                "sections": [self.section_a.pk],
                "semester": self.semester.pk,
                "instructor": self.instructor1.pk,
                "schedule": "",
                "room": "",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 204)
        log = self.class_offering.assignment_logs.get()
        self.assertTrue(log.is_admin_override)
        self.assertEqual(log.new_instructor, self.instructor1)


class TeachingLoadsPageTests(TeachingAssignmentTestBase):
    def setUp(self):
        super().setUp()
        self.class_offering.instructor = self.instructor1
        self.class_offering.save()

        self.second_subject = Subject.objects.create(code="IT205", title="Databases", units=Decimal("3.0"))
        self.second_class = ClassOffering.objects.create(subject=self.second_subject, semester=self.semester, instructor=self.instructor1)
        self.second_class.sections.set([self.section_a])

        self.student = make_user(User.Role.STUDENT, "ta_student")
        ClassRosterEntry.objects.create(student=self.student, class_offering=self.class_offering)

    def test_program_head_sees_totals_across_shared_classes(self):
        self.client.force_login(self.head_a)
        response = self.client.get(reverse("academics:teaching_loads"))
        self.assertEqual(response.status_code, 200)
        rows = {row["instructor"].pk: row for row in response.context["rows"]}
        self.assertEqual(len(rows[self.instructor1.pk]["classes"]), 2)
        self.assertEqual(rows[self.instructor1.pk]["total_units"], Decimal("5.0"))  # 2.0 + 3.0
        self.assertEqual(rows[self.instructor1.pk]["total_students"], 1)

    def test_admin_can_filter_by_program(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("academics:teaching_loads"), {"program": self.program_b.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["rows"], [])

    def test_export_returns_an_xlsx_file(self):
        self.client.force_login(self.head_a)
        response = self.client.get(reverse("academics:teaching_loads_export"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheetml", response["Content-Type"])


class TeachingAssignmentAuditLogTests(TeachingAssignmentTestBase):
    def test_assignment_appears_in_the_combined_audit_log(self):
        from accounts.audit import collect_audit_rows

        self.client.force_login(self.head_a)
        self.client.post(
            reverse("academics:class_assign_instructor", args=[self.class_offering.pk]),
            {"instructor": self.instructor1.pk},
        )
        rows = collect_audit_rows(source="teaching_assignment")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["actor"], self.head_a)
        self.assertFalse(rows[0]["details"]["is_admin_override"])


class OfferingsImportTests(TestCase):
    """Admin: Import Class Offerings — xlsx preview/confirm. Never
    auto-creates or auto-merges an instructor."""

    def setUp(self):
        self.ay = AcademicYear.objects.create(start_year=2026)
        self.semester = Semester.objects.create(academic_year=self.ay, term=Term.FIRST, is_active=True)
        self.program = Program.objects.create(code="BSED", name="BS Secondary Education")
        self.major = Major.objects.create(program=self.program, code="ENG", name="English")
        self.section = Section.objects.create(
            program=self.program, major=self.major, academic_year=self.ay, year_level=1, name=""
        )
        self.instructor = make_user(User.Role.INSTRUCTOR, "garibay", first_name="Juan", last_name="Garibay")
        self.admin = make_user(User.Role.ADMIN, "import_admin")

    def _index(self):
        return {
            "semester": 0, "program": 1, "major": 2, "year level": 3, "course code": 4,
            "description": 5, "units": 6, "room": 7, "schedule": 8, "instructor": 9,
        }

    def test_preview_classifies_new_subject_and_matches_known_instructor(self):
        from .offerings_import import build_offerings_preview

        rows = [
            ("FIRST", "BSED", "ENG", "1", "ENG101", "Intro to Lit", "3", "Room 1", "MWF 8-9AM", "Juan Garibay"),
        ]
        preview = build_offerings_preview(self._index(), rows, self.semester)
        self.assertEqual(preview["new_subject_count"], 1)
        self.assertEqual(preview["new_class_count"], 1)
        self.assertEqual(preview["invalid_count"], 0)
        self.assertEqual(preview["unknown_instructor_names"], [])
        self.assertEqual(preview["classes"][0]["matched_instructor_id"], self.instructor.pk)

    def test_preview_never_matches_or_creates_an_unknown_instructor(self):
        from .offerings_import import build_offerings_preview

        rows = [
            ("FIRST", "BSED", "ENG", "1", "ENG102", "World Lit", "3", "Room 1", "MWF 9-10AM", "Someone Unknown"),
        ]
        preview = build_offerings_preview(self._index(), rows, self.semester)
        self.assertEqual(preview["unknown_instructor_names"], ["Someone Unknown"])
        self.assertIsNone(preview["classes"][0]["matched_instructor_id"])
        self.assertEqual(User.objects.filter(role=User.Role.INSTRUCTOR).count(), 1)  # unchanged

    def test_preview_flags_unknown_program_and_missing_section_as_invalid(self):
        from .offerings_import import build_offerings_preview

        rows = [
            ("FIRST", "XXXX", "", "", "ENG103", "Bad Program", "3", "", "", ""),
            ("FIRST", "BSED", "ENG", "4", "ENG104", "No Section For Year 4", "3", "", "", ""),
        ]
        preview = build_offerings_preview(self._index(), rows, self.semester)
        self.assertEqual(preview["invalid_count"], 2)
        self.assertEqual(preview["classes"], [])

    def test_preview_detects_shared_class_across_sections(self):
        from .offerings_import import build_offerings_preview

        major2 = Major.objects.create(program=self.program, code="SS", name="Social Studies")
        Section.objects.create(program=self.program, major=major2, academic_year=self.ay, year_level=1, name="")
        rows = [
            ("FIRST", "BSED", "ENG", "1", "GE2", "Purposive Comm", "3", "Rm1", "5-8PM Fri", "Juan Garibay"),
            ("FIRST", "BSED", "SS", "1", "GE2", "Purposive Comm", "3", "Rm1", "5-8PM Fri", "Juan Garibay"),
        ]
        preview = build_offerings_preview(self._index(), rows, self.semester)
        self.assertEqual(preview["new_class_count"], 1)
        self.assertEqual(preview["shared_class_count"], 1)
        self.assertEqual(len(preview["classes"][0]["section_ids"]), 2)

    def test_preview_makes_zero_writes(self):
        from .offerings_import import build_offerings_preview

        rows = [("FIRST", "BSED", "ENG", "1", "ENG105", "New Subject", "3", "", "", "")]
        before_subjects = Subject.objects.count()
        before_classes = ClassOffering.objects.count()
        build_offerings_preview(self._index(), rows, self.semester)
        self.assertEqual(Subject.objects.count(), before_subjects)
        self.assertEqual(ClassOffering.objects.count(), before_classes)

    def test_commit_creates_subject_and_class_with_unassigned_instructor(self):
        from .offerings_import import build_offerings_preview, commit_offerings_import

        rows = [("FIRST", "BSED", "ENG", "1", "ENG106", "Shakespeare", "3", "Rm2", "", "Unknown Person")]
        preview = build_offerings_preview(self._index(), rows, self.semester)
        counts = commit_offerings_import(preview["classes"], self.semester)

        self.assertEqual(counts["subjects_created"], 1)
        self.assertEqual(counts["classes_created"], 1)
        self.assertEqual(counts["unassigned_instructor_classes"], 1)
        new_class = ClassOffering.objects.get(subject__code="ENG106")
        self.assertIsNone(new_class.instructor)
        self.assertIn(self.section, new_class.sections.all())

    def test_non_admin_gets_403_on_every_new_url(self):
        instructor = make_user(User.Role.INSTRUCTOR, "not_admin_offerings")
        self.client.force_login(instructor)
        for url_name in (
            "academics:offerings_import",
            "academics:offerings_import_template",
            "academics:offerings_copy_previous",
        ):
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 403, url_name)


class OfferingsImportAtomicityTests(TransactionTestCase):
    """Uses TransactionTestCase (real commits, not TestCase's savepoints) —
    under TestCase's nested-savepoint setup, Postgres defers this FK check
    past the inner transaction.atomic() block's own exit, which would make
    this test assert something that didn't actually happen yet."""

    def setUp(self):
        self.ay = AcademicYear.objects.create(start_year=2026)
        self.semester = Semester.objects.create(academic_year=self.ay, term=Term.FIRST, is_active=True)
        self.program = Program.objects.create(code="BSED", name="BS Secondary Education")
        self.section = Section.objects.create(program=self.program, academic_year=self.ay, year_level=1, name="")

    def test_commit_is_one_atomic_transaction(self):
        from django.db import IntegrityError

        from .offerings_import import commit_offerings_import

        # A class dict with a bogus instructor id forces an IntegrityError
        # mid-loop; a prior valid row in the same call must not be left
        # committed.
        classes = [
            {
                "code": "ENG107", "description": "Valid Row", "units": "3", "room": "", "schedule": "",
                "instructor_name": "", "program_ids": [self.program.id], "section_ids": [self.section.id],
                "matched_instructor_id": None,
            },
            {
                "code": "ENG108", "description": "Bad Row", "units": "3", "room": "", "schedule": "",
                "instructor_name": "", "program_ids": [self.program.id], "section_ids": [self.section.id],
                "matched_instructor_id": 999999,
            },
        ]
        with self.assertRaises(IntegrityError):
            commit_offerings_import(classes, self.semester)
        self.assertFalse(Subject.objects.filter(code="ENG107").exists())


class CopyClassesPreviousSemesterTests(TestCase):
    def setUp(self):
        self.ay_old = AcademicYear.objects.create(start_year=2025)
        self.ay_new = AcademicYear.objects.create(start_year=2026)
        self.old_semester = Semester.objects.create(academic_year=self.ay_old, term=Term.FIRST)
        self.new_semester = Semester.objects.create(academic_year=self.ay_new, term=Term.FIRST, is_active=True)

        self.program = Program.objects.create(code="BSED", name="BS Secondary Education")
        self.old_section = Section.objects.create(program=self.program, academic_year=self.ay_old, year_level=1, name="")
        self.new_section = Section.objects.create(program=self.program, academic_year=self.ay_new, year_level=1, name="")

        self.subject = Subject.objects.create(code="PEd207", title="Assessment", units=Decimal("3.0"))
        self.instructor = make_user(User.Role.INSTRUCTOR, "copy_instructor")
        self.old_class = ClassOffering.objects.create(
            subject=self.subject, semester=self.old_semester, instructor=self.instructor, room="Rm1"
        )
        self.old_class.sections.set([self.old_section])

    def test_default_source_semester_is_same_term_previous_academic_year(self):
        from .services import default_source_semester

        self.assertEqual(default_source_semester(self.new_semester), self.old_semester)

    def test_preview_resolves_equivalent_section_and_never_copies_instructor(self):
        from .services import build_copy_preview

        rows = build_copy_preview(self.old_semester, self.new_semester)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["can_copy"])
        self.assertEqual(rows[0]["target_section_ids"], [self.new_section.id])

    def test_missing_equivalent_section_is_reported_not_guessed(self):
        from .services import build_copy_preview

        self.new_section.delete()
        rows = build_copy_preview(self.old_semester, self.new_semester)
        self.assertFalse(rows[0]["can_copy"])
        self.assertEqual(rows[0]["missing_sections"], [self.old_section])

    def test_commit_copy_always_leaves_instructor_unassigned(self):
        from .services import build_copy_preview, commit_copy

        rows = build_copy_preview(self.old_semester, self.new_semester)
        counts = commit_copy(rows, self.new_semester)
        self.assertEqual(counts["created"], 1)
        self.assertEqual(counts["skipped"], 0)
        new_class = ClassOffering.objects.get(subject=self.subject, semester=self.new_semester)
        self.assertIsNone(new_class.instructor)
        self.assertIn(self.new_section, new_class.sections.all())

    def test_commit_copy_skips_unresolvable_rows_without_partial_class(self):
        from .services import build_copy_preview, commit_copy

        self.new_section.delete()
        rows = build_copy_preview(self.old_semester, self.new_semester)
        counts = commit_copy(rows, self.new_semester)
        self.assertEqual(counts["created"], 0)
        self.assertEqual(counts["skipped"], 1)
        self.assertFalse(ClassOffering.objects.filter(subject=self.subject, semester=self.new_semester).exists())

    def test_source_semester_and_sections_untouched_by_copy(self):
        from .services import build_copy_preview, commit_copy

        rows = build_copy_preview(self.old_semester, self.new_semester)
        commit_copy(rows, self.new_semester)
        self.old_class.refresh_from_db()
        self.assertEqual(self.old_class.instructor, self.instructor)
        self.assertIn(self.old_section, self.old_class.sections.all())


class AYWizardTestBase(TestCase):
    def setUp(self):
        self.ay_2026 = AcademicYear.objects.create(start_year=2026)
        self.program = Program.objects.create(code="BSED", name="BS Secondary Education")
        self.tcp = Program.objects.create(code="TCP", name="Teacher Certificate Program")
        self.sec1 = Section.objects.create(program=self.program, academic_year=self.ay_2026, year_level=1, name="")
        self.sec2 = Section.objects.create(program=self.program, academic_year=self.ay_2026, year_level=2, name="")
        self.sec4 = Section.objects.create(program=self.program, academic_year=self.ay_2026, year_level=4, name="")
        self.sec_tcp = Section.objects.create(program=self.tcp, academic_year=self.ay_2026, year_level=None, name="")
        self.admin = make_user(User.Role.ADMIN, "wizard_admin")

    def _make_student(self, username, section):
        student = make_user(User.Role.STUDENT, username, id_number=username)
        StudentProfile.objects.filter(user=student).update(
            program=section.program, section=section, year_level=section.year_level
        )
        return student


class AYWizardStepTests(AYWizardTestBase):
    def test_step1_preview_flags_already_existing_year(self):
        from .ay_wizard import step1_preview

        preview = step1_preview(2026)
        self.assertTrue(preview["already_exists"])
        preview = step1_preview(2027)
        self.assertFalse(preview["already_exists"])
        self.assertEqual(preview["end_year"], 2028)

    def test_step2_preview_sections_lists_every_source_section(self):
        from .ay_wizard import step2_preview_sections

        sections = step2_preview_sections(self.ay_2026)
        self.assertEqual(len(sections), 4)

    def test_step3_promotes_year1_to_year2(self):
        from .ay_wizard import step2_preview_sections, step3_preview_promotions

        student = self._make_student("promo1", self.sec1)
        new_sections = step2_preview_sections(self.ay_2026)  # same keys reused for the "new" year in this test
        rows = step3_preview_promotions(self.ay_2026, new_sections)
        row = next(r for r in rows if r["student"] == student)
        self.assertFalse(row["will_complete"])
        self.assertEqual(row["target_key"], (self.program.id, None, 2, ""))

    def test_step3_marks_4th_year_and_tcp_as_completed(self):
        from .ay_wizard import step2_preview_sections, step3_preview_promotions

        year4_student = self._make_student("promo4", self.sec4)
        tcp_student = self._make_student("promotcp", self.sec_tcp)
        new_sections = step2_preview_sections(self.ay_2026)
        rows = step3_preview_promotions(self.ay_2026, new_sections)

        row4 = next(r for r in rows if r["student"] == year4_student)
        row_tcp = next(r for r in rows if r["student"] == tcp_student)
        self.assertTrue(row4["will_complete"])
        self.assertTrue(row_tcp["will_complete"])

    def test_step3_flags_unresolved_when_no_matching_target_section(self):
        from .ay_wizard import step3_preview_promotions

        self._make_student("nomatch", self.sec1)
        rows = step3_preview_promotions(self.ay_2026, [])  # no sections for the "new" year
        row = rows[0]
        self.assertTrue(row["unresolved"])


class AYWizardExclusionTests(AYWizardTestBase):
    def test_excluded_student_is_untouched_by_commit(self):
        from .ay_wizard import step2_preview_sections, step3_preview_promotions, step4_commit

        student = self._make_student("excl1", self.sec1)
        new_sections = step2_preview_sections(self.ay_2026)
        rows = step3_preview_promotions(self.ay_2026, new_sections)
        for row in rows:
            row["excluded"] = True

        step4_commit(2027, ["FIRST"], new_sections, rows, self.admin)

        student.student_profile.refresh_from_db()
        self.assertEqual(student.student_profile.section, self.sec1)
        self.assertEqual(student.student_profile.status, StudentProfile.Status.ACTIVE)


class AYWizardTransactionTests(TransactionTestCase):
    """Uses TransactionTestCase (real commits) — see
    OfferingsImportAtomicityTests for why TestCase's nested savepoints
    aren't sufficient to observe this synchronously."""

    def setUp(self):
        self.ay_2026 = AcademicYear.objects.create(start_year=2026)
        self.program = Program.objects.create(code="BSED", name="BS Secondary Education")
        self.admin = make_user(User.Role.ADMIN, "wizard_tx_admin")

    def test_forced_failure_leaves_zero_new_rows(self):
        from django.db import IntegrityError

        from .ay_wizard import step4_commit

        # The second section dict references a nonexistent program, forcing
        # an IntegrityError after the AcademicYear/Semester rows and the
        # first Section already exist inside this same call. The whole
        # call must still roll back.
        sections_to_create = [
            {"program_id": self.program.id, "major_id": None, "year_level": 1, "name": "", "label": "valid"},
            {"program_id": 999999, "major_id": None, "year_level": 1, "name": "", "label": "bad"},
        ]
        with self.assertRaises(IntegrityError):
            step4_commit(2027, ["FIRST"], sections_to_create, [], self.admin)
        self.assertFalse(AcademicYear.objects.filter(start_year=2027).exists())
        self.assertEqual(Section.objects.filter(academic_year__start_year=2027).count(), 0)


class AYWizardAuditLogTests(AYWizardTestBase):
    def test_exactly_one_audit_log_row_with_correct_counts(self):
        from accounts.models import AuditLog

        from .ay_wizard import step2_preview_sections, step3_preview_promotions, step4_commit

        self._make_student("audit1", self.sec1)
        self._make_student("audit2", self.sec4)
        new_sections = step2_preview_sections(self.ay_2026)
        rows = step3_preview_promotions(self.ay_2026, new_sections)

        step4_commit(2027, ["FIRST", "SECOND"], new_sections, rows, self.admin)

        logs = AuditLog.objects.filter(action=AuditLog.Action.ACADEMIC_YEAR_WIZARD_RUN)
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.first().details["promoted"], 1)
        self.assertEqual(logs.first().details["completed"], 1)


class AYWizardPastDataUntouchedTests(AYWizardTestBase):
    def test_prior_semester_sections_and_classes_untouched(self):
        from .ay_wizard import step2_preview_sections, step3_preview_promotions, step4_commit

        semester = Semester.objects.create(academic_year=self.ay_2026)
        subject = Subject.objects.create(code="X101", title="X", units=Decimal("3.0"))
        class_offering = ClassOffering.objects.create(subject=subject, semester=semester)
        class_offering.sections.set([self.sec1])
        self._make_student("keep1", self.sec1)

        new_sections = step2_preview_sections(self.ay_2026)
        rows = step3_preview_promotions(self.ay_2026, new_sections)
        step4_commit(2027, ["FIRST"], new_sections, rows, self.admin)

        class_offering.refresh_from_db()
        self.assertIn(self.sec1, class_offering.sections.all())
        self.assertEqual(Section.objects.filter(academic_year=self.ay_2026).count(), 4)


class AYWizardPermissionTests(AYWizardTestBase):
    def test_non_admin_gets_403_on_every_step_url(self):
        instructor = make_user(User.Role.INSTRUCTOR, "not_admin_wizard")
        self.client.force_login(instructor)
        for url_name in (
            "academics:ay_wizard_step1",
            "academics:ay_wizard_step2",
            "academics:ay_wizard_step3",
            "academics:ay_wizard_step4",
        ):
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 403, url_name)


class AYWizardDateValidationTests(AYWizardTestBase):
    """Step 1's optional per-term start/end dates go through the same
    academics.semester_validation rules as SemesterForm: range, within
    the new A.Y.'s two calendar years, no overlap among the terms being
    created together, and a non-blocking duration warning carried to
    step 2. Dates actually land on the created Semester rows in step 4."""

    def _step1(self, **fields):
        self.client.force_login(self.admin)
        data = {
            "start_year": "2027", "terms": ["FIRST", "SECOND"],
            "source_academic_year": self.ay_2026.pk,
        }
        data.update(fields)
        return self.client.post(reverse("academics:ay_wizard_step1"), data)

    def test_end_before_start_is_rejected(self):
        response = self._step1(start_FIRST="2027-12-01", end_FIRST="2027-08-01")
        self.assertContains(response, "End date must be after")
        self.assertNotIn("ay_wizard", self.client.session)

    def test_dates_outside_the_new_academic_year_are_rejected(self):
        response = self._step1(start_FIRST="2026-08-01", end_FIRST="2026-12-15")
        self.assertContains(response, "must fall within")

    def test_valid_dates_proceed_to_step2(self):
        response = self._step1(
            start_FIRST="2027-08-01", end_FIRST="2027-12-15",
            start_SECOND="2028-01-10", end_SECOND="2028-05-30",
        )
        self.assertRedirects(response, reverse("academics:ay_wizard_step2"))
        stashed = self.client.session["ay_wizard"]
        self.assertEqual(list(stashed["term_dates"]["FIRST"]), ["2027-08-01", "2027-12-15"])

    def test_overlapping_terms_in_the_same_run_are_rejected(self):
        response = self._step1(
            start_FIRST="2027-08-01", end_FIRST="2027-12-31",
            start_SECOND="2027-12-01", end_SECOND="2028-04-30",
        )
        self.assertContains(response, "overlap")

    def test_long_semester_warns_but_proceeds(self):
        response = self._step1(start_FIRST="2027-08-01", end_FIRST="2028-04-01")
        self.assertRedirects(response, reverse("academics:ay_wizard_step2"))
        step2 = self.client.get(reverse("academics:ay_wizard_step2"))
        self.assertContains(step2, "longer than 6 months")

    def test_blank_dates_are_allowed(self):
        response = self._step1()
        self.assertRedirects(response, reverse("academics:ay_wizard_step2"))

    def test_step4_commit_applies_dates_to_created_semesters(self):
        from .ay_wizard import step4_commit

        result = step4_commit(
            2027, ["FIRST"], [], [], self.admin,
            term_dates={"FIRST": ("2027-08-01", "2027-12-15")},
        )
        semester = Semester.objects.get(academic_year=result["academic_year"], term="FIRST")
        self.assertEqual(semester.start_date, date(2027, 8, 1))
        self.assertEqual(semester.end_date, date(2027, 12, 15))


class ScopeForHelperTests(TeachingAssignmentTestBase):
    """academics.scoping.scope_for and its companion queryset helpers —
    program-level head covers every major with no head of its own;
    major-level head takes precedence over the program-level catch-all
    for that one major; admin is unrestricted (None sentinel)."""

    def setUp(self):
        super().setUp()
        self.major_eng = Major.objects.create(program=self.program_b, code="ENG", name="English")
        self.major_ss = Major.objects.create(program=self.program_b, code="SS", name="Social Studies")

    def test_admin_scope_is_unrestricted_sentinel(self):
        from .scoping import scope_for

        self.assertIsNone(scope_for(self.admin))

    def test_program_level_head_covers_every_major_with_no_head_of_its_own(self):
        from .scoping import scope_for

        scope = scope_for(self.head_b)
        self.assertIn((self.program_b.id, None), scope)

    def test_major_level_head_takes_precedence_for_their_major(self):
        from .scoping import scope_for

        major_head = make_user(User.Role.PROGRAM_HEAD, "sc_major_head")
        self.major_eng.program_head = major_head
        self.major_eng.save()

        scope = scope_for(major_head)
        self.assertEqual(scope, {(self.program_b.id, self.major_eng.id)})
        # The program-level head (head_b) no longer implicitly covers this
        # major once it has its own head — verified via sections_in_scope.
        from .scoping import sections_in_scope

        eng_section = Section.objects.create(
            program=self.program_b, major=self.major_eng, academic_year=self.ay, year_level=1, name="A"
        )
        self.assertIn(eng_section, sections_in_scope(major_head))
        self.assertNotIn(eng_section, sections_in_scope(self.head_b))

    def test_program_head_with_both_program_and_major_assignment_keeps_both_tuples(self):
        from .scoping import scope_for

        self.major_eng.program_head = self.head_b
        self.major_eng.save()

        scope = scope_for(self.head_b)
        self.assertIn((self.program_b.id, None), scope)
        self.assertIn((self.program_b.id, self.major_eng.id), scope)

    def test_sections_in_scope_includes_majorless_sections_for_program_level_head(self):
        from .scoping import sections_in_scope

        # section_b has no major — program_b's program-level head (head_b) must see it.
        self.assertIn(self.section_b, sections_in_scope(self.head_b))

    def test_non_program_head_user_has_empty_scope(self):
        from .scoping import scope_for

        self.assertEqual(scope_for(self.instructor1), set())

    def test_unassigned_program_head_sees_nothing(self):
        from .scoping import classes_in_scope, sections_in_scope

        unassigned_head = make_user(User.Role.PROGRAM_HEAD, "sc_unassigned")
        self.assertEqual(sections_in_scope(unassigned_head).count(), 0)
        self.assertEqual(classes_in_scope(unassigned_head).count(), 0)

    def test_classes_in_scope_matches_if_any_section_is_in_scope(self):
        from .scoping import classes_in_scope

        self.class_offering.sections.add(self.section_b)
        self.assertIn(self.class_offering, classes_in_scope(self.head_b))

    def test_is_in_scope_membership_check(self):
        from .scoping import is_in_scope

        self.assertTrue(is_in_scope(self.head_b, self.program_b.id, None))
        self.assertFalse(is_in_scope(self.head_a, self.program_b.id, None))
        self.assertTrue(is_in_scope(self.admin, self.program_b.id, None))

    def test_heads_for_class_resolves_major_level_over_program_level(self):
        from .scoping import heads_for_class

        major_head = make_user(User.Role.PROGRAM_HEAD, "sc_heads_for_class")
        self.major_eng.program_head = major_head
        self.major_eng.save()
        eng_section = Section.objects.create(
            program=self.program_b, major=self.major_eng, academic_year=self.ay, year_level=1, name="A"
        )
        self.class_offering.sections.set([eng_section])

        heads = heads_for_class(self.class_offering)
        self.assertEqual(heads, [major_head])

    def test_programs_in_scope_for_program_level_head(self):
        from .scoping import programs_in_scope

        self.assertIn(self.program_b, programs_in_scope(self.head_b))
        self.assertNotIn(self.program_a, programs_in_scope(self.head_b))


class CurriculumScopingHelperTests(TeachingAssignmentTestBase):
    """academics.scoping.curriculum_entries_in_scope / subjects_editable_by
    — built on top of CurriculumEntry rather than fields on Subject
    itself (Subject no longer carries program/major/year_level/term)."""

    def test_curriculum_entries_in_scope_restricted_to_own_program(self):
        from .models import CurriculumEntry
        from .scoping import curriculum_entries_in_scope

        subject = Subject.objects.create(code="CS1", title="X", units=Decimal("3.0"))
        entry_a = CurriculumEntry.objects.create(program=self.program_a, year_level=1, term="FIRST", subject=subject)
        entry_b = CurriculumEntry.objects.create(program=self.program_b, year_level=1, term="FIRST", subject=subject)

        entries = curriculum_entries_in_scope(self.head_b)
        self.assertIn(entry_b, entries)
        self.assertNotIn(entry_a, entries)

    def test_curriculum_entries_in_scope_admin_unrestricted(self):
        from .models import CurriculumEntry
        from .scoping import curriculum_entries_in_scope

        subject = Subject.objects.create(code="CS2", title="X", units=Decimal("3.0"))
        entry_a = CurriculumEntry.objects.create(program=self.program_a, year_level=1, term="FIRST", subject=subject)
        self.assertIn(entry_a, curriculum_entries_in_scope(self.admin))

    def test_subjects_editable_by_excludes_subject_shared_across_programs(self):
        from .models import CurriculumEntry
        from .scoping import subjects_editable_by

        shared = Subject.objects.create(code="SHARED3", title="X", units=Decimal("3.0"))
        CurriculumEntry.objects.create(program=self.program_a, year_level=1, term="FIRST", subject=shared)
        CurriculumEntry.objects.create(program=self.program_b, year_level=1, term="FIRST", subject=shared)
        self.assertNotIn(shared, subjects_editable_by(self.head_b))

    def test_subjects_editable_by_includes_subject_used_solely_in_scope(self):
        from .models import CurriculumEntry
        from .scoping import subjects_editable_by

        exclusive = Subject.objects.create(code="EXCL1", title="X", units=Decimal("3.0"))
        CurriculumEntry.objects.create(program=self.program_b, year_level=1, term="FIRST", subject=exclusive)
        self.assertIn(exclusive, subjects_editable_by(self.head_b))

    def test_subjects_editable_by_excludes_an_unplaced_subject(self):
        from .scoping import subjects_editable_by

        unplaced = Subject.objects.create(code="UNPLACED2", title="X", units=Decimal("3.0"))
        self.assertNotIn(unplaced, subjects_editable_by(self.head_b))

    def test_subjects_editable_by_admin_unrestricted(self):
        from .scoping import subjects_editable_by

        unplaced = Subject.objects.create(code="UNPLACED3", title="X", units=Decimal("3.0"))
        self.assertIn(unplaced, subjects_editable_by(self.admin))


class MajorFormProgramHeadFieldTests(TeachingAssignmentTestBase):
    def test_admin_can_assign_a_major_level_head_via_the_majors_page(self):
        major = Major.objects.create(program=self.program_b, code="ENG", name="English")
        major_head = make_user(User.Role.PROGRAM_HEAD, "major_form_head")
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("academics:major_edit", args=[major.pk]),
            {"program": self.program_b.pk, "code": "ENG", "name": "English", "program_head": major_head.pk, "is_active": "on"},
        )
        self.assertEqual(response.status_code, 204, response.content)
        major.refresh_from_db()
        self.assertEqual(major.program_head, major_head)

    def test_majors_table_renders_program_head_column(self):
        major_head = make_user(User.Role.PROGRAM_HEAD, "major_table_head")
        Major.objects.create(program=self.program_b, code="SS", name="Social Studies", program_head=major_head)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("academics:majors"))
        self.assertContains(response, major_head.full_name)


class ProgramHeadAssignmentNotificationTests(TeachingAssignmentTestBase):
    def test_assigning_a_program_head_notifies_once(self):
        from dashboard.models import Notification

        new_program = Program.objects.create(code="BSCS", name="BS Computer Science")
        unassigned_head = make_user(User.Role.PROGRAM_HEAD, "notif_unassigned_head")
        self.client.force_login(self.admin)

        self.client.post(
            reverse("academics:program_edit", args=[new_program.pk]),
            {"code": "BSCS", "name": "BS Computer Science", "program_head": unassigned_head.pk, "is_active": "on"},
        )
        self.assertEqual(
            Notification.objects.filter(recipient=unassigned_head, title="You've been assigned as Program Head").count(), 1
        )

        # Re-saving with the SAME head must not notify again (no-op guard).
        self.client.post(
            reverse("academics:program_edit", args=[new_program.pk]),
            {"code": "BSCS", "name": "BS Computer Science", "program_head": unassigned_head.pk, "is_active": "on"},
        )
        self.assertEqual(
            Notification.objects.filter(recipient=unassigned_head, title="You've been assigned as Program Head").count(), 1
        )

    def test_assigning_a_major_level_head_notifies(self):
        from dashboard.models import Notification

        major = Major.objects.create(program=self.program_b, code="ENG", name="English")
        major_head = make_user(User.Role.PROGRAM_HEAD, "notif_major_head")
        self.client.force_login(self.admin)

        self.client.post(
            reverse("academics:major_edit", args=[major.pk]),
            {"program": self.program_b.pk, "code": "ENG", "name": "English", "program_head": major_head.pk, "is_active": "on"},
        )
        self.assertTrue(
            Notification.objects.filter(recipient=major_head, title="You've been assigned as Program Head").exists()
        )


class UsersPageScopeDisplayTests(TeachingAssignmentTestBase):
    def test_program_level_head_scope_label(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("accounts:users"), {"role": "PROGRAM_HEAD"})
        self.assertContains(response, "BSED (all majors)")

    def test_major_level_head_scope_label(self):
        major = Major.objects.create(program=self.program_b, code="ENG", name="English")
        major_head = make_user(User.Role.PROGRAM_HEAD, "scope_label_major_head")
        major.program_head = major_head
        major.save()

        self.client.force_login(self.admin)
        response = self.client.get(reverse("accounts:users"), {"role": "PROGRAM_HEAD"})
        self.assertContains(response, "BSED – English")

    def test_unassigned_head_shows_unassigned(self):
        make_user(User.Role.PROGRAM_HEAD, "scope_label_unassigned")
        self.client.force_login(self.admin)
        response = self.client.get(reverse("accounts:users"), {"role": "PROGRAM_HEAD"})
        self.assertContains(response, "Unassigned")


class ProgramHeadSectionScopeTests(TeachingAssignmentTestBase):
    def test_can_create_a_section_in_scope(self):
        self.client.force_login(self.head_b)
        response = self.client.post(
            reverse("academics:ph_section_create"),
            {"program": self.program_b.pk, "major": "", "year_level": "2", "name": "B"},
        )
        self.assertEqual(response.status_code, 204, response.content)
        section = Section.objects.get(program=self.program_b, year_level=2, name="B")
        self.assertEqual(section.academic_year, self.ay)

    def test_create_form_locks_program_choices_to_scope(self):
        self.client.force_login(self.head_b)
        response = self.client.get(reverse("academics:ph_section_create"))
        form = response.context["form"]
        self.assertIn(self.program_b, form.fields["program"].queryset)
        self.assertNotIn(self.program_a, form.fields["program"].queryset)

    def test_cannot_edit_a_section_outside_scope(self):
        self.client.force_login(self.head_a)  # heads program_a, not program_b
        response = self.client.get(reverse("academics:ph_section_edit", args=[self.section_b.pk]))
        self.assertEqual(response.status_code, 403)

    def test_can_edit_a_section_in_scope(self):
        self.client.force_login(self.head_b)
        response = self.client.post(
            reverse("academics:ph_section_edit", args=[self.section_b.pk]),
            {"program": self.program_b.pk, "major": "", "year_level": "3", "name": "A"},
        )
        self.assertEqual(response.status_code, 204, response.content)
        self.section_b.refresh_from_db()
        self.assertEqual(self.section_b.year_level, 3)

    def test_major_level_head_can_create_in_their_major_only(self):
        major = Major.objects.create(program=self.program_b, code="ENG", name="English")
        major_head = make_user(User.Role.PROGRAM_HEAD, "sec_scope_major_head")
        major.program_head = major_head
        major.save()

        self.client.force_login(major_head)
        response = self.client.post(
            reverse("academics:ph_section_create"),
            {"program": self.program_b.pk, "major": major.pk, "year_level": "1", "name": "C"},
        )
        self.assertEqual(response.status_code, 204, response.content)

    def test_section_create_logs_change(self):
        from .models import AcademicSetupChangeLog

        self.client.force_login(self.head_b)
        self.client.post(
            reverse("academics:ph_section_create"),
            {"program": self.program_b.pk, "major": "", "year_level": "2", "name": "D"},
        )
        log = AcademicSetupChangeLog.objects.get(model_name=AcademicSetupChangeLog.ModelName.SECTION)
        self.assertEqual(log.action, AcademicSetupChangeLog.Action.CREATED)
        self.assertFalse(log.is_admin_override)
        self.assertEqual(log.actor, self.head_b)

    def test_no_active_semester_shows_empty_state(self):
        self.semester.is_active = False
        self.semester.save()
        self.client.force_login(self.head_b)
        response = self.client.get(reverse("academics:ph_sections"))
        self.assertContains(response, "No active semester")

    def test_ph_sections_page_only_lists_own_scope(self):
        self.client.force_login(self.head_b)
        response = self.client.get(reverse("academics:ph_sections"))
        self.assertContains(response, str(self.section_b))
        self.assertNotContains(response, str(self.section_a))


class ProgramHeadSubjectScopeTests(TeachingAssignmentTestBase):
    """Subjects prospectus page — curriculum-entry-based scoping. program_a/
    program_b and head_a/head_b come from TeachingAssignmentTestBase (no
    majors — program-level scope only)."""

    def test_can_create_a_subject_tagged_to_own_scope(self):
        self.client.force_login(self.head_b)
        response = self.client.post(
            reverse("academics:subject_add") + f"?program={self.program_b.pk}&year_level=1&term=FIRST",
            {"code": "ENG101", "title": "Intro to Lit", "units": "3.0"},
        )
        self.assertEqual(response.status_code, 204, response.content)
        subject = Subject.objects.get(code="ENG101")
        self.assertTrue(
            CurriculumEntry.objects.filter(subject=subject, program=self.program_b, year_level=1, term="FIRST").exists()
        )

    def test_cannot_add_a_subject_outside_scope(self):
        self.client.force_login(self.head_b)
        response = self.client.post(
            reverse("academics:subject_add") + f"?program={self.program_a.pk}&year_level=1&term=FIRST",
            {"code": "ENG101", "title": "Intro to Lit", "units": "3.0"},
        )
        self.assertEqual(response.status_code, 403)

    def test_any_active_subject_usable_via_existing_subject_mode(self):
        # Confirms the shared-catalog read is unrestricted — any active
        # subject (even one placed only under program_a) can be attached
        # into program_b's curriculum via "use an existing subject".
        subject = Subject.objects.create(code="SHARED1", title="Shared", units=Decimal("3.0"))
        CurriculumEntry.objects.create(program=self.program_a, year_level=1, term="FIRST", subject=subject)
        self.client.force_login(self.head_b)
        response = self.client.post(
            reverse("academics:subject_add") + f"?program={self.program_b.pk}&year_level=1&term=FIRST",
            {"code": subject.code},
        )
        self.assertEqual(response.status_code, 204, response.content)
        self.assertTrue(CurriculumEntry.objects.filter(subject=subject, program=self.program_b).exists())

    def test_shared_subject_appears_under_both_programs_prospectus(self):
        subject = Subject.objects.create(code="SHARED2", title="Shared", units=Decimal("3.0"))
        CurriculumEntry.objects.create(program=self.program_a, year_level=1, term="FIRST", subject=subject)
        CurriculumEntry.objects.create(program=self.program_b, year_level=1, term="FIRST", subject=subject)

        self.client.force_login(self.head_a)
        response = self.client.get(reverse("academics:ph_subjects") + f"?program={self.program_a.pk}")
        self.assertContains(response, "SHARED2")

        self.client.force_login(self.head_b)
        response = self.client.get(reverse("academics:ph_subjects") + f"?program={self.program_b.pk}")
        self.assertContains(response, "SHARED2")

    def test_head_sees_only_their_own_scope_pill(self):
        self.client.force_login(self.head_a)
        response = self.client.get(reverse("academics:ph_subjects"))
        self.assertContains(response, self.program_a.code)
        self.assertNotContains(response, self.program_b.code)

    def test_cannot_edit_a_subject_outside_scope(self):
        subject = Subject.objects.create(code="OUTSCOPE", title="X", units=Decimal("3.0"))
        CurriculumEntry.objects.create(program=self.program_a, year_level=1, term="FIRST", subject=subject)
        self.client.force_login(self.head_b)
        response = self.client.get(reverse("academics:subject_edit", args=[subject.pk]))
        self.assertEqual(response.status_code, 403)

    def test_cannot_edit_a_shared_subject_used_by_more_than_one_program(self):
        shared = Subject.objects.create(code="GE2", title="Gen Ed", units=Decimal("3.0"))
        CurriculumEntry.objects.create(program=self.program_a, year_level=1, term="FIRST", subject=shared)
        CurriculumEntry.objects.create(program=self.program_b, year_level=1, term="FIRST", subject=shared)
        self.client.force_login(self.head_b)
        response = self.client.get(reverse("academics:subject_edit", args=[shared.pk]))
        self.assertEqual(response.status_code, 403)

    def test_cannot_edit_a_subject_with_no_curriculum_entry_at_all(self):
        unplaced = Subject.objects.create(code="UNPLACED1", title="X", units=Decimal("3.0"))
        self.client.force_login(self.head_b)
        response = self.client.get(reverse("academics:subject_edit", args=[unplaced.pk]))
        self.assertEqual(response.status_code, 403)

    def test_can_edit_a_subject_used_solely_in_own_scope(self):
        subject = Subject.objects.create(code="INSCOPE", title="X", units=Decimal("3.0"))
        CurriculumEntry.objects.create(program=self.program_b, year_level=1, term="FIRST", subject=subject)
        self.client.force_login(self.head_b)
        response = self.client.post(
            reverse("academics:subject_edit", args=[subject.pk]),
            {"code": "INSCOPE", "title": "Updated Title", "units": "3.0"},
        )
        self.assertEqual(response.status_code, 204, response.content)
        subject.refresh_from_db()
        self.assertEqual(subject.title, "Updated Title")

    def test_remove_from_curriculum_deletes_entry_not_subject(self):
        subject = Subject.objects.create(code="REMOVEME", title="X", units=Decimal("3.0"))
        entry = CurriculumEntry.objects.create(program=self.program_b, year_level=1, term="FIRST", subject=subject)
        self.client.force_login(self.head_b)
        response = self.client.post(reverse("academics:subject_remove_from_curriculum", args=[entry.pk]))
        self.assertEqual(response.status_code, 204, response.content)
        self.assertFalse(CurriculumEntry.objects.filter(pk=entry.pk).exists())
        self.assertTrue(Subject.objects.filter(pk=subject.pk).exists())

    def test_remove_from_curriculum_blocked_if_an_active_semester_class_uses_it(self):
        subject = Subject.objects.create(code="INUSE", title="X", units=Decimal("3.0"))
        entry = CurriculumEntry.objects.create(program=self.program_b, year_level=1, term="FIRST", subject=subject)
        class_offering = ClassOffering.objects.create(subject=subject, semester=self.semester)
        class_offering.sections.set([self.section_b])
        self.client.force_login(self.head_b)
        response = self.client.post(reverse("academics:subject_remove_from_curriculum", args=[entry.pk]))
        self.assertEqual(response.status_code, 200)  # re-rendered, blocked
        self.assertTrue(CurriculumEntry.objects.filter(pk=entry.pk).exists())

    def test_tcp_style_program_groups_without_year_level_cards(self):
        subject = Subject.objects.create(code="TCPSUBJ", title="TCP Subject", units=Decimal("3.0"))
        CurriculumEntry.objects.create(program=self.program_b, year_level=None, term="FIRST", subject=subject)
        self.client.force_login(self.head_b)
        response = self.client.get(reverse("academics:ph_subjects") + f"?program={self.program_b.pk}")
        self.assertContains(response, "TCPSUBJ")
        self.assertNotContains(response, "1st Year")


class ProgramHeadClassScopeTests(TeachingAssignmentTestBase):
    def setUp(self):
        super().setUp()
        self.subject = Subject.objects.create(code="PEd300", title="Phys Ed 3", units=Decimal("2.0"))

    def test_can_create_a_class_with_own_sections(self):
        self.client.force_login(self.head_b)
        response = self.client.post(
            reverse("academics:ph_class_create"),
            {"subject": self.subject.pk, "sections": [self.section_b.pk], "schedule": "", "room": "", "instructor": "", "is_active": "on"},
        )
        self.assertEqual(response.status_code, 204, response.content)
        new_class = ClassOffering.objects.get(subject=self.subject)
        self.assertIn(self.section_b, new_class.sections.all())
        self.assertEqual(new_class.semester, self.semester)

    def test_cannot_create_a_class_with_another_heads_section(self):
        self.client.force_login(self.head_b)
        response = self.client.post(
            reverse("academics:ph_class_create"),
            {"subject": self.subject.pk, "sections": [self.section_a.pk], "schedule": "", "room": "", "instructor": "", "is_active": "on"},
        )
        self.assertEqual(response.status_code, 200)  # re-rendered with a validation error
        self.assertFalse(ClassOffering.objects.filter(subject=self.subject).exists())

    def test_cannot_edit_a_class_with_no_section_in_scope(self):
        other_class = ClassOffering.objects.create(subject=self.subject, semester=self.semester)
        other_class.sections.set([self.section_a])
        self.client.force_login(self.head_b)
        response = self.client.get(reverse("academics:ph_class_edit", args=[other_class.pk]))
        self.assertEqual(response.status_code, 403)

    def test_instructor_change_on_edit_is_logged_via_the_normal_mechanism(self):
        from dashboard.models import Notification

        self.class_offering.sections.set([self.section_b])
        self.client.force_login(self.head_b)
        response = self.client.post(
            reverse("academics:ph_class_edit", args=[self.class_offering.pk]),
            {"subject": self.subject.pk, "sections": [self.section_b.pk], "schedule": "", "room": "", "instructor": self.instructor1.pk, "is_active": "on"},
        )
        self.assertEqual(response.status_code, 204, response.content)
        self.class_offering.refresh_from_db()
        self.assertEqual(self.class_offering.instructor, self.instructor1)
        self.assertTrue(Notification.objects.filter(recipient=self.instructor1, title="New teaching assignment").exists())
        log = self.class_offering.assignment_logs.get()
        self.assertFalse(log.is_admin_override)

    def test_class_create_logs_academic_setup_change(self):
        from .models import AcademicSetupChangeLog

        self.client.force_login(self.head_b)
        self.client.post(
            reverse("academics:ph_class_create"),
            {"subject": self.subject.pk, "sections": [self.section_b.pk], "schedule": "", "room": "", "instructor": "", "is_active": "on"},
        )
        log = AcademicSetupChangeLog.objects.get(model_name=AcademicSetupChangeLog.ModelName.CLASS)
        self.assertEqual(log.action, AcademicSetupChangeLog.Action.CREATED)
        self.assertFalse(log.is_admin_override)


class SharedClassJoinLeaveTests(TeachingAssignmentTestBase):
    """Two Program Heads sharing one class (same subject, different
    sections) — head_a creates it, head_b joins with their own section,
    either can leave independently."""

    def setUp(self):
        super().setUp()
        self.class_offering.sections.set([self.section_a])  # starts as head_a's alone

    def test_other_head_can_join_with_their_own_section(self):
        self.client.force_login(self.head_b)
        response = self.client.post(
            reverse("academics:ph_class_join"),
            {"class_offering": self.class_offering.pk, "sections": [self.section_b.pk]},
        )
        self.assertEqual(response.status_code, 204, response.content)
        self.class_offering.refresh_from_db()
        self.assertIn(self.section_b, self.class_offering.sections.all())
        self.assertIn(self.section_a, self.class_offering.sections.all())  # head_a's section untouched

    def test_cannot_join_with_another_heads_section(self):
        self.client.force_login(self.head_b)
        response = self.client.post(
            reverse("academics:ph_class_join"),
            {"class_offering": self.class_offering.pk, "sections": [self.section_a.pk]},
        )
        self.assertEqual(response.status_code, 200)  # section_a isn't in head_b's own-sections queryset -> invalid choice
        self.assertEqual(list(self.class_offering.sections.all()), [self.section_a])

    def test_join_is_logged(self):
        from .models import AcademicSetupChangeLog

        self.client.force_login(self.head_b)
        self.client.post(
            reverse("academics:ph_class_join"),
            {"class_offering": self.class_offering.pk, "sections": [self.section_b.pk]},
        )
        log = AcademicSetupChangeLog.objects.get(action=AcademicSetupChangeLog.Action.SECTION_JOINED)
        self.assertEqual(log.actor, self.head_b)

    def test_leaving_removes_only_own_sections(self):
        self.class_offering.sections.add(self.section_b)
        self.client.force_login(self.head_b)
        response = self.client.post(reverse("academics:ph_class_leave", args=[self.class_offering.pk]))
        self.assertEqual(response.status_code, 204, response.content)
        self.class_offering.refresh_from_db()
        self.assertNotIn(self.section_b, self.class_offering.sections.all())
        self.assertIn(self.section_a, self.class_offering.sections.all())  # head_a's stays
        self.assertTrue(self.class_offering.is_active)  # still has head_a's section

    def test_last_section_leaving_deactivates_the_class(self):
        from .models import AcademicSetupChangeLog

        self.client.force_login(self.head_a)
        response = self.client.post(reverse("academics:ph_class_leave", args=[self.class_offering.pk]))
        self.assertEqual(response.status_code, 204, response.content)
        self.class_offering.refresh_from_db()
        self.assertEqual(self.class_offering.sections.count(), 0)
        self.assertFalse(self.class_offering.is_active)
        self.assertTrue(
            AcademicSetupChangeLog.objects.filter(
                action=AcademicSetupChangeLog.Action.DEACTIVATED, details__reason="last section removed"
            ).exists()
        )

    def test_cannot_leave_a_class_with_no_own_section(self):
        self.client.force_login(self.head_b)  # has no section in this class yet
        response = self.client.get(reverse("academics:ph_class_leave", args=[self.class_offering.pk]))
        self.assertEqual(response.status_code, 403)

    def test_leave_blocked_when_grade_sheet_submitted(self):
        self.make_submitted_sheet(self.class_offering)
        self.client.force_login(self.head_a)
        get_response = self.client.get(reverse("academics:ph_class_leave", args=[self.class_offering.pk]))
        self.assertContains(get_response, "already has scores or a submitted grade sheet")

        post_response = self.client.post(reverse("academics:ph_class_leave", args=[self.class_offering.pk]))
        self.assertEqual(post_response.status_code, 200)
        self.class_offering.refresh_from_db()
        self.assertIn(self.section_a, self.class_offering.sections.all())


class ProgramHeadClassListsScopeTests(TeachingAssignmentTestBase):
    """Class Lists page + roster actions, scoped via _can_manage_roster."""

    def setUp(self):
        super().setUp()
        self.class_offering.sections.set([self.section_a])
        self.student = make_user(User.Role.STUDENT, "ph_cl_student")
        self.entry = ClassRosterEntry.objects.create(student=self.student, class_offering=self.class_offering)

    def test_head_can_view_class_lists_for_own_class(self):
        self.client.force_login(self.head_a)
        response = self.client.get(reverse("academics:class_lists") + f"?class={self.class_offering.pk}")
        self.assertEqual(response.status_code, 200)

    def test_other_head_gets_404_picking_class_outside_scope(self):
        self.client.force_login(self.head_b)
        response = self.client.get(reverse("academics:class_lists") + f"?class={self.class_offering.pk}")
        self.assertEqual(response.status_code, 404)

    def test_other_head_cannot_mark_dropped_outside_scope(self):
        self.client.force_login(self.head_b)
        response = self.client.post(reverse("academics:class_list_mark_dropped", args=[self.entry.pk]))
        self.assertEqual(response.status_code, 403)

    def test_other_head_cannot_add_section_outside_scope(self):
        self.client.force_login(self.head_b)
        response = self.client.post(
            reverse("academics:class_list_add_section", args=[self.class_offering.pk]),
            {"section": self.section_a.pk},
        )
        self.assertEqual(response.status_code, 403)

    def test_own_head_can_mark_dropped(self):
        self.client.force_login(self.head_a)
        response = self.client.post(reverse("academics:class_list_mark_dropped", args=[self.entry.pk]))
        self.assertEqual(response.status_code, 200)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, ClassRosterEntry.Status.DROPPED)

    def test_class_search_scoped_to_own_classes(self):
        other_class = ClassOffering.objects.create(subject=self.subject, semester=self.semester)
        other_class.sections.set([self.section_b])
        self.client.force_login(self.head_a)
        response = self.client.get(reverse("academics:class_search"))
        self.assertContains(response, str(self.class_offering))
        self.assertNotContains(response, str(other_class))


class ProgramHeadImportOfferingsScopeTests(TestCase):
    """Import Class Offerings — rows outside a Program Head's scope are
    rejected in preview with a reason; admin stays unrestricted."""

    def setUp(self):
        self.ay = AcademicYear.objects.create(start_year=2026)
        self.semester = Semester.objects.create(academic_year=self.ay, term=Term.FIRST, is_active=True)
        self.program = Program.objects.create(code="BSED", name="BS Secondary Education")
        self.major = Major.objects.create(program=self.program, code="ENG", name="English")
        Section.objects.create(program=self.program, major=self.major, academic_year=self.ay, year_level=1, name="")
        self.other_program = Program.objects.create(code="BSIT", name="BS IT")
        Section.objects.create(program=self.other_program, academic_year=self.ay, year_level=1, name="")

        self.head = make_user(User.Role.PROGRAM_HEAD, "ph_import_head")
        self.major.program_head = self.head
        self.major.save()

    def _index(self):
        return {
            "semester": 0, "program": 1, "major": 2, "year level": 3, "course code": 4,
            "description": 5, "units": 6, "room": 7, "schedule": 8, "instructor": 9,
        }

    def test_row_outside_scope_is_rejected_with_reason(self):
        from .offerings_import import build_offerings_preview

        rows = [("FIRST", "BSIT", "", "1", "IT101", "Programming 1", "3", "", "", "")]
        preview = build_offerings_preview(self._index(), rows, self.semester, user=self.head)
        self.assertEqual(preview["invalid_count"], 1)
        self.assertIn("outside your scope", preview["rows"][0]["reason"])

    def test_row_in_scope_is_accepted(self):
        from .offerings_import import build_offerings_preview

        rows = [("FIRST", "BSED", "ENG", "1", "ENG201", "Lit 201", "3", "", "", "")]
        preview = build_offerings_preview(self._index(), rows, self.semester, user=self.head)
        self.assertEqual(preview["invalid_count"], 0)
        self.assertEqual(preview["new_class_count"], 1)

    def test_admin_unrestricted_by_default(self):
        from .offerings_import import build_offerings_preview

        rows = [("FIRST", "BSIT", "", "1", "IT102", "Programming 2", "3", "", "", "")]
        preview = build_offerings_preview(self._index(), rows, self.semester)
        self.assertEqual(preview["invalid_count"], 0)

    def test_commit_rejects_out_of_scope_rows_defensively(self):
        from .offerings_import import commit_offerings_import

        other_section = Section.objects.get(program=self.other_program)
        classes = [
            {
                "code": "IT103", "description": "Programming 3", "units": "3", "room": "", "schedule": "",
                "instructor_name": "", "program_ids": [self.other_program.id], "section_ids": [other_section.id],
                "matched_instructor_id": None,
            },
        ]
        with self.assertRaises(PermissionDenied):
            commit_offerings_import(classes, self.semester, user=self.head)
        self.assertFalse(Subject.objects.filter(code="IT103").exists())

    def test_non_admin_can_reach_import_page(self):
        self.client.force_login(self.head)
        response = self.client.get(reverse("academics:offerings_import"))
        self.assertEqual(response.status_code, 200)


class AdminOverrideAuditTests(TeachingAssignmentTestBase):
    """Admin editing Sections/Subjects/Classes through the Override menu
    group is logged as an admin override; a Program Head editing their
    own scope is not. Both surface, correctly labeled, on the Audit Log
    page (accounts.audit.collect_audit_rows)."""

    def test_admin_section_edit_logs_override(self):
        from .models import AcademicSetupChangeLog

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("academics:section_edit", args=[self.section_a.pk]),
            {"program": self.program_a.pk, "major": "", "academic_year": self.ay.pk, "year_level": "2", "name": "A"},
        )
        self.assertEqual(response.status_code, 204, response.content)
        log = AcademicSetupChangeLog.objects.get(
            model_name=AcademicSetupChangeLog.ModelName.SECTION, object_id=self.section_a.pk
        )
        self.assertTrue(log.is_admin_override)
        self.assertEqual(log.actor, self.admin)

    def test_program_head_section_edit_is_not_an_override(self):
        from .models import AcademicSetupChangeLog

        self.client.force_login(self.head_a)
        self.client.post(
            reverse("academics:ph_section_edit", args=[self.section_a.pk]),
            {"program": self.program_a.pk, "major": "", "year_level": "2", "name": "A"},
        )
        log = AcademicSetupChangeLog.objects.get(
            model_name=AcademicSetupChangeLog.ModelName.SECTION, object_id=self.section_a.pk
        )
        self.assertFalse(log.is_admin_override)

    def test_admin_subject_edit_logs_override(self):
        from .models import AcademicSetupChangeLog

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("academics:subject_edit", args=[self.subject.pk]),
            {"code": self.subject.code, "title": self.subject.title, "units": "2.0", "is_active": "on"},
        )
        self.assertEqual(response.status_code, 204, response.content)
        log = AcademicSetupChangeLog.objects.get(
            model_name=AcademicSetupChangeLog.ModelName.SUBJECT, object_id=self.subject.pk
        )
        self.assertTrue(log.is_admin_override)

    def test_admin_class_edit_logs_override(self):
        from .models import AcademicSetupChangeLog

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("academics:class_edit", args=[self.class_offering.pk]),
            {
                "subject": self.subject.pk, "sections": [self.section_a.pk], "semester": self.semester.pk,
                "instructor": "", "schedule": "", "room": "", "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 204, response.content)
        log = AcademicSetupChangeLog.objects.get(
            model_name=AcademicSetupChangeLog.ModelName.CLASS, object_id=self.class_offering.pk
        )
        self.assertTrue(log.is_admin_override)

    def test_override_shows_correctly_labeled_on_audit_log_page(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse("academics:section_edit", args=[self.section_a.pk]),
            {"program": self.program_a.pk, "major": "", "academic_year": self.ay.pk, "year_level": "2", "name": "A"},
        )
        response = self.client.get(reverse("accounts:audit_log"))
        self.assertContains(response, "admin override")


class LoadCitciCurriculumCommandTests(TestCase):
    """load_citci_curriculum — idempotent Subject/CurriculumEntry loading
    from parse_docx's row shape, conflict/near-duplicate/unit-jump
    detection, never auto-merging. Patches parse_docx itself rather than
    needing a real .docx fixture — the row shape is the documented
    contract both this command and import_offerings_docx.py share.

    BASE_DIR is overridden to a scratch temp directory for every test
    here — `_write_data_issues` writes to a REAL file
    (`<BASE_DIR>/docs/source/DATA_ISSUES.md`), not something Django's
    TestCase's database-only isolation touches; without this override,
    running this test class would clobber the project's actual
    DATA_ISSUES.md with test-fixture content every time the suite runs
    (caught the hard way — it happened to the real file this session)."""

    def setUp(self):
        import tempfile
        from pathlib import Path

        from django.test import override_settings

        self.bsed = Program.objects.create(code="BSED", name="BS Secondary Education", is_active=True)
        self.tcp = Program.objects.create(code="TCP", name="Teacher Certificate Program", is_active=True)
        self.eng = Major.objects.create(program=self.bsed, code="ENG", name="English")
        self.tmp_path = None

        self._tmp_base_dir = tempfile.mkdtemp()
        (Path(self._tmp_base_dir) / "docs" / "source").mkdir(parents=True)
        self._override = override_settings(BASE_DIR=self._tmp_base_dir)
        self._override.enable()
        self.addCleanup(self._override.disable)

    def _dummy_docx_path(self):
        import tempfile

        f = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
        f.write(b"placeholder")
        f.close()
        self.tmp_path = f.name
        return f.name

    def _run(self, rows):
        from unittest.mock import patch

        from django.core.management import call_command

        path = self._dummy_docx_path()
        with patch("academics.management.commands.load_citci_curriculum.parse_docx", return_value=rows):
            call_command("load_citci_curriculum", path, stdout=StringIO())

    def _row(self, **overrides):
        row = {
            "semester": "FIRST", "program": "BSED", "major": "English", "year_level": 1,
            "code": "ENG101", "description": "Intro to Lit", "units": "3", "instructor": "",
            "room": "", "schedule": "",
        }
        row.update(overrides)
        return row

    def test_creates_subject_and_curriculum_entry(self):
        self._run([self._row()])
        subject = Subject.objects.get(code="ENG101")
        self.assertEqual(subject.title, "Intro to Lit")
        self.assertTrue(
            CurriculumEntry.objects.filter(subject=subject, program=self.bsed, major=self.eng, year_level=1, term="FIRST").exists()
        )

    def test_idempotent_on_rerun(self):
        rows = [self._row()]
        self._run(rows)
        self._run(rows)
        self.assertEqual(Subject.objects.filter(code="ENG101").count(), 1)
        self.assertEqual(CurriculumEntry.objects.filter(subject__code="ENG101").count(), 1)

    def test_shared_subject_across_majors_gets_two_entries_one_subject(self):
        ss = Major.objects.create(program=self.bsed, code="SS", name="Social Studies")
        self._run(
            [
                self._row(major="English"),
                self._row(major="Social Studies"),
            ]
        )
        self.assertEqual(Subject.objects.filter(code="ENG101").count(), 1)
        self.assertEqual(CurriculumEntry.objects.filter(subject__code="ENG101").count(), 2)
        self.assertTrue(CurriculumEntry.objects.filter(subject__code="ENG101", major=ss).exists())

    def test_exact_code_conflict_keeps_first_seen_bsed_value(self):
        self._run(
            [
                self._row(code="PEd207", description="Assessment in Learning 2", units="3"),
                self._row(program="TCP", major=None, year_level=None, description="Assessment Learning 2", code="PEd207", units="3"),
            ]
        )
        subject = Subject.objects.get(code="PEd207")
        self.assertEqual(subject.title, "Assessment in Learning 2")

    def test_near_duplicate_codes_are_not_merged(self):
        self._run(
            [
                self._row(code="PEd 205", description="Facilitating Learning"),
                self._row(program="TCP", major=None, year_level=None, code="PEd 205 Elec", description="Facilitating Learning"),
            ]
        )
        self.assertTrue(Subject.objects.filter(code="PEd 205").exists())
        self.assertTrue(Subject.objects.filter(code="PEd 205 Elec").exists())
        issues = (Path(settings.BASE_DIR) / "docs" / "source" / "DATA_ISSUES.md").read_text(encoding="utf-8")
        self.assertIn("PEd 205", issues)
        self.assertIn("Possible duplicate codes", issues)

    def test_unknown_program_is_skipped_not_guessed(self):
        self._run([self._row(program="NOPE", major=None)])
        self.assertFalse(Subject.objects.filter(code="ENG101").exists() and CurriculumEntry.objects.filter(subject__code="ENG101").exists())

    def test_data_issues_section_is_replaced_not_duplicated_on_rerun(self):
        rows = [self._row(code="PEd 205"), self._row(program="TCP", major=None, year_level=None, code="PEd 205 Elec")]
        self._run(rows)
        self._run(rows)
        issues = (Path(settings.BASE_DIR) / "docs" / "source" / "DATA_ISSUES.md").read_text(encoding="utf-8")
        self.assertEqual(issues.count("## Curriculum loading issues"), 1)

    def tearDown(self):
        if self.tmp_path and os.path.exists(self.tmp_path):
            os.unlink(self.tmp_path)


class AdminSubjectsProspectusTests(TeachingAssignmentTestBase):
    """Admin's Subjects page — same prospectus layout as the Program Head
    page, but with a program/major selector covering everything and full
    edit rights (including code) regardless of sharing."""

    def test_admin_can_view_any_program_major_prospectus(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("academics:subjects") + f"?program={self.program_a.pk}")
        self.assertEqual(response.status_code, 200)

    def test_admin_can_edit_a_shared_subjects_code(self):
        shared = Subject.objects.create(code="ADMINSHARED", title="X", units=Decimal("3.0"))
        CurriculumEntry.objects.create(program=self.program_a, year_level=1, term="FIRST", subject=shared)
        CurriculumEntry.objects.create(program=self.program_b, year_level=1, term="FIRST", subject=shared)
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("academics:subject_edit", args=[shared.pk]),
            {"code": "ADMINSHARED2", "title": "X", "units": "3.0", "is_active": "on"},
        )
        self.assertEqual(response.status_code, 204, response.content)
        shared.refresh_from_db()
        self.assertEqual(shared.code, "ADMINSHARED2")

    def test_admin_add_subject_logs_override(self):
        from .models import AcademicSetupChangeLog

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("academics:subject_add") + f"?program={self.program_a.pk}&year_level=1&term=FIRST",
            {"code": "ADMINNEW1", "title": "X", "units": "3.0"},
        )
        self.assertEqual(response.status_code, 204, response.content)
        log = AcademicSetupChangeLog.objects.get(object_repr="ADMINNEW1")
        self.assertTrue(log.is_admin_override)


class CurriculumAwareSubjectSuggestionTests(TeachingAssignmentTestBase):
    """Class-creation subject picker groups curriculum-matched subjects
    first ("From the curriculum"), falling back to one ungrouped list
    when nothing is selected yet."""

    def test_curriculum_matched_subject_suggested_first(self):
        from .forms import _grouped_subject_choices

        matched = Subject.objects.create(code="MATCH1", title="X", units=Decimal("3.0"))
        unmatched = Subject.objects.create(code="NOMATCH1", title="Y", units=Decimal("3.0"))
        CurriculumEntry.objects.create(
            program=self.section_a.program, major=self.section_a.major, year_level=self.section_a.year_level,
            term="FIRST", subject=matched,
        )
        choices = _grouped_subject_choices([self.section_a], term="FIRST")
        self.assertEqual(choices[0][0], "From the curriculum")
        suggested_ids = {pk for pk, _ in choices[0][1]}
        self.assertIn(matched.pk, suggested_ids)
        self.assertNotIn(unmatched.pk, suggested_ids)

    def test_no_sections_falls_back_to_ungrouped_list(self):
        from .forms import _grouped_subject_choices

        Subject.objects.create(code="ANY1", title="X", units=Decimal("3.0"))
        choices = _grouped_subject_choices([])
        self.assertTrue(all(isinstance(c[0], int) for c in choices))

    def test_live_regroup_on_class_create_get_with_sections_param(self):
        matched = Subject.objects.create(code="LIVEMATCH1", title="X", units=Decimal("3.0"))
        CurriculumEntry.objects.create(
            program=self.section_b.program, major=self.section_b.major, year_level=self.section_b.year_level,
            term="FIRST", subject=matched,
        )
        self.client.force_login(self.head_b)
        response = self.client.get(reverse("academics:ph_class_create") + f"?sections={self.section_b.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "From the curriculum")
        self.assertContains(response, "hx-get")


class SubjectsFilterTests(TeachingAssignmentTestBase):
    """Subjects prospectus: major-only pills (program-level pill dropped
    once a program has majors), semester + year-level segmented filters,
    URL persistence, and the subject-count/total-units summary."""

    def setUp(self):
        super().setUp()
        self.major_eng = Major.objects.create(program=self.program_b, code="ENG", name="English")
        self.major_eng.program_head = self.head_b
        self.major_eng.save()

    def test_program_with_majors_hides_program_level_pill(self):
        self.client.force_login(self.head_b)
        response = self.client.get(reverse("academics:ph_subjects"))
        self.assertContains(response, "English")
        self.assertNotContains(response, f">{self.program_b.code}<")

    def test_program_without_majors_shows_program_pill(self):
        self.client.force_login(self.head_a)  # program_a has no majors
        response = self.client.get(reverse("academics:ph_subjects"))
        self.assertContains(response, self.program_a.code)

    def test_semester_filter_defaults_to_active_semester_term(self):
        first_subject = Subject.objects.create(code="SEMFIRST1", title="X", units=Decimal("3.0"))
        second_subject = Subject.objects.create(code="SEMSECOND1", title="Y", units=Decimal("3.0"))
        CurriculumEntry.objects.create(program=self.program_b, major=self.major_eng, year_level=1, term="FIRST", subject=first_subject)
        CurriculumEntry.objects.create(program=self.program_b, major=self.major_eng, year_level=1, term="SECOND", subject=second_subject)

        self.client.force_login(self.head_b)
        response = self.client.get(reverse("academics:ph_subjects") + f"?major={self.major_eng.pk}")
        self.assertContains(response, "SEMFIRST1")
        self.assertNotContains(response, "SEMSECOND1")

    def test_semester_dropdown_is_the_only_term_control(self):
        """The old "All / 1st Sem / 2nd Sem" pill row is gone -- the
        Academic Year + Semester dropdown pair is the only way to change
        which term's curriculum is listed now; a stray ?term= param in the
        URL is simply ignored."""
        first_subject = Subject.objects.create(code="SEMFIRST2", title="X", units=Decimal("3.0"))
        second_subject = Subject.objects.create(code="SEMSECOND2", title="Y", units=Decimal("3.0"))
        CurriculumEntry.objects.create(program=self.program_b, major=self.major_eng, year_level=1, term="FIRST", subject=first_subject)
        CurriculumEntry.objects.create(program=self.program_b, major=self.major_eng, year_level=1, term="SECOND", subject=second_subject)

        self.client.force_login(self.head_b)
        response = self.client.get(reverse("academics:ph_subjects") + f"?major={self.major_eng.pk}&term=ALL")
        self.assertContains(response, "SEMFIRST2")
        self.assertNotContains(response, "SEMSECOND2")
        self.assertNotContains(response, ">All<")

    def test_year_level_filter_hidden_when_no_year_levels(self):
        subject = Subject.objects.create(code="NOYRLVL1", title="X", units=Decimal("3.0"))
        CurriculumEntry.objects.create(program=self.program_a, year_level=None, term="FIRST", subject=subject)
        self.client.force_login(self.head_a)
        response = self.client.get(reverse("academics:ph_subjects") + f"?program={self.program_a.pk}")
        self.assertNotContains(response, "All Years")

    def test_year_level_filter_narrows_cards(self):
        year1_subject = Subject.objects.create(code="YR1SUBJ1", title="X", units=Decimal("3.0"))
        year2_subject = Subject.objects.create(code="YR2SUBJ1", title="Y", units=Decimal("3.0"))
        CurriculumEntry.objects.create(program=self.program_b, major=self.major_eng, year_level=1, term="FIRST", subject=year1_subject)
        CurriculumEntry.objects.create(program=self.program_b, major=self.major_eng, year_level=2, term="FIRST", subject=year2_subject)

        self.client.force_login(self.head_b)
        response = self.client.get(
            reverse("academics:ph_subjects") + f"?major={self.major_eng.pk}&term=FIRST&year_level=1"
        )
        self.assertContains(response, "YR1SUBJ1")
        self.assertNotContains(response, "YR2SUBJ1")

    def test_subject_count_and_total_units_summary(self):
        s1 = Subject.objects.create(code="SUMUNITS1", title="X", units=Decimal("3.0"))
        s2 = Subject.objects.create(code="SUMUNITS2", title="Y", units=Decimal("2.0"))
        CurriculumEntry.objects.create(program=self.program_b, major=self.major_eng, year_level=1, term="FIRST", subject=s1)
        CurriculumEntry.objects.create(program=self.program_b, major=self.major_eng, year_level=1, term="FIRST", subject=s2)

        self.client.force_login(self.head_b)
        response = self.client.get(
            reverse("academics:ph_subjects") + f"?major={self.major_eng.pk}&term=FIRST&year_level=1"
        )
        self.assertContains(response, "2 subjects")
        self.assertContains(response, "5.0 units")

    def test_filters_persist_across_pill_switch(self):
        major_ss = Major.objects.create(program=self.program_b, code="SS", name="Social Studies")
        major_ss.program_head = self.head_b
        major_ss.save()
        self.client.force_login(self.head_b)
        response = self.client.get(reverse("academics:ph_subjects") + "?term=SECOND&year_level=2")
        self.assertContains(response, f"term=SECOND")
        self.assertContains(response, f"year_level=2")


class AddSubjectDuplicateCheckTests(TeachingAssignmentTestBase):
    """Add Subject modal: single form, server-side duplicate blocking
    (a subject can only sit once per program/major, period — not once
    per year/term slot), case/spacing-insensitive code matching, and the
    search dropdown's ordering/tagging."""

    def _add(self, user, program, year_level, term, **data):
        self.client.force_login(user)
        return self.client.post(
            reverse("academics:subject_add") + f"?program={program.pk}&year_level={year_level}&term={term}",
            data,
        )

    def test_duplicate_in_exact_same_slot_blocked(self):
        subject = Subject.objects.create(code="DUP1", title="X", units=Decimal("3.0"))
        CurriculumEntry.objects.create(program=self.program_b, year_level=1, term="FIRST", subject=subject)
        response = self._add(self.head_b, self.program_b, 1, "FIRST", code="DUP1")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already in 1st Year")

    def test_duplicate_elsewhere_in_same_program_blocked(self):
        subject = Subject.objects.create(code="DUP2", title="X", units=Decimal("3.0"))
        CurriculumEntry.objects.create(program=self.program_b, year_level=1, term="FIRST", subject=subject)
        response = self._add(self.head_b, self.program_b, 2, "SECOND", code="DUP2")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Remove it there first")
        self.assertEqual(CurriculumEntry.objects.filter(subject=subject).count(), 1)

    def test_case_and_spacing_insensitive_code_match_reuses_existing_subject(self):
        Subject.objects.create(code="EL 100", title="Original Title", units=Decimal("3.0"))
        response = self._add(self.head_b, self.program_b, 1, "FIRST", code="el100", title="Different", units="5.0")
        self.assertEqual(response.status_code, 204, response.content)
        self.assertEqual(Subject.objects.filter(code__iexact="EL 100").count(), 1)
        subject = Subject.objects.get(code="EL 100")
        self.assertEqual(subject.title, "Original Title")  # not overwritten by the (ignored) new-mode fields
        self.assertEqual(subject.units, Decimal("3.0"))

    def test_new_subject_created_when_no_match(self):
        response = self._add(self.head_b, self.program_b, 1, "FIRST", code="BRANDNEW1", title="Brand New", units="4.0")
        self.assertEqual(response.status_code, 204, response.content)
        subject = Subject.objects.get(code="BRANDNEW1")
        self.assertEqual(subject.title, "Brand New")

    def test_new_subject_without_title_units_is_rejected(self):
        response = self._add(self.head_b, self.program_b, 1, "FIRST", code="BRANDNEW2")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Required for a new subject")
        self.assertFalse(Subject.objects.filter(code="BRANDNEW2").exists())

    def test_search_results_tag_already_added_subject_as_disabled(self):
        subject = Subject.objects.create(code="TAGGED1", title="X", units=Decimal("3.0"))
        CurriculumEntry.objects.create(program=self.program_b, year_level=1, term="FIRST", subject=subject)
        self.client.force_login(self.head_b)
        response = self.client.get(
            reverse("academics:subject_add") + f"?program={self.program_b.pk}&year_level=2&term=FIRST&code=TAGGED"
        )
        self.assertContains(response, "Already in 1st Year")

    def test_search_results_order_same_scope_first(self):
        same_scope = Subject.objects.create(code="ORDERA1", title="Same scope", units=Decimal("3.0"))
        other_scope = Subject.objects.create(code="ORDERA2", title="Other scope", units=Decimal("3.0"))
        CurriculumEntry.objects.create(program=self.program_b, year_level=2, term="FIRST", subject=same_scope)
        CurriculumEntry.objects.create(program=self.program_a, year_level=1, term="FIRST", subject=other_scope)
        self.client.force_login(self.head_b)
        response = self.client.get(
            reverse("academics:subject_add") + f"?program={self.program_b.pk}&year_level=1&term=FIRST&code=ORDERA"
        )
        content = response.content.decode()
        self.assertLess(content.index("ORDERA1"), content.index("ORDERA2"))


class EditSubjectCodeTests(TeachingAssignmentTestBase):
    """Edit Subject: code is now editable (title/units too), gated by
    the same scope rule, with uniqueness checking and a released-grades
    block that only Admin can bypass (via "Correct code", logged)."""

    def test_code_edit_uniqueness_blocked(self):
        Subject.objects.create(code="TAKEN1", title="X", units=Decimal("3.0"))
        subject = Subject.objects.create(code="FREE1", title="Y", units=Decimal("3.0"))
        CurriculumEntry.objects.create(program=self.program_b, year_level=1, term="FIRST", subject=subject)
        self.client.force_login(self.head_b)
        response = self.client.post(
            reverse("academics:subject_edit", args=[subject.pk]),
            {"code": "taken1", "title": "Y", "units": "3.0"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")
        subject.refresh_from_db()
        self.assertEqual(subject.code, "FREE1")

    def test_code_edit_blocked_when_used_in_released_grades(self):
        from approvals.models import GradeSheet, GradeSheetStatus

        subject = Subject.objects.create(code="RELEASED1", title="X", units=Decimal("3.0"))
        CurriculumEntry.objects.create(program=self.program_b, year_level=1, term="FIRST", subject=subject)
        class_offering = ClassOffering.objects.create(subject=subject, semester=self.semester)
        class_offering.sections.set([self.section_b])
        GradeSheet.objects.create(class_offering=class_offering, status=GradeSheetStatus.RELEASED)

        self.client.force_login(self.head_b)
        get_response = self.client.get(reverse("academics:subject_edit", args=[subject.pk]))
        self.assertContains(get_response, "already appears in released grades")

        response = self.client.post(
            reverse("academics:subject_edit", args=[subject.pk]),
            {"code": "NEWCODE1", "title": "X", "units": "3.0"},
        )
        # The code field is server-side disabled once locked -- a posted
        # change to it is silently ignored (title/units still save fine)
        # rather than erroring, since the warning is already shown
        # up-front on the form before any submission is attempted.
        self.assertEqual(response.status_code, 204, response.content)
        subject.refresh_from_db()
        self.assertEqual(subject.code, "RELEASED1")

    def test_admin_correct_code_bypasses_block_and_is_logged(self):
        from approvals.models import GradeSheet, GradeSheetStatus

        from .models import AcademicSetupChangeLog

        subject = Subject.objects.create(code="RELEASED2", title="X", units=Decimal("3.0"))
        CurriculumEntry.objects.create(program=self.program_b, year_level=1, term="FIRST", subject=subject)
        class_offering = ClassOffering.objects.create(subject=subject, semester=self.semester)
        class_offering.sections.set([self.section_b])
        GradeSheet.objects.create(class_offering=class_offering, status=GradeSheetStatus.LOCKED)

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("academics:subject_correct_code", args=[subject.pk]),
            {"code": "CORRECTED1", "reason": "Typo in the original Registrar sheet."},
        )
        self.assertEqual(response.status_code, 204, response.content)
        subject.refresh_from_db()
        self.assertEqual(subject.code, "CORRECTED1")
        log = AcademicSetupChangeLog.objects.get(action=AcademicSetupChangeLog.Action.CODE_CORRECTED)
        self.assertTrue(log.is_admin_override)
        self.assertEqual(log.details["old_code"], "RELEASED2")
        self.assertEqual(log.details["new_code"], "CORRECTED1")

    def test_non_admin_cannot_reach_correct_code(self):
        subject = Subject.objects.create(code="RELEASED3", title="X", units=Decimal("3.0"))
        self.client.force_login(self.head_b)
        response = self.client.get(reverse("academics:subject_correct_code", args=[subject.pk]))
        self.assertEqual(response.status_code, 403)


class SubjectOfferingTestBase(TestCase):
    """One program (BSED) with two majors (English, Social Studies), each
    with one 1st-Year section, sharing a General Education subject in
    their curricula -- the "shared subject" scenario the spec describes
    (offering GE 2 for one major while it's already offered for the
    other)."""

    def setUp(self):
        self.ay = AcademicYear.objects.create(start_year=2026)
        self.semester = Semester.objects.create(academic_year=self.ay, term=Term.FIRST, is_active=True)

        self.program = Program.objects.create(code="BSED", name="BS Education")
        self.major_eng = Major.objects.create(program=self.program, code="ENG", name="English")
        self.major_ss = Major.objects.create(program=self.program, code="SS", name="Social Studies")

        self.section_eng = Section.objects.create(
            program=self.program, major=self.major_eng, academic_year=self.ay, year_level=1, name="A"
        )
        self.section_ss = Section.objects.create(
            program=self.program, major=self.major_ss, academic_year=self.ay, year_level=1, name="A"
        )

        self.ge_subject = Subject.objects.create(code="GE 2", title="Purposive Communication", units=Decimal("3.0"))
        self.entry_eng = CurriculumEntry.objects.create(
            program=self.program, major=self.major_eng, year_level=1, term=Term.FIRST, subject=self.ge_subject
        )
        self.entry_ss = CurriculumEntry.objects.create(
            program=self.program, major=self.major_ss, year_level=1, term=Term.FIRST, subject=self.ge_subject
        )

        self.admin = make_user(User.Role.ADMIN, "offering_admin", is_staff=True, is_superuser=True)

        self.active_students_eng = [self._make_active_student(f"eng_stud{i}", self.section_eng) for i in range(2)]
        self.active_students_ss = [self._make_active_student(f"ss_stud{i}", self.section_ss) for i in range(1)]
        self.completed_student_ss = self._make_active_student(
            "ss_completed", self.section_ss, status=StudentProfile.Status.COMPLETED
        )

    def _make_active_student(self, username, section, status=StudentProfile.Status.ACTIVE):
        user = make_user(User.Role.STUDENT, username)
        profile = user.student_profile
        profile.program = section.program
        profile.major = section.major
        profile.year_level = section.year_level
        profile.section = section
        profile.status = status
        profile.save()
        return user


class SubjectOfferingPreviewAndCommitTests(SubjectOfferingTestBase):
    def test_offer_creates_one_class_per_section_and_fills_roster_with_active_students_only(self):
        from .services import commit_subject_offerings, preview_subject_offerings

        preview = preview_subject_offerings([self.entry_eng.pk], self.semester)
        self.assertEqual(len(preview["plan_rows"]), 1)
        self.assertEqual(preview["missing_section_rows"], [])
        self.assertIsNone(preview["plan_rows"][0]["conflict_class"])

        result = commit_subject_offerings(preview["plan_rows"], self.semester, self.admin)
        self.assertEqual(result, {"offerings_created": 1, "classes_created": 1, "students_added": 2})

        offering = SubjectOffering.objects.get(program=self.program, major=self.major_eng, subject=self.ge_subject)
        class_offering = ClassOffering.objects.get(offering=offering)
        self.assertEqual(list(class_offering.sections.all()), [self.section_eng])
        roster_student_ids = set(
            class_offering.roster_entries.filter(status=ClassRosterEntry.Status.ACTIVE).values_list(
                "student_id", flat=True
            )
        )
        self.assertEqual(roster_student_ids, {u.id for u in self.active_students_eng})

    def test_no_section_for_year_level_reports_missing_and_creates_nothing(self):
        from .services import preview_subject_offerings

        other_major = Major.objects.create(program=self.program, code="MATH", name="Mathematics")
        entry_no_section = CurriculumEntry.objects.create(
            program=self.program, major=other_major, year_level=2, term=Term.FIRST, subject=self.ge_subject
        )

        preview = preview_subject_offerings([entry_no_section.pk], self.semester)
        self.assertEqual(preview["plan_rows"], [])
        self.assertEqual(len(preview["missing_section_rows"]), 1)
        self.assertEqual(preview["missing_section_rows"][0]["major"], other_major)
        self.assertEqual(SubjectOffering.objects.count(), 0)
        self.assertEqual(ClassOffering.objects.count(), 0)

    def test_shared_subject_combine_adds_section_to_existing_class(self):
        from .services import commit_subject_offerings, preview_subject_offerings

        first_preview = preview_subject_offerings([self.entry_eng.pk], self.semester)
        commit_subject_offerings(first_preview["plan_rows"], self.semester, self.admin)

        second_preview = preview_subject_offerings([self.entry_ss.pk], self.semester)
        self.assertEqual(len(second_preview["plan_rows"]), 1)
        conflict_class = second_preview["plan_rows"][0]["conflict_class"]
        self.assertIsNotNone(conflict_class)
        second_preview["plan_rows"][0]["combine"] = True

        result = commit_subject_offerings(second_preview["plan_rows"], self.semester, self.admin)
        self.assertEqual(result["classes_created"], 0)
        self.assertEqual(result["offerings_created"], 1)

        self.assertEqual(ClassOffering.objects.count(), 1)
        class_offering = ClassOffering.objects.get()
        self.assertEqual(set(class_offering.sections.all()), {self.section_eng, self.section_ss})
        roster_student_ids = set(
            class_offering.roster_entries.filter(status=ClassRosterEntry.Status.ACTIVE).values_list(
                "student_id", flat=True
            )
        )
        expected = {u.id for u in self.active_students_eng} | {u.id for u in self.active_students_ss}
        self.assertEqual(roster_student_ids, expected)
        self.assertNotIn(self.completed_student_ss.id, roster_student_ids)

    def test_shared_subject_separate_creates_second_class(self):
        from .services import commit_subject_offerings, preview_subject_offerings

        first_preview = preview_subject_offerings([self.entry_eng.pk], self.semester)
        commit_subject_offerings(first_preview["plan_rows"], self.semester, self.admin)

        second_preview = preview_subject_offerings([self.entry_ss.pk], self.semester)
        conflict_class = second_preview["plan_rows"][0]["conflict_class"]

        commit_subject_offerings(second_preview["plan_rows"], self.semester, self.admin)

        self.assertEqual(ClassOffering.objects.count(), 2)
        new_class = ClassOffering.objects.exclude(pk=conflict_class.pk).get()
        self.assertEqual(list(new_class.sections.all()), [self.section_ss])

    def test_duplicate_offering_skipped_by_preview_and_blocked_by_constraint(self):
        from django.db import IntegrityError

        from .services import commit_subject_offerings, preview_subject_offerings

        preview = preview_subject_offerings([self.entry_eng.pk], self.semester)
        commit_subject_offerings(preview["plan_rows"], self.semester, self.admin)

        second_preview = preview_subject_offerings([self.entry_eng.pk], self.semester)
        self.assertEqual(second_preview["plan_rows"], [])
        self.assertEqual(len(second_preview["already_offered_rows"]), 1)

        with self.assertRaises(IntegrityError):
            SubjectOffering.objects.create(
                semester=self.semester, program=self.program, major=self.major_eng, year_level=1, subject=self.ge_subject
            )


class WithdrawOfferingTests(SubjectOfferingTestBase):
    def _offer_eng(self):
        from .services import commit_subject_offerings, preview_subject_offerings

        preview = preview_subject_offerings([self.entry_eng.pk], self.semester)
        commit_subject_offerings(preview["plan_rows"], self.semester, self.admin)
        return SubjectOffering.objects.get(program=self.program, major=self.major_eng, subject=self.ge_subject)

    def test_withdraw_succeeds_when_no_scores_or_submitted_sheet(self):
        from .services import withdraw_offering

        offering = self._offer_eng()
        ok, reason = withdraw_offering(offering, self.admin)
        self.assertTrue(ok)
        self.assertIsNone(reason)
        self.assertEqual(SubjectOffering.objects.count(), 0)
        self.assertEqual(ClassOffering.objects.count(), 0)

    def test_withdraw_blocked_when_scores_exist(self):
        from grading.models import AssessmentItem, AssessmentTerm, ClassGradingScheme, Score
        from grading.services import ensure_default_grading_template

        from .services import withdraw_offering

        ensure_default_grading_template()
        offering = self._offer_eng()
        class_offering = ClassOffering.objects.get(offering=offering)
        scheme = ClassGradingScheme.get_or_create_default(class_offering)
        component = scheme.components.first()
        item = AssessmentItem.objects.create(
            class_offering=class_offering, component=component, title="Quiz 1", max_score=10, term=AssessmentTerm.PRELIM
        )
        roster_entry = class_offering.roster_entries.first()
        Score.objects.create(roster_entry=roster_entry, item=item, score=8)

        ok, reason = withdraw_offering(offering, self.admin)
        self.assertFalse(ok)
        self.assertIn("scores", reason)
        self.assertEqual(SubjectOffering.objects.count(), 1)

    def test_withdraw_blocked_when_grade_sheet_submitted(self):
        from approvals.models import GradeSheet, GradeSheetStatus

        from .services import withdraw_offering

        offering = self._offer_eng()
        class_offering = ClassOffering.objects.get(offering=offering)
        GradeSheet.objects.create(class_offering=class_offering, status=GradeSheetStatus.SUBMITTED)

        ok, reason = withdraw_offering(offering, self.admin)
        self.assertFalse(ok)
        self.assertEqual(SubjectOffering.objects.count(), 1)


class ClassOfferingSnapshotTests(SubjectOfferingTestBase):
    def test_subject_edit_after_class_created_does_not_change_past_class_display(self):
        from .services import commit_subject_offerings, preview_subject_offerings

        preview = preview_subject_offerings([self.entry_eng.pk], self.semester)
        commit_subject_offerings(preview["plan_rows"], self.semester, self.admin)
        class_offering = ClassOffering.objects.get()
        self.assertEqual(class_offering.display_code, "GE 2")
        self.assertEqual(class_offering.display_title, "Purposive Communication")

        self.ge_subject.code = "GE 2-REVISED"
        self.ge_subject.title = "Communication Skills"
        self.ge_subject.save()
        class_offering.refresh_from_db()

        self.assertEqual(class_offering.display_code, "GE 2")
        self.assertEqual(class_offering.display_title, "Purposive Communication")
        self.assertEqual(class_offering.subject.code, "GE 2-REVISED")


class SemesterStatusTests(TestCase):
    def test_setting_active_sets_status_active(self):
        ay = AcademicYear.objects.create(start_year=2027)
        semester = Semester.objects.create(academic_year=ay, term=Term.FIRST, is_active=True)
        self.assertEqual(semester.status, SemesterStatus.ACTIVE)

    def test_close_semester_clears_is_active(self):
        from .services import close_semester

        ay = AcademicYear.objects.create(start_year=2027)
        semester = Semester.objects.create(
            academic_year=ay, term=Term.FIRST, is_active=True, end_date=date(2020, 1, 1)
        )
        admin = make_user(User.Role.ADMIN, "close_sem_admin", is_staff=True, is_superuser=True)
        ok, reason = close_semester(semester, admin)
        self.assertTrue(ok)
        semester.refresh_from_db()
        self.assertEqual(semester.status, SemesterStatus.CLOSED)
        self.assertFalse(semester.is_active)

    def test_close_semester_blocked_before_end_date_with_unlocked_sheets(self):
        from approvals.models import GradeSheet, GradeSheetStatus

        from .services import close_semester

        ay = AcademicYear.objects.create(start_year=2028)
        semester = Semester.objects.create(academic_year=ay, term=Term.FIRST, is_active=True)
        program = Program.objects.create(code="BSIT2", name="BS Information Technology")
        section = Section.objects.create(program=program, academic_year=ay, year_level=1, name="A")
        subject = Subject.objects.create(code="SUBX", title="X", units=Decimal("3.0"))
        class_offering = ClassOffering.objects.create(subject=subject, semester=semester)
        class_offering.sections.set([section])
        GradeSheet.objects.create(class_offering=class_offering, status=GradeSheetStatus.SUBMITTED)
        admin = make_user(User.Role.ADMIN, "close_sem_admin2", is_staff=True, is_superuser=True)

        ok, reason = close_semester(semester, admin)
        self.assertFalse(ok)
        semester.refresh_from_db()
        self.assertEqual(semester.status, SemesterStatus.ACTIVE)


class SubjectOfferingViewTests(SubjectOfferingTestBase):
    """End-to-end through the actual URLs/views, not just the service
    layer -- preview stashes in session, commit reads it back and clears
    it, both gated by scope and by offering_allowed(semester)."""

    def _post_params(self):
        return {
            "program": self.program.pk,
            "major": self.major_eng.pk,
            "ay": self.ay.pk,
            "sem_term": Term.FIRST,
        }

    def test_preview_then_commit_creates_class(self):
        self.client.force_login(self.admin)
        params = self._post_params()
        params["entry_ids"] = [self.entry_eng.pk]
        response = self.client.post(reverse("academics:subject_offering_preview"), params)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Confirm Offering", response.content.decode())

        commit_response = self.client.post(reverse("academics:subject_offering_commit"), {"sections_0": [self.section_eng.pk]})
        self.assertEqual(commit_response.status_code, 204)
        self.assertIn("refreshSubjects", commit_response.headers.get("HX-Trigger", ""))

        self.assertEqual(ClassOffering.objects.filter(offering__subject=self.ge_subject).count(), 1)
        self.assertNotIn("subject_offering_preview", self.client.session)

    def test_preview_silently_drops_already_offered_entry(self):
        from .services import commit_subject_offerings, preview_subject_offerings

        preview = preview_subject_offerings([self.entry_eng.pk], self.semester)
        commit_subject_offerings(preview["plan_rows"], self.semester, self.admin)

        self.client.force_login(self.admin)
        params = self._post_params()
        params["entry_ids"] = [self.entry_eng.pk]
        response = self.client.post(reverse("academics:subject_offering_preview"), params, follow=True)
        self.assertEqual(ClassOffering.objects.filter(offering__subject=self.ge_subject).count(), 1)

    def test_preview_blocked_on_closed_semester(self):
        self.semester.status = SemesterStatus.CLOSED
        self.semester.is_active = False
        self.semester.save()

        self.client.force_login(self.admin)
        params = self._post_params()
        params["entry_ids"] = [self.entry_eng.pk]
        response = self.client.post(reverse("academics:subject_offering_preview"), params)
        self.assertEqual(response.status_code, 403)

    def test_withdraw_view_get_then_post(self):
        from .services import commit_subject_offerings, preview_subject_offerings

        preview = preview_subject_offerings([self.entry_eng.pk], self.semester)
        commit_subject_offerings(preview["plan_rows"], self.semester, self.admin)
        offering = SubjectOffering.objects.get(program=self.program, major=self.major_eng, subject=self.ge_subject)

        self.client.force_login(self.admin)
        get_response = self.client.get(reverse("academics:subject_offering_withdraw", args=[offering.pk]))
        self.assertEqual(get_response.status_code, 200)

        post_response = self.client.post(reverse("academics:subject_offering_withdraw", args=[offering.pk]))
        self.assertEqual(post_response.status_code, 204)
        self.assertIn("refreshSubjects", post_response.headers.get("HX-Trigger", ""))
        self.assertFalse(SubjectOffering.objects.filter(pk=offering.pk).exists())

    def test_withdraw_blocked_for_program_head_outside_scope(self):
        from .services import commit_subject_offerings, preview_subject_offerings

        preview = preview_subject_offerings([self.entry_eng.pk], self.semester)
        commit_subject_offerings(preview["plan_rows"], self.semester, self.admin)
        offering = SubjectOffering.objects.get(program=self.program, major=self.major_eng, subject=self.ge_subject)

        outside_head = make_user(User.Role.PROGRAM_HEAD, "offering_outside_head")
        self.client.force_login(outside_head)
        response = self.client.get(reverse("academics:subject_offering_withdraw", args=[offering.pk]))
        self.assertEqual(response.status_code, 403)

    def test_adhoc_offering_outside_curriculum(self):
        other_subject = Subject.objects.create(code="ADHOC1", title="Ad-hoc Subject", units=Decimal("3.0"))

        self.client.force_login(self.admin)
        params = self._post_params()
        params["subject"] = other_subject.pk
        params["year_level"] = 1
        response = self.client.post(reverse("academics:subject_offering_adhoc"), params)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Confirm Offering", response.content.decode())

        commit_response = self.client.post(reverse("academics:subject_offering_commit"), {"sections_0": [self.section_eng.pk]})
        self.assertEqual(commit_response.status_code, 204)
        self.assertTrue(ClassOffering.objects.filter(offering__subject=other_subject).exists())
        # Offering it didn't touch the curriculum itself.
        self.assertFalse(CurriculumEntry.objects.filter(subject=other_subject).exists())


class ClosedSemesterReadOnlyTests(TestCase):
    """Once a semester is CLOSED, every existing mutation path that touches
    one of its classes/rosters/instructor-assignments must 403 -- server-
    enforced, not just a hidden button (CLAUDE.md's established rule for
    every editability lock in this codebase)."""

    def setUp(self):
        self.ay = AcademicYear.objects.create(start_year=2026)
        self.semester = Semester.objects.create(academic_year=self.ay, term=Term.FIRST, is_active=True)
        self.program = Program.objects.create(code="BSIT3", name="BS Information Technology")
        self.head = make_user(User.Role.PROGRAM_HEAD, "closed_sem_head")
        self.program.program_head = self.head
        self.program.save()
        self.section = Section.objects.create(program=self.program, academic_year=self.ay, year_level=1, name="A")
        self.subject = Subject.objects.create(code="CLOSEDSUB", title="X", units=Decimal("3.0"))
        self.class_offering = ClassOffering.objects.create(subject=self.subject, semester=self.semester)
        self.class_offering.sections.set([self.section])

        self.student = make_user(User.Role.STUDENT, "closed_sem_student")
        profile = self.student.student_profile
        profile.program = self.program
        profile.section = self.section
        profile.year_level = 1
        profile.save()
        self.roster_entry = ClassRosterEntry.objects.create(student=self.student, class_offering=self.class_offering)
        self.admin = make_user(User.Role.ADMIN, "closed_sem_admin", is_staff=True, is_superuser=True)

        # Close it directly -- this test suite is about the read-only
        # enforcement, not close_semester()'s own gating (covered above).
        self.semester.status = SemesterStatus.CLOSED
        self.semester.is_active = False
        self.semester.save()

    def test_ph_class_edit_blocked(self):
        self.client.force_login(self.head)
        response = self.client.get(reverse("academics:ph_class_edit", args=[self.class_offering.pk]))
        self.assertEqual(response.status_code, 403)

    def test_ph_class_leave_blocked(self):
        self.client.force_login(self.head)
        response = self.client.get(reverse("academics:ph_class_leave", args=[self.class_offering.pk]))
        self.assertEqual(response.status_code, 403)

    def test_admin_class_edit_blocked(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("academics:class_edit", args=[self.class_offering.pk]),
            {
                "subject": self.subject.pk,
                "sections": [self.section.pk],
                "semester": self.semester.pk,
                "schedule": "",
                "room": "",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_class_list_add_section_blocked(self):
        self.client.force_login(self.head)
        response = self.client.post(
            reverse("academics:class_list_add_section", args=[self.class_offering.pk]), {"section": self.section.pk}
        )
        self.assertEqual(response.status_code, 403)

    def test_class_list_add_students_submit_blocked(self):
        self.client.force_login(self.head)
        response = self.client.post(
            reverse("academics:class_list_add_students_submit", args=[self.class_offering.pk]),
            {"student_ids": [self.student.pk]},
        )
        self.assertEqual(response.status_code, 403)

    def test_class_list_mark_dropped_blocked(self):
        self.client.force_login(self.head)
        response = self.client.post(reverse("academics:class_list_mark_dropped", args=[self.roster_entry.pk]))
        self.assertEqual(response.status_code, 403)

    def test_class_list_restore_blocked(self):
        self.roster_entry.status = ClassRosterEntry.Status.DROPPED
        self.roster_entry.save()
        self.client.force_login(self.head)
        response = self.client.post(reverse("academics:class_list_restore", args=[self.roster_entry.pk]))
        self.assertEqual(response.status_code, 403)

    def test_class_list_import_confirm_blocked(self):
        session = self.client.session
        session["class_list_import_preview"] = {"class_offering_id": self.class_offering.pk, "rows": []}
        session.save()
        self.client.force_login(self.head)
        response = self.client.post(reverse("academics:class_list_import_confirm", args=[self.class_offering.pk]), {})
        self.assertEqual(response.status_code, 403)

    def test_instructor_assignment_blocked(self):
        instructor = make_user(User.Role.INSTRUCTOR, "closed_sem_inst")
        self.client.force_login(self.head)
        self.client.post(
            reverse("academics:class_assign_instructor", args=[self.class_offering.pk]), {"instructor": instructor.pk}
        )
        self.class_offering.refresh_from_db()
        self.assertIsNone(self.class_offering.instructor)

    def test_grade_correction_not_blocked_by_closed_semester(self):
        """Grade corrections are explicitly exempt -- they go through
        approvals.services.correct_grade's own RELEASED/LOCKED-only gate,
        independent of semester status."""
        from approvals.models import GradeSheet, GradeSheetEntry, GradeSheetStatus
        from approvals.services import correct_grade

        sheet = GradeSheet.objects.create(class_offering=self.class_offering, status=GradeSheetStatus.RELEASED)
        entry = GradeSheetEntry.objects.create(
            sheet=sheet, roster_entry=self.roster_entry, final_grade=Decimal("1.50"), remarks="PASSED"
        )
        correct_grade(entry, self.admin, Decimal("1.25"), "PASSED", "Recomputation error")
        entry.refresh_from_db()
        self.assertEqual(entry.final_grade, Decimal("1.25"))


class SubjectsPageOfferingRenderTests(SubjectOfferingTestBase):
    """The Subjects page itself must render correctly with the new
    filter/checkbox/badge additions, both before and after a subject is
    offered, and for a CLOSED semester (no checkboxes at all)."""

    def test_page_renders_with_offerable_checkbox(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("academics:subjects"),
            {"program": self.program.pk, "major": self.major_eng.pk, "ay": self.ay.pk, "sem_term": Term.FIRST},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="entry_ids"')
        self.assertContains(response, "Offer another subject")

    def test_page_renders_offered_badge_after_offering(self):
        from .services import commit_subject_offerings, preview_subject_offerings

        preview = preview_subject_offerings([self.entry_eng.pk], self.semester)
        commit_subject_offerings(preview["plan_rows"], self.semester, self.admin)

        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("academics:subjects"),
            {"program": self.program.pk, "major": self.major_eng.pk, "ay": self.ay.pk, "sem_term": Term.FIRST},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Offered")

    def test_page_renders_closed_semester_without_checkboxes(self):
        self.semester.status = SemesterStatus.CLOSED
        self.semester.is_active = False
        self.semester.save()

        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("academics:subjects"),
            {"program": self.program.pk, "major": self.major_eng.pk, "ay": self.ay.pk, "sem_term": Term.FIRST},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="entry_ids"')
        self.assertContains(response, "Closed")


class SectionLetterTests(TestCase):
    """Section.name is re-scoped to a single optional uppercase letter
    (A, B, C…) -- display format "BSED-ENG 1-A" / "BSED-ENG 1" (no
    suffix), and services.next_section_letter suggests the next free one."""

    def setUp(self):
        self.ay = AcademicYear.objects.create(start_year=2026)
        self.program = Program.objects.create(code="BSED", name="BS Education")
        self.major = Major.objects.create(program=self.program, code="ENG", name="English")

    def test_blank_letter_displays_with_no_suffix(self):
        section = Section.objects.create(
            program=self.program, major=self.major, academic_year=self.ay, year_level=1, name=""
        )
        self.assertEqual(str(section), "BSED-ENG 1")

    def test_letter_displays_with_hyphen_suffix(self):
        section = Section.objects.create(
            program=self.program, major=self.major, academic_year=self.ay, year_level=1, name="A"
        )
        self.assertEqual(str(section), "BSED-ENG 1-A")

    def test_lowercase_letter_rejected(self):
        section = Section(program=self.program, major=self.major, academic_year=self.ay, year_level=1, name="a")
        with self.assertRaises(ValidationError):
            section.full_clean()

    def test_multi_character_name_rejected(self):
        section = Section(program=self.program, major=self.major, academic_year=self.ay, year_level=1, name="AB")
        with self.assertRaises(ValidationError):
            section.full_clean()

    def test_next_section_letter_starts_at_a(self):
        from .services import next_section_letter

        letter = next_section_letter(self.program, self.major, self.ay, 1)
        self.assertEqual(letter, "A")

    def test_next_section_letter_increments(self):
        from .services import next_section_letter

        Section.objects.create(program=self.program, major=self.major, academic_year=self.ay, year_level=1, name="A")
        Section.objects.create(program=self.program, major=self.major, academic_year=self.ay, year_level=1, name="B")
        letter = next_section_letter(self.program, self.major, self.ay, 1)
        self.assertEqual(letter, "C")

    def test_next_section_letter_ignores_other_year_levels(self):
        from .services import next_section_letter

        Section.objects.create(program=self.program, major=self.major, academic_year=self.ay, year_level=2, name="A")
        letter = next_section_letter(self.program, self.major, self.ay, 1)
        self.assertEqual(letter, "A")


class MoveStudentsToSectionTests(TestCase):
    def setUp(self):
        self.ay = AcademicYear.objects.create(start_year=2026)
        self.program = Program.objects.create(code="BSED", name="BS Education")
        self.major = Major.objects.create(program=self.program, code="ENG", name="English")
        self.section_a = Section.objects.create(
            program=self.program, major=self.major, academic_year=self.ay, year_level=1, name="A"
        )
        self.section_b = Section.objects.create(
            program=self.program, major=self.major, academic_year=self.ay, year_level=1, name="B"
        )
        self.student = make_user(User.Role.STUDENT, "move_stud1")
        profile = self.student.student_profile
        profile.program = self.program
        profile.major = self.major
        profile.year_level = 1
        profile.section = self.section_a
        profile.save()
        self.admin = make_user(User.Role.ADMIN, "move_admin", is_staff=True, is_superuser=True)

    def test_moves_student_and_logs(self):
        from .models import AcademicSetupChangeLog
        from .services import move_students_to_section

        moved = move_students_to_section([self.student.student_profile.pk], self.section_b, self.admin)
        self.assertEqual(moved, 1)
        self.student.student_profile.refresh_from_db()
        self.assertEqual(self.student.student_profile.section, self.section_b)

        log = AcademicSetupChangeLog.objects.get(action=AcademicSetupChangeLog.Action.STUDENTS_MOVED)
        self.assertEqual(log.details["moved_count"], 1)
        self.assertEqual(log.details["to_section_id"], self.section_b.pk)

    def test_no_op_move_is_not_logged(self):
        from .models import AcademicSetupChangeLog
        from .services import move_students_to_section

        moved = move_students_to_section([], self.section_b, self.admin)
        self.assertEqual(moved, 0)
        self.assertFalse(AcademicSetupChangeLog.objects.filter(action=AcademicSetupChangeLog.Action.STUDENTS_MOVED).exists())


class SectionsPageRedesignTests(TeachingAssignmentTestBase):
    """Sections is now a toolbar + year-level-card prospectus, same shape
    as Subjects -- admin picks any program/major, Program Head sees
    segmented major pills scoped to their own program(s)."""

    def setUp(self):
        super().setUp()
        self.major_eng = Major.objects.create(program=self.program_b, code="ENG", name="English")
        self.major_eng.program_head = self.head_b
        self.major_eng.save()
        self.section = Section.objects.create(
            program=self.program_b, major=self.major_eng, academic_year=self.ay, year_level=1, name="A"
        )

    def test_admin_sections_page_renders(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("academics:sections"), {"program": self.program_b.pk, "major": self.major_eng.pk, "ay": self.ay.pk}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "BSED-ENG 1-A")

    def test_ph_sections_page_renders_with_pills(self):
        self.client.force_login(self.head_b)
        response = self.client.get(reverse("academics:ph_sections"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "English")
        self.assertContains(response, "BSED-ENG 1-A")

    def test_add_section_prefills_next_letter(self):
        self.client.force_login(self.head_b)
        response = self.client.get(
            reverse("academics:ph_section_create"),
            {"program": self.program_b.pk, "major": self.major_eng.pk, "year_level": 1},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="B"')

    def test_section_students_page_scoped(self):
        student = make_user(User.Role.STUDENT, "section_stud1")
        profile = student.student_profile
        profile.section = self.section
        profile.program = self.program_b
        profile.major = self.major_eng
        profile.year_level = 1
        profile.save()

        self.client.force_login(self.head_b)
        response = self.client.get(reverse("academics:section_students", args=[self.section.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, student.full_name)

        outside_head = make_user(User.Role.PROGRAM_HEAD, "section_outside_head")
        self.client.force_login(outside_head)
        response = self.client.get(reverse("academics:section_students", args=[self.section.pk]))
        self.assertEqual(response.status_code, 403)

    def test_move_students_only_offers_same_year_level_sections(self):
        student = make_user(User.Role.STUDENT, "section_stud3")
        profile = student.student_profile
        profile.section = self.section
        profile.program = self.program_b
        profile.major = self.major_eng
        profile.year_level = 1
        profile.save()
        other_year_section = Section.objects.create(
            program=self.program_b, major=self.major_eng, academic_year=self.ay, year_level=2, name="A"
        )
        same_year_section = Section.objects.create(
            program=self.program_b, major=self.major_eng, academic_year=self.ay, year_level=1, name="B"
        )
        self.client.force_login(self.head_b)
        response = self.client.get(reverse("academics:section_students", args=[self.section.pk]))
        content = response.content.decode()
        self.assertIn(str(same_year_section.pk), content)
        self.assertNotIn(f'value="{other_year_section.pk}"', content)

    def test_move_students_via_post(self):
        student = make_user(User.Role.STUDENT, "section_stud2")
        profile = student.student_profile
        profile.section = self.section
        profile.program = self.program_b
        profile.major = self.major_eng
        profile.year_level = 1
        profile.save()
        target = Section.objects.create(
            program=self.program_b, major=self.major_eng, academic_year=self.ay, year_level=1, name="B"
        )

        self.client.force_login(self.head_b)
        response = self.client.post(
            reverse("academics:section_students_move", args=[self.section.pk]),
            {"target_section": target.pk, "profile_ids": [profile.pk]},
        )
        self.assertEqual(response.status_code, 204)
        profile.refresh_from_db()
        self.assertEqual(profile.section, target)


class SectionShortLabelTests(TestCase):
    def setUp(self):
        self.ay = AcademicYear.objects.create(start_year=2026)
        self.program = Program.objects.create(code="BSED", name="BS Education")

    def test_year_level_and_letter(self):
        section = Section.objects.create(program=self.program, academic_year=self.ay, year_level=1, name="A")
        self.assertEqual(section.short_label, "1-A")

    def test_year_level_only(self):
        section = Section.objects.create(program=self.program, academic_year=self.ay, year_level=1, name="")
        self.assertEqual(section.short_label, "1")

    def test_letter_only(self):
        section = Section.objects.create(program=self.program, academic_year=self.ay, year_level=None, name="A")
        self.assertEqual(section.short_label, "A")

    def test_neither_falls_back_to_program_code(self):
        section = Section.objects.create(program=self.program, academic_year=self.ay, year_level=None, name="")
        self.assertEqual(section.short_label, "BSED")


class SyncOfferingAfterSectionChangeTests(SubjectOfferingTestBase):
    def test_deletes_offering_once_no_classes_remain(self):
        from .services import commit_subject_offerings, preview_subject_offerings, sync_offering_after_section_change

        preview = preview_subject_offerings([self.entry_eng.pk], self.semester)
        commit_subject_offerings(preview["plan_rows"], self.semester, self.admin)
        offering = SubjectOffering.objects.get(program=self.program, major=self.major_eng, subject=self.ge_subject)
        class_offering = ClassOffering.objects.get(offering=offering)

        class_offering.roster_entries.all().delete()
        class_offering.delete()
        sync_offering_after_section_change(offering)
        self.assertFalse(SubjectOffering.objects.filter(pk=offering.pk).exists())

    def test_noop_while_classes_remain(self):
        from .services import commit_subject_offerings, preview_subject_offerings, sync_offering_after_section_change

        preview = preview_subject_offerings([self.entry_eng.pk], self.semester)
        commit_subject_offerings(preview["plan_rows"], self.semester, self.admin)
        offering = SubjectOffering.objects.get(program=self.program, major=self.major_eng, subject=self.ge_subject)

        sync_offering_after_section_change(offering)
        self.assertTrue(SubjectOffering.objects.filter(pk=offering.pk).exists())

    def test_none_is_a_noop(self):
        from .services import sync_offering_after_section_change

        sync_offering_after_section_change(None)  # must not raise


class OfferingMatrixAndManageSectionsTests(TestCase):
    """Two sections under one program/year_level -- the minimal shape the
    matrix's "combine toggle" and Manage Sections' add/withdraw diffing
    need, which SubjectOfferingTestBase's one-section-per-major fixture
    can't exercise on its own."""

    def setUp(self):
        self.ay = AcademicYear.objects.create(start_year=2026)
        self.semester = Semester.objects.create(academic_year=self.ay, term=Term.FIRST, is_active=True)
        self.program = Program.objects.create(code="BSIT4", name="BS Information Technology")
        self.section_a = Section.objects.create(program=self.program, academic_year=self.ay, year_level=1, name="A")
        self.section_b = Section.objects.create(program=self.program, academic_year=self.ay, year_level=1, name="B")
        self.subject = Subject.objects.create(code="GE 9", title="Life and Works of Rizal", units=Decimal("3.0"))
        self.entry = CurriculumEntry.objects.create(
            program=self.program, major=None, year_level=1, term=Term.FIRST, subject=self.subject
        )
        self.admin = make_user(User.Role.ADMIN, "matrix_admin", is_staff=True, is_superuser=True)

        self.student = make_user(User.Role.STUDENT, "matrix_student")
        profile = self.student.student_profile
        profile.program = self.program
        profile.year_level = 1
        profile.section = self.section_a
        profile.status = StudentProfile.Status.ACTIVE
        profile.save()

    def test_default_combine_off_creates_one_class_per_section(self):
        from .services import commit_subject_offerings, preview_subject_offerings

        preview = preview_subject_offerings([self.entry.pk], self.semester)
        self.assertEqual(len(preview["plan_rows"]), 2)
        self.assertFalse(any(row["combine"] for row in preview["plan_rows"]))

        result = commit_subject_offerings(preview["plan_rows"], self.semester, self.admin)
        self.assertEqual(result["classes_created"], 2)
        self.assertEqual(ClassOffering.objects.filter(subject=self.subject).count(), 2)

    def test_combine_true_merges_both_sections_into_one_class(self):
        from .services import commit_subject_offerings, preview_subject_offerings

        preview = preview_subject_offerings([self.entry.pk], self.semester)
        for row in preview["plan_rows"]:
            row["combine"] = True

        result = commit_subject_offerings(preview["plan_rows"], self.semester, self.admin)
        self.assertEqual(result["classes_created"], 1)
        class_offering = ClassOffering.objects.get(subject=self.subject)
        self.assertEqual(set(class_offering.sections.all()), {self.section_a, self.section_b})

    def test_already_offered_cell_is_skipped_by_commit(self):
        from .services import commit_subject_offerings, preview_subject_offerings

        preview = preview_subject_offerings([self.entry.pk], self.semester)
        commit_subject_offerings(preview["plan_rows"], self.semester, self.admin)

        from .services import build_offering_rows

        offering = SubjectOffering.objects.get(program=self.program, subject=self.subject)
        rows, _ = build_offering_rows(self.subject, self.program, None, 1, self.semester)
        self.assertTrue(all(row["already_offered"] for row in rows))

        result = commit_subject_offerings(rows, self.semester, self.admin)
        self.assertEqual(result["classes_created"], 0)
        self.assertEqual(ClassOffering.objects.filter(offering=offering).count(), 2)

    def test_manage_sections_view_adds_and_withdraws_sections(self):
        from .services import commit_subject_offerings, preview_subject_offerings

        preview = preview_subject_offerings([self.entry.pk], self.semester)
        section_a_only = [row for row in preview["plan_rows"] if row["section"] == self.section_a]
        commit_subject_offerings(section_a_only, self.semester, self.admin)
        offering = SubjectOffering.objects.get(program=self.program, subject=self.subject)
        self.assertEqual(ClassOffering.objects.filter(offering=offering).count(), 1)

        self.client.force_login(self.admin)
        get_response = self.client.get(reverse("academics:subject_offering_manage", args=[offering.pk]))
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, "Manage Sections")

        # Tick both sections -- A stays (already offered), B is newly added.
        add_response = self.client.post(
            reverse("academics:subject_offering_manage", args=[offering.pk]),
            {"sections_0": [self.section_a.pk, self.section_b.pk]},
        )
        self.assertEqual(add_response.status_code, 204)
        self.assertEqual(ClassOffering.objects.filter(offering=offering).count(), 2)

        # Re-open and untick A -- withdraws just that section's class.
        self.client.get(reverse("academics:subject_offering_manage", args=[offering.pk]))
        withdraw_response = self.client.post(
            reverse("academics:subject_offering_manage", args=[offering.pk]),
            {"sections_0": [self.section_b.pk]},
        )
        self.assertEqual(withdraw_response.status_code, 204)
        offering.refresh_from_db()
        self.assertEqual(set(offering.covered_sections), {self.section_b})

    def test_manage_sections_withdraw_blocked_by_scores_is_skipped_with_reason(self):
        from grading.models import AssessmentItem, AssessmentTerm, ClassGradingScheme, Score
        from grading.services import ensure_default_grading_template

        from .services import commit_subject_offerings, preview_subject_offerings

        ensure_default_grading_template()
        preview = preview_subject_offerings([self.entry.pk], self.semester)
        commit_subject_offerings(preview["plan_rows"], self.semester, self.admin)
        offering = SubjectOffering.objects.get(program=self.program, subject=self.subject)
        class_a = ClassOffering.objects.get(offering=offering, sections=self.section_a)
        scheme = ClassGradingScheme.get_or_create_default(class_a)
        component = scheme.components.first()
        item = AssessmentItem.objects.create(
            class_offering=class_a, component=component, title="Quiz 1", max_score=10, term=AssessmentTerm.PRELIM
        )
        roster_entry = class_a.roster_entries.first()
        Score.objects.create(roster_entry=roster_entry, item=item, score=8)

        self.client.force_login(self.admin)
        self.client.get(reverse("academics:subject_offering_manage", args=[offering.pk]))
        response = self.client.post(
            reverse("academics:subject_offering_manage", args=[offering.pk]),
            {"sections_0": [self.section_b.pk]},  # untick A -- should be skipped, not withdrawn
        )
        self.assertEqual(response.status_code, 204)
        self.assertIn("skipped", response.headers.get("HX-Trigger", ""))
        self.assertEqual(ClassOffering.objects.filter(offering=offering).count(), 2)
        self.assertTrue(ClassOffering.objects.filter(pk=class_a.pk, sections=self.section_a).exists())


class BulkWithdrawOfferingTests(TestCase):
    def setUp(self):
        self.ay = AcademicYear.objects.create(start_year=2026)
        self.semester = Semester.objects.create(academic_year=self.ay, term=Term.FIRST, is_active=True)
        self.program = Program.objects.create(code="BSIT5", name="BS Information Technology")
        self.section_1a = Section.objects.create(program=self.program, academic_year=self.ay, year_level=1, name="A")
        self.section_2a = Section.objects.create(program=self.program, academic_year=self.ay, year_level=2, name="A")
        self.subject_1 = Subject.objects.create(code="SUBY1", title="Year 1 Subject", units=Decimal("3.0"))
        self.subject_2 = Subject.objects.create(code="SUBY2", title="Year 2 Subject", units=Decimal("3.0"))
        self.entry_1 = CurriculumEntry.objects.create(
            program=self.program, major=None, year_level=1, term=Term.FIRST, subject=self.subject_1
        )
        self.entry_2 = CurriculumEntry.objects.create(
            program=self.program, major=None, year_level=2, term=Term.FIRST, subject=self.subject_2
        )
        self.admin = make_user(User.Role.ADMIN, "bulk_withdraw_admin", is_staff=True, is_superuser=True)

        from .services import commit_subject_offerings, preview_subject_offerings

        preview = preview_subject_offerings([self.entry_1.pk, self.entry_2.pk], self.semester)
        commit_subject_offerings(preview["plan_rows"], self.semester, self.admin)
        self.offering_1 = SubjectOffering.objects.get(subject=self.subject_1)
        self.offering_2 = SubjectOffering.objects.get(subject=self.subject_2)

    def _post_params(self, **extra):
        params = {"program": self.program.pk, "major": "", "ay": self.ay.pk, "sem_term": Term.FIRST}
        params.update(extra)
        return params

    def test_bulk_withdraw_by_explicit_offering_ids(self):
        self.client.force_login(self.admin)
        params = self._post_params(offering_ids=[self.offering_1.pk])
        preview_response = self.client.post(reverse("academics:subject_offering_bulk_withdraw"), params)
        self.assertEqual(preview_response.status_code, 200)
        self.assertIn(self.subject_1.code, preview_response.content.decode())

        confirm_params = self._post_params(offering_ids=[self.offering_1.pk], confirmed="1")
        confirm_response = self.client.post(reverse("academics:subject_offering_bulk_withdraw"), confirm_params)
        self.assertEqual(confirm_response.status_code, 204)
        self.assertIn("Withdrew 1 subject", confirm_response.headers.get("HX-Trigger", ""))
        self.assertFalse(SubjectOffering.objects.filter(pk=self.offering_1.pk).exists())
        self.assertTrue(SubjectOffering.objects.filter(pk=self.offering_2.pk).exists())

    def test_bulk_withdraw_by_year_level_scope(self):
        self.client.force_login(self.admin)
        params = self._post_params(scope="year_level:1", confirmed="1")
        response = self.client.post(reverse("academics:subject_offering_bulk_withdraw"), params)
        self.assertEqual(response.status_code, 204)
        self.assertFalse(SubjectOffering.objects.filter(pk=self.offering_1.pk).exists())
        self.assertTrue(SubjectOffering.objects.filter(pk=self.offering_2.pk).exists())

    def test_bulk_withdraw_all_scope_skips_with_reason_when_scores_exist(self):
        from grading.models import AssessmentItem, AssessmentTerm, ClassGradingScheme, Score
        from grading.services import ensure_default_grading_template

        ensure_default_grading_template()
        class_1 = ClassOffering.objects.get(offering=self.offering_1)
        scheme = ClassGradingScheme.get_or_create_default(class_1)
        component = scheme.components.first()
        item = AssessmentItem.objects.create(
            class_offering=class_1, component=component, title="Quiz 1", max_score=10, term=AssessmentTerm.PRELIM
        )
        student = make_user(User.Role.STUDENT, "bulk_withdraw_student")
        roster_entry = ClassRosterEntry.objects.create(student=student, class_offering=class_1)
        Score.objects.create(roster_entry=roster_entry, item=item, score=8)

        self.client.force_login(self.admin)
        params = self._post_params(scope="all", confirmed="1")
        response = self.client.post(reverse("academics:subject_offering_bulk_withdraw"), params)
        self.assertEqual(response.status_code, 204)
        toast = response.headers.get("HX-Trigger", "")
        self.assertIn("skipped", toast)
        self.assertTrue(SubjectOffering.objects.filter(pk=self.offering_1.pk).exists())
        self.assertFalse(SubjectOffering.objects.filter(pk=self.offering_2.pk).exists())


class ClassJoinCodeTestBase(TestCase):
    """One class, its instructor, a second (unrelated) instructor, and a
    student -- the shared fixture for the class-join-code feature."""

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.academic_year = AcademicYear.objects.create(start_year=2026)
        self.semester = Semester.objects.create(academic_year=self.academic_year, term=Term.FIRST, is_active=True)
        self.program = Program.objects.create(code="BSIT", name="BS Information Technology")
        self.section = Section.objects.create(program=self.program, academic_year=self.academic_year, year_level=1, name="A")
        self.other_section = Section.objects.create(program=self.program, academic_year=self.academic_year, year_level=1, name="B")
        self.subject = Subject.objects.create(code="IT101", title="Intro to Computing", units=Decimal("3.0"))
        self.instructor = make_user(User.Role.INSTRUCTOR, "join_prof")
        self.other_instructor = make_user(User.Role.INSTRUCTOR, "join_prof2")
        self.class_offering = ClassOffering.objects.create(
            subject=self.subject, semester=self.semester, instructor=self.instructor
        )
        self.class_offering.sections.set([self.section])

        self.student = make_user(User.Role.STUDENT, "join_student", id_number="2026-0099")
        StudentProfile.objects.update_or_create(
            user=self.student, defaults={"program": self.program, "section": self.section}
        )

    def _request_join(self, student=None, code=None):
        from .services import generate_join_code, request_to_join

        self.class_offering.join_code = self.class_offering.join_code or generate_join_code()
        self.class_offering.save(update_fields=["join_code"])
        return request_to_join(self.class_offering, student or self.student)


class JoinCodeGenerationTests(ClassJoinCodeTestBase):
    def test_ensure_join_code_assigns_once(self):
        from .services import ensure_join_code

        code1 = ensure_join_code(self.class_offering)
        self.class_offering.refresh_from_db()
        code2 = ensure_join_code(self.class_offering)
        self.assertEqual(code1, code2)
        self.assertEqual(len(code1), 7)
        self.assertTrue(set(code1) <= set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789"))

    def test_reset_join_code_changes_it_and_old_code_stops_resolving(self):
        from .services import ensure_join_code, reset_join_code, resolve_join_code

        old_code = ensure_join_code(self.class_offering)
        new_code = reset_join_code(self.class_offering, self.instructor)
        self.assertNotEqual(old_code, new_code)
        with self.assertRaises(ValidationError):
            resolve_join_code(old_code)
        self.assertEqual(resolve_join_code(new_code).pk, self.class_offering.pk)


class JoinRequestFlowTests(ClassJoinCodeTestBase):
    def test_join_then_approve_adds_to_roster_and_class_record(self):
        from grading.services import compute_class, ensure_default_grading_template

        ensure_default_grading_template()
        join_request = self._request_join()
        self.assertEqual(join_request.status, ClassJoinRequest.Status.PENDING)
        self.assertFalse(
            ClassRosterEntry.objects.filter(student=self.student, class_offering=self.class_offering).exists()
        )

        from .services import approve_join_request

        approve_join_request(join_request, self.instructor)
        join_request.refresh_from_db()
        self.assertEqual(join_request.status, ClassJoinRequest.Status.APPROVED)
        entry = ClassRosterEntry.objects.get(student=self.student, class_offering=self.class_offering)
        self.assertEqual(entry.source, ClassRosterEntry.Source.JOIN_CODE)

        results = compute_class(self.class_offering)
        self.assertIn(self.student.id, [r.roster_entry.student_id for r in results])

    def test_reject_does_not_add_to_roster_and_records_reason(self):
        from .services import reject_join_request

        join_request = self._request_join()
        reject_join_request(join_request, self.instructor, "Wrong section.")
        join_request.refresh_from_db()
        self.assertEqual(join_request.status, ClassJoinRequest.Status.REJECTED)
        self.assertEqual(join_request.reject_reason, "Wrong section.")
        self.assertFalse(
            ClassRosterEntry.objects.filter(student=self.student, class_offering=self.class_offering).exists()
        )

    def test_duplicate_pending_request_rejected(self):
        self._request_join()
        with self.assertRaises(ValidationError):
            self._request_join()

    def test_already_in_roster_rejected(self):
        ClassRosterEntry.objects.create(student=self.student, class_offering=self.class_offering)
        with self.assertRaises(ValidationError):
            self._request_join()

    def test_invalid_code_rejected(self):
        from .services import resolve_join_code

        with self.assertRaises(ValidationError):
            resolve_join_code("ZZZZZZZ")

    def test_join_disabled_rejected(self):
        self.class_offering.join_enabled = False
        self.class_offering.save(update_fields=["join_enabled"])
        with self.assertRaises(ValidationError):
            self._request_join()

    def test_inactive_semester_rejected(self):
        self.semester.is_active = False
        self.semester.save(update_fields=["is_active"])
        with self.assertRaises(ValidationError):
            self._request_join()

    def test_locked_grade_sheet_blocks_join_and_approval(self):
        from approvals.models import GradeSheet, GradeSheetStatus
        from .services import approve_join_request

        join_request = self._request_join()
        GradeSheet.objects.create(class_offering=self.class_offering, status=GradeSheetStatus.SUBMITTED)

        with self.assertRaises(ValidationError):
            approve_join_request(join_request, self.instructor)

        with self.assertRaises(ValidationError):
            self._request_join(student=make_user(User.Role.STUDENT, "join_student2"))

    def test_section_match_badge(self):
        from .services import join_request_section_match

        join_request = self._request_join()
        self.assertTrue(join_request_section_match(join_request))

        other_student = make_user(User.Role.STUDENT, "join_student_other")
        StudentProfile.objects.update_or_create(
            user=other_student, defaults={"program": self.program, "section": self.other_section}
        )
        other_request = self._request_join(student=other_student)
        self.assertFalse(join_request_section_match(other_request))

    def test_cancel_pending_request(self):
        from .services import cancel_join_request

        join_request = self._request_join()
        cancel_join_request(join_request, self.student)
        join_request.refresh_from_db()
        self.assertEqual(join_request.status, ClassJoinRequest.Status.CANCELLED)

    def test_bulk_approve_skips_already_decided(self):
        from .services import bulk_decide_join_requests, reject_join_request

        join_request = self._request_join()
        reject_join_request(join_request, self.instructor)
        decided, skipped = bulk_decide_join_requests([join_request], self.instructor, approve=True)
        self.assertEqual(decided, 0)
        self.assertEqual(len(skipped), 1)


class JoinCodeRateLimitTests(ClassJoinCodeTestBase):
    def test_wrong_codes_are_rate_limited(self):
        from .services import check_join_rate_limit, record_join_attempt

        for _ in range(10):
            self.assertTrue(check_join_rate_limit(self.student))
            record_join_attempt(self.student)
        self.assertFalse(check_join_rate_limit(self.student))

    def test_view_blocks_after_too_many_wrong_attempts(self):
        from .services import ensure_join_code

        ensure_join_code(self.class_offering)
        self.client.force_login(self.student)
        for _ in range(10):
            self.client.get(reverse("academics:join_with_code", args=["BADCODE"]))
        response = self.client.get(reverse("academics:join_with_code", args=["BADCODE"]))
        self.assertContains(response, "Too many attempts")


class ClassJoinViewTests(ClassJoinCodeTestBase):
    def test_join_view_shows_confirmation_for_valid_code(self):
        from .services import ensure_join_code

        code = ensure_join_code(self.class_offering)
        self.client.force_login(self.student)
        response = self.client.get(reverse("academics:join_with_code", args=[code]))
        self.assertContains(response, self.subject.code)
        self.assertContains(response, "Request to join")

    def test_join_view_post_creates_request(self):
        from .services import ensure_join_code

        code = ensure_join_code(self.class_offering)
        self.client.force_login(self.student)
        response = self.client.post(reverse("academics:join_with_code", args=[code]))
        self.assertContains(response, "Request sent")
        self.assertTrue(ClassJoinRequest.objects.filter(student=self.student, class_offering=self.class_offering).exists())

    def test_anonymous_user_redirected_to_login(self):
        from .services import ensure_join_code

        code = ensure_join_code(self.class_offering)
        response = self.client.get(reverse("academics:join_with_code", args=[code]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_student_cannot_decide_requests(self):
        join_request = self._request_join()
        self.client.force_login(self.student)
        response = self.client.post(
            reverse("academics:class_join_request_decide", args=[join_request.pk]), {"action": "approve"}
        )
        self.assertEqual(response.status_code, 403)

    def test_other_instructor_cannot_see_or_decide_requests(self):
        join_request = self._request_join()
        self.client.force_login(self.other_instructor)
        response = self.client.get(reverse("academics:class_roster", args=[self.class_offering.pk]))
        self.assertEqual(response.status_code, 403)

        response = self.client.post(
            reverse("academics:class_join_request_decide", args=[join_request.pk]), {"action": "approve"}
        )
        self.assertEqual(response.status_code, 403)
        join_request.refresh_from_db()
        self.assertEqual(join_request.status, ClassJoinRequest.Status.PENDING)

    def test_owner_instructor_can_approve_via_view(self):
        join_request = self._request_join()
        self.client.force_login(self.instructor)
        response = self.client.post(
            reverse("academics:class_join_request_decide", args=[join_request.pk]), {"action": "approve"}
        )
        self.assertEqual(response.status_code, 204)
        join_request.refresh_from_db()
        self.assertEqual(join_request.status, ClassJoinRequest.Status.APPROVED)

    def test_class_roster_page_shows_invite_card_and_pending_list_for_owner(self):
        self._request_join()
        self.client.force_login(self.instructor)
        response = self.client.get(reverse("academics:class_roster", args=[self.class_offering.pk]))
        self.assertContains(response, "Invite Students")
        self.assertContains(response, "Pending Requests")
        self.assertContains(response, self.student.full_name)

    def test_qr_endpoint_returns_svg(self):
        self.client.force_login(self.instructor)
        response = self.client.get(reverse("academics:class_join_qr", args=[self.class_offering.pk]))
        self.assertEqual(response["Content-Type"], "image/svg+xml")
        self.assertIn(b"<svg", response.content)

    def test_student_my_classes_shows_joined_and_pending(self):
        from .services import approve_join_request

        join_request = self._request_join()
        approve_join_request(join_request, self.instructor)

        other_student = make_user(User.Role.STUDENT, "join_student_pending_view")
        StudentProfile.objects.update_or_create(user=other_student, defaults={"program": self.program})
        pending_request = self._request_join(student=other_student)

        self.client.force_login(self.student)
        response = self.client.get(reverse("academics:student_my_classes"))
        self.assertContains(response, "Joined")

        self.client.force_login(other_student)
        response = self.client.get(reverse("academics:student_my_classes"))
        self.assertContains(response, "Pending approval")
