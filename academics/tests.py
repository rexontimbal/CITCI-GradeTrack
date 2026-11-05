from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

from .models import (
    AcademicYear,
    ClassOffering,
    ClassRosterEntry,
    Major,
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
    """ClassOffering.clean() can only check sections once the instance has a
    pk (M2M needs one) — the form-level check is what actually protects
    creation; see ClassOfferingForm.clean() in forms.py."""

    def setUp(self):
        self.ay_2026 = AcademicYear.objects.create(start_year=2026)
        self.ay_2027 = AcademicYear.objects.create(start_year=2027)
        self.program = Program.objects.create(code="BSIT", name="BS Information Technology")
        self.section_2026 = Section.objects.create(program=self.program, academic_year=self.ay_2026, year_level=1, name="A")
        self.section_2027 = Section.objects.create(program=self.program, academic_year=self.ay_2027, year_level=1, name="A")
        self.subject = Subject.objects.create(code="IT101", title="Intro to Computing", units=Decimal("3.0"), year_level=1, term=Term.FIRST)

    def test_class_offering_rejects_mismatched_academic_year_via_form(self):
        from .forms import ClassOfferingForm

        semester_2026 = Semester.objects.create(academic_year=self.ay_2026, term=Term.FIRST)
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

        semester_2026 = Semester.objects.create(academic_year=self.ay_2026, term=Term.FIRST)
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
        self.subject = Subject.objects.create(code="IT101", title="Intro to Computing", units=Decimal("3.0"), year_level=1, term=Term.FIRST)
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
        self.subject = Subject.objects.create(code="GE 2", title="Purposive Communication", units=Decimal("3.0"), term=Term.FIRST)
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
        self.subject = Subject.objects.create(code="IT101", title="Intro to Computing", units=Decimal("3.0"), year_level=1, term=Term.FIRST)

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
        other_subject = Subject.objects.create(code="IT102", title="Programming 1", units=Decimal("3.0"), year_level=1, term=Term.FIRST)
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
        self.subject = Subject.objects.create(code="IT101", title="Intro to Computing", units=Decimal("3.0"), year_level=1, term=Term.FIRST)
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

        self.subject = Subject.objects.create(code="PEd 205", title="Physical Education", units=Decimal("2.0"), term=Term.FIRST)
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


class BulkAssignInstructorTests(TeachingAssignmentTestBase):
    def setUp(self):
        super().setUp()
        self.other_class = ClassOffering.objects.create(subject=self.subject, semester=self.semester)
        self.other_class.sections.set([self.section_a])

    def test_program_head_bulk_assigns_only_classes_in_their_program(self):
        foreign_class = ClassOffering.objects.create(subject=self.subject, semester=self.semester)
        foreign_class.sections.set([self.section_b])

        self.client.force_login(self.head_a)
        self.client.post(
            reverse("academics:class_bulk_assign_instructor"),
            {"class_ids": [self.class_offering.pk, self.other_class.pk, foreign_class.pk], "instructor": self.instructor1.pk},
        )
        self.class_offering.refresh_from_db()
        self.other_class.refresh_from_db()
        foreign_class.refresh_from_db()
        self.assertEqual(self.class_offering.instructor_id, self.instructor1.id)
        self.assertEqual(self.other_class.instructor_id, self.instructor1.id)
        self.assertIsNone(foreign_class.instructor_id)  # not under head_a's program — silently skipped


class TeachingLoadsPageTests(TeachingAssignmentTestBase):
    def setUp(self):
        super().setUp()
        self.class_offering.instructor = self.instructor1
        self.class_offering.save()

        self.second_subject = Subject.objects.create(code="IT205", title="Databases", units=Decimal("3.0"), term=Term.FIRST)
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
