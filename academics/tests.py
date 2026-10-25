from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

from .models import (
    AcademicYear,
    ClassOffering,
    Enrollment,
    Program,
    Section,
    Semester,
    StudentProfile,
    Subject,
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


class AcademicYearTests(TestCase):
    def test_end_year_is_derived_from_start_year(self):
        ay = AcademicYear.objects.create(start_year=2026)
        self.assertEqual(ay.end_year, 2027)
        self.assertEqual(str(ay), "A.Y. 2026–2027")


class SectionSemesterValidationTests(TestCase):
    def setUp(self):
        self.ay_2026 = AcademicYear.objects.create(start_year=2026)
        self.ay_2027 = AcademicYear.objects.create(start_year=2027)
        self.program = Program.objects.create(code="BSIT", name="BS Information Technology")
        self.section = Section.objects.create(
            program=self.program, academic_year=self.ay_2026, year_level=1, name="A"
        )
        self.subject = Subject.objects.create(code="IT101", title="Intro to Computing", year_level=1, term=Term.FIRST)

    def test_class_offering_rejects_mismatched_academic_years(self):
        semester_2027 = Semester.objects.create(academic_year=self.ay_2027, term=Term.FIRST)
        offering = ClassOffering(subject=self.subject, section=self.section, semester=semester_2027)
        with self.assertRaises(Exception):
            offering.full_clean()

    def test_class_offering_accepts_matching_academic_years(self):
        semester_2026 = Semester.objects.create(academic_year=self.ay_2026, term=Term.FIRST)
        offering = ClassOffering(subject=self.subject, section=self.section, semester=semester_2026)
        offering.full_clean()  # should not raise
        offering.save()
        self.assertEqual(ClassOffering.objects.count(), 1)


class EnrollmentTests(TestCase):
    def setUp(self):
        self.ay = AcademicYear.objects.create(start_year=2026)
        self.semester = Semester.objects.create(academic_year=self.ay, term=Term.FIRST, is_active=True)
        self.program = Program.objects.create(code="BSIT", name="BS Information Technology")
        self.section = Section.objects.create(program=self.program, academic_year=self.ay, year_level=1, name="A")
        self.other_section = Section.objects.create(
            program=self.program, academic_year=self.ay, year_level=1, name="B"
        )
        self.subject = Subject.objects.create(code="IT101", title="Intro to Computing", year_level=1, term=Term.FIRST)
        self.class_offering = ClassOffering.objects.create(
            subject=self.subject, section=self.section, semester=self.semester
        )
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

    def test_enroll_entire_section_skips_already_enrolled(self):
        # pre-enroll one student manually
        Enrollment.objects.create(student=self.students_in_section[0], class_offering=self.class_offering)

        self.client.login(username="admin1", password="pw12345!")
        response = self.client.post(
            reverse("academics:enrollment_enroll_section", args=[self.class_offering.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("2 enrolled, 1 already enrolled", response.content.decode())

        enrolled_ids = set(
            Enrollment.objects.filter(class_offering=self.class_offering).values_list("student_id", flat=True)
        )
        self.assertEqual(enrolled_ids, {s.id for s in self.students_in_section})
        self.assertNotIn(self.outside_student.id, enrolled_ids)

    def test_drop_keeps_the_enrollment_record(self):
        enrollment = Enrollment.objects.create(student=self.students_in_section[0], class_offering=self.class_offering)

        self.client.login(username="admin1", password="pw12345!")
        self.client.post(reverse("academics:enrollment_drop", args=[enrollment.pk]))

        enrollment.refresh_from_db()
        self.assertEqual(enrollment.status, Enrollment.Status.DROPPED)
        self.assertEqual(enrollment.date_dropped, date.today())
        self.assertEqual(Enrollment.objects.count(), 1)  # still there, not deleted

    def test_reenroll_clears_drop_date(self):
        enrollment = Enrollment.objects.create(
            student=self.students_in_section[0],
            class_offering=self.class_offering,
            status=Enrollment.Status.DROPPED,
            date_dropped=date.today(),
        )
        self.client.login(username="admin1", password="pw12345!")
        self.client.post(reverse("academics:enrollment_reenroll", args=[enrollment.pk]))

        enrollment.refresh_from_db()
        self.assertEqual(enrollment.status, Enrollment.Status.ENROLLED)
        self.assertIsNone(enrollment.date_dropped)


class RoleAndObjectLevelAccessTests(TestCase):
    def setUp(self):
        self.ay = AcademicYear.objects.create(start_year=2026)
        self.semester = Semester.objects.create(academic_year=self.ay, term=Term.FIRST, is_active=True)
        self.program = Program.objects.create(code="BSIT", name="BS Information Technology")
        self.section = Section.objects.create(program=self.program, academic_year=self.ay, year_level=1, name="A")
        self.subject = Subject.objects.create(code="IT101", title="Intro to Computing", year_level=1, term=Term.FIRST)

        self.instructor1 = make_user(User.Role.INSTRUCTOR, "inst1")
        self.instructor2 = make_user(User.Role.INSTRUCTOR, "inst2")
        self.class_offering = ClassOffering.objects.create(
            subject=self.subject, section=self.section, semester=self.semester, instructor=self.instructor1
        )

        self.program_head_owner = make_user(User.Role.PROGRAM_HEAD, "ph_owner")
        self.program_head_other = make_user(User.Role.PROGRAM_HEAD, "ph_other")
        self.program.program_head = self.program_head_owner
        self.program.save()

        self.student = make_user(User.Role.STUDENT, "stud_role_test")

    def test_student_gets_403_on_admin_classes_page(self):
        self.client.login(username="stud_role_test", password="pw12345!")
        response = self.client.get(reverse("academics:classes"))
        self.assertEqual(response.status_code, 403)

    def test_instructor_cannot_open_another_instructors_roster(self):
        self.client.login(username="inst2", password="pw12345!")
        response = self.client.get(reverse("academics:class_roster", args=[self.class_offering.pk]))
        self.assertEqual(response.status_code, 403)

    def test_owning_instructor_can_open_their_own_roster(self):
        self.client.login(username="inst1", password="pw12345!")
        response = self.client.get(reverse("academics:class_roster", args=[self.class_offering.pk]))
        self.assertEqual(response.status_code, 200)

    def test_program_head_cannot_open_another_programs_class(self):
        self.client.login(username="ph_other", password="pw12345!")
        response = self.client.get(reverse("academics:class_roster", args=[self.class_offering.pk]))
        self.assertEqual(response.status_code, 403)

    def test_owning_program_head_can_open_the_roster(self):
        self.client.login(username="ph_owner", password="pw12345!")
        response = self.client.get(reverse("academics:class_roster", args=[self.class_offering.pk]))
        self.assertEqual(response.status_code, 200)


class StudentProfileSignalTests(TestCase):
    def test_creating_a_student_user_auto_creates_a_profile(self):
        user = make_user(User.Role.STUDENT, "autoprofile")
        self.assertTrue(StudentProfile.objects.filter(user=user).exists())

    def test_creating_a_non_student_user_does_not_create_a_profile(self):
        user = make_user(User.Role.INSTRUCTOR, "noprofile")
        self.assertFalse(StudentProfile.objects.filter(user=user).exists())


class SubjectTotalUnitsTests(TestCase):
    def test_total_units_sums_lec_and_lab(self):
        subject = Subject.objects.create(
            code="IT102", title="Programming 1", lec_units=Decimal("2.0"), lab_units=Decimal("1.0"),
            year_level=1, term=Term.FIRST,
        )
        self.assertEqual(subject.total_units, Decimal("3.0"))
