from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from academics.models import (
    AcademicYear,
    ClassOffering,
    ClassRosterEntry,
    Program,
    Section,
    Semester,
    StudentProfile,
    Subject,
    Term,
)
from accounts.models import User
from dashboard.models import Notification
from grading.models import AssessmentTerm
from grading.tests import GradingTestBase, make_user

from .models import GradeCorrection, GradeSheet, GradeSheetEntry, GradeSheetStatus, GradeSheetTransition, IncCompletion, IncCompletionStatus
from .services import (
    approve_grade_sheet,
    can_file_inc_completion,
    compute_gwa,
    correct_grade,
    decide_inc_completion,
    file_inc_completion,
    inc_completions_to_file_for_instructor,
    lock_term,
    pending_inc_completions_for_program_head,
    release_grade_sheet,
    return_grade_sheet,
    submit_grade_sheet,
)


class ApprovalsTestBase(GradingTestBase):
    """Reuses grading.tests.GradingTestBase's class/roster/scheme fixture and
    adds a Program Head (owning the class's program) and an Admin."""

    def setUp(self):
        super().setUp()
        self.program_head = make_user(User.Role.PROGRAM_HEAD, "ph1")
        self.program.program_head = self.program_head
        self.program.save()
        self.admin = make_user(User.Role.ADMIN, "admin1")

    def fully_score_class(self):
        """Row 11 (Dela Cruz) data — complete, so compute/submit works
        cleanly with no missing cells."""
        attendance_items = self.make_items("Attendance", [10, 10, 10, 10, 10])
        quiz_items = self.make_items("Quizzes", [20, 20, 30, 20, 30, 40, 50])
        recitation_items = self.make_items("Recitation", [10, 10, 20, 30, 30, 30, 40])
        project_items = self.make_items("Project", [50, 70, 60, 80, 90])
        exam_items = self.make_items("Examination", [80, 100, 80, 100])
        for item, term in zip(
            exam_items, [AssessmentTerm.PRELIM, AssessmentTerm.MIDTERM, AssessmentTerm.SEMIFINAL, AssessmentTerm.FINAL]
        ):
            item.term = term
            item.save(update_fields=["term"])

        self.set_scores(self.roster_entry, attendance_items, [10, 10, 10, 5, 10])
        self.set_scores(self.roster_entry, quiz_items, [15, 18, 21, 15, 25, 29, 37])
        self.set_scores(self.roster_entry, recitation_items, [6, 8, 16, 24, 27, 22, 34])
        self.set_scores(self.roster_entry, project_items, [45, 65, 50, 76, 82])
        self.set_scores(self.roster_entry, exam_items, [59, 87, 67, 76])


class TransitionTests(ApprovalsTestBase):
    def setUp(self):
        super().setUp()
        self.fully_score_class()

    def test_submit_from_draft_succeeds(self):
        sheet = submit_grade_sheet(self.class_offering, self.instructor)
        self.assertEqual(sheet.status, GradeSheetStatus.SUBMITTED)
        self.assertEqual(sheet.entries.count(), 1)

    def test_approve_requires_submitted_status(self):
        sheet = GradeSheet.get_or_create_draft(self.class_offering)
        with self.assertRaises(ValidationError):
            approve_grade_sheet(sheet, self.program_head)

    def test_release_requires_approved_status(self):
        sheet = submit_grade_sheet(self.class_offering, self.instructor)
        with self.assertRaises(ValidationError):
            release_grade_sheet(sheet, self.program_head)

    def test_full_happy_path(self):
        sheet = submit_grade_sheet(self.class_offering, self.instructor)
        approve_grade_sheet(sheet, self.program_head)
        sheet.refresh_from_db()
        self.assertEqual(sheet.status, GradeSheetStatus.APPROVED)

        release_grade_sheet(sheet, self.program_head)
        sheet.refresh_from_db()
        self.assertEqual(sheet.status, GradeSheetStatus.RELEASED)

        locked = lock_term(self.semester, self.admin)
        self.assertEqual(len(locked), 1)
        sheet.refresh_from_db()
        self.assertEqual(sheet.status, GradeSheetStatus.LOCKED)

    def test_return_then_resubmit(self):
        sheet = submit_grade_sheet(self.class_offering, self.instructor)
        return_grade_sheet(sheet, self.program_head, "Please fix the quiz scores")
        sheet.refresh_from_db()
        self.assertEqual(sheet.status, GradeSheetStatus.RETURNED)
        self.assertEqual(sheet.return_remarks, "Please fix the quiz scores")

        sheet2 = submit_grade_sheet(self.class_offering, self.instructor)
        self.assertEqual(sheet2.pk, sheet.pk)
        self.assertEqual(sheet2.status, GradeSheetStatus.SUBMITTED)

    def test_return_requires_remarks(self):
        sheet = submit_grade_sheet(self.class_offering, self.instructor)
        with self.assertRaises(ValidationError):
            return_grade_sheet(sheet, self.program_head, "")

    def test_cannot_submit_twice_without_a_return(self):
        submit_grade_sheet(self.class_offering, self.instructor)
        with self.assertRaises(ValidationError):
            submit_grade_sheet(self.class_offering, self.instructor)

    def test_resubmit_replaces_the_snapshot(self):
        sheet = submit_grade_sheet(self.class_offering, self.instructor)
        old_grade = sheet.entries.first().final_grade
        return_grade_sheet(sheet, self.program_head, "fix it")

        quiz_item = self.scheme_components["Quizzes"].items.first()
        from grading.services import save_score

        save_score(self.roster_entry, quiz_item, 0, self.instructor)

        submit_grade_sheet(self.class_offering, self.instructor)
        sheet.refresh_from_db()
        self.assertEqual(sheet.entries.count(), 1)  # replaced, not duplicated
        self.assertNotEqual(sheet.entries.first().final_grade, old_grade)


class SubmitBlockingTests(ApprovalsTestBase):
    def test_submit_blocked_with_missing_scores(self):
        self.make_items("Attendance", [10])  # created, left blank
        with self.assertRaises(ValidationError):
            submit_grade_sheet(self.class_offering, self.instructor)

    def test_submit_allowed_when_the_missing_student_is_marked_inc(self):
        self.make_items("Attendance", [10])
        self.roster_entry.is_incomplete = True
        self.roster_entry.incomplete_reason = "Hospitalized"
        self.roster_entry.save()

        sheet = submit_grade_sheet(self.class_offering, self.instructor)
        self.assertEqual(sheet.status, GradeSheetStatus.SUBMITTED)
        entry = sheet.entries.first()
        self.assertEqual(entry.remarks, "INC")
        self.assertEqual(entry.inc_reason, "Hospitalized")


class EditLockTests(ApprovalsTestBase):
    def setUp(self):
        super().setUp()
        self.fully_score_class()
        self.sheet = submit_grade_sheet(self.class_offering, self.instructor)

    def test_instructor_cannot_save_a_score_while_submitted(self):
        item = self.scheme_components["Attendance"].items.first()
        self.client.force_login(self.instructor)
        response = self.client.post(reverse("grading:save_cell", args=[self.roster_entry.pk, item.pk]), {"value": "5"})
        self.assertEqual(response.status_code, 403)

    def test_instructor_cannot_edit_components_while_submitted(self):
        self.client.force_login(self.instructor)
        response = self.client.post(reverse("grading:class_components_save", args=[self.class_offering.pk]), {})
        self.assertEqual(response.status_code, 403)

    def test_instructor_cannot_add_an_item_while_approved(self):
        approve_grade_sheet(self.sheet, self.program_head)
        self.client.force_login(self.instructor)
        response = self.client.post(
            reverse("grading:item_create", args=[self.class_offering.pk]),
            {"component": self.scheme_components["Attendance"].pk, "title": "Extra", "max_score": "10", "term": "PRELIM", "order": "0"},
        )
        self.assertEqual(response.status_code, 403)

    def test_instructor_can_edit_again_once_returned(self):
        return_grade_sheet(self.sheet, self.program_head, "fix")
        item = self.scheme_components["Attendance"].items.first()
        self.client.force_login(self.instructor)
        response = self.client.post(reverse("grading:save_cell", args=[self.roster_entry.pk, item.pk]), {"value": "5"})
        self.assertEqual(response.status_code, 200)


class GradeCorrectionTests(ApprovalsTestBase):
    def setUp(self):
        super().setUp()
        self.fully_score_class()
        sheet = submit_grade_sheet(self.class_offering, self.instructor)
        approve_grade_sheet(sheet, self.program_head)
        self.sheet = release_grade_sheet(sheet, self.program_head)
        self.entry = self.sheet.entries.first()

    def test_correction_requires_a_reason(self):
        with self.assertRaises(ValidationError):
            correct_grade(self.entry, self.admin, Decimal("2.00"), "PASSED", "")

    def test_correction_rejected_when_sheet_is_not_released_or_locked(self):
        self.sheet.status = GradeSheetStatus.SUBMITTED
        self.sheet.save()
        entry = GradeSheetEntry.objects.get(pk=self.entry.pk)
        with self.assertRaises(ValidationError):
            correct_grade(entry, self.admin, Decimal("2.00"), "PASSED", "testing")

    def test_correction_allowed_when_locked(self):
        self.sheet.status = GradeSheetStatus.LOCKED
        self.sheet.save()
        entry = GradeSheetEntry.objects.get(pk=self.entry.pk)
        correct_grade(entry, self.admin, Decimal("2.00"), "PASSED", "Recomputation error")
        entry.refresh_from_db()
        self.assertEqual(entry.final_grade, Decimal("2.00"))

    def test_correction_is_logged_and_marks_entry_corrected(self):
        correct_grade(self.entry, self.admin, Decimal("2.00"), "PASSED", "Recomputation error")
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.final_grade, Decimal("2.00"))
        self.assertTrue(self.entry.is_corrected)

        correction = GradeCorrection.objects.filter(entry=self.entry).first()
        self.assertIsNotNone(correction)
        self.assertEqual(correction.reason, "Recomputation error")
        self.assertEqual(correction.corrected_by, self.admin)

        self.assertTrue(
            GradeSheetTransition.objects.filter(sheet=self.sheet, remarks__icontains="Recomputation error").exists()
        )


class ProgramHeadAuthorizationTests(ApprovalsTestBase):
    def setUp(self):
        super().setUp()
        self.fully_score_class()
        self.sheet = submit_grade_sheet(self.class_offering, self.instructor)
        self.other_program_head = make_user(User.Role.PROGRAM_HEAD, "ph2")

    def test_other_program_head_review_gets_403(self):
        self.client.force_login(self.other_program_head)
        response = self.client.get(reverse("approvals:review", args=[self.sheet.pk]))
        self.assertEqual(response.status_code, 403)

    def test_other_program_head_approve_gets_403(self):
        self.client.force_login(self.other_program_head)
        response = self.client.post(reverse("approvals:approve", args=[self.sheet.pk]))
        self.assertEqual(response.status_code, 403)

    def test_owning_program_head_can_review(self):
        self.client.force_login(self.program_head)
        response = self.client.get(reverse("approvals:review", args=[self.sheet.pk]))
        self.assertEqual(response.status_code, 200)


class NotificationTests(ApprovalsTestBase):
    def setUp(self):
        super().setUp()
        self.fully_score_class()

    def test_submit_notifies_the_program_head(self):
        submit_grade_sheet(self.class_offering, self.instructor)
        self.assertTrue(Notification.objects.filter(recipient=self.program_head, title__icontains="submitted").exists())

    def test_return_notifies_instructor_with_remarks(self):
        sheet = submit_grade_sheet(self.class_offering, self.instructor)
        return_grade_sheet(sheet, self.program_head, "Fix attendance")
        notif = Notification.objects.filter(recipient=self.instructor, title__icontains="returned").first()
        self.assertIsNotNone(notif)
        self.assertIn("Fix attendance", notif.message)

    def test_approve_notifies_instructor(self):
        sheet = submit_grade_sheet(self.class_offering, self.instructor)
        approve_grade_sheet(sheet, self.program_head)
        self.assertTrue(Notification.objects.filter(recipient=self.instructor, title__icontains="approved").exists())

    def test_release_notifies_instructor(self):
        sheet = submit_grade_sheet(self.class_offering, self.instructor)
        approve_grade_sheet(sheet, self.program_head)
        release_grade_sheet(sheet, self.program_head)
        self.assertTrue(Notification.objects.filter(recipient=self.instructor, title__icontains="released").exists())

    def test_correction_notifies_instructor(self):
        sheet = submit_grade_sheet(self.class_offering, self.instructor)
        approve_grade_sheet(sheet, self.program_head)
        sheet = release_grade_sheet(sheet, self.program_head)
        entry = sheet.entries.first()
        correct_grade(entry, self.admin, Decimal("2.00"), "PASSED", "fix")
        self.assertTrue(Notification.objects.filter(recipient=self.instructor, title__icontains="correction").exists())


class GwaTests(TestCase):
    def setUp(self):
        self.academic_year = AcademicYear.objects.create(start_year=2026)
        self.semester = Semester.objects.create(academic_year=self.academic_year, term=Term.FIRST, is_active=True)
        self.program = Program.objects.create(code="BSED", name="BS Education")
        self.section = Section.objects.create(program=self.program, academic_year=self.academic_year, year_level=1, name="A")
        self.student = make_user(User.Role.STUDENT, "gwa_student", id_number="2026-9999")
        StudentProfile.objects.update_or_create(user=self.student, defaults={"program": self.program, "section": self.section})
        self.instructor = make_user(User.Role.INSTRUCTOR, "gwa_prof")

    def _make_entry(self, subject_code, units, final_grade, remarks="PASSED", sheet_status=GradeSheetStatus.RELEASED, roster_status=ClassRosterEntry.Status.ACTIVE):
        subject = Subject.objects.create(code=subject_code, title=subject_code, units=Decimal(str(units)), term=Term.FIRST)
        class_offering = ClassOffering.objects.create(subject=subject, semester=self.semester, instructor=self.instructor)
        class_offering.sections.set([self.section])
        roster_entry = ClassRosterEntry.objects.create(student=self.student, class_offering=class_offering, status=roster_status)
        sheet = GradeSheet.objects.create(class_offering=class_offering, status=sheet_status)
        return GradeSheetEntry.objects.create(
            sheet=sheet, roster_entry=roster_entry, final_grade=Decimal(str(final_grade)), remarks=remarks
        )

    def test_gwa_weighted_by_units(self):
        self._make_entry("PATHFIT2", 2, "1.50")
        self._make_entry("PRACTICUM", 6, "2.00")
        result = compute_gwa(self.student, self.semester)
        # (1.50*2 + 2.00*6) / 8 = 15/8 = 1.875 -> 1.88 (ROUND_HALF_UP via quantize)
        self.assertEqual(result["gwa"], Decimal("1.88"))
        self.assertEqual(result["total_units"], Decimal("8"))
        self.assertTrue(result["is_complete"])

    def test_gwa_excludes_dropped_and_inc(self):
        self._make_entry("IT101", 3, "1.50")
        self._make_entry("IT102", 3, "5.00", remarks="DROPPED", roster_status=ClassRosterEntry.Status.DROPPED)
        self._make_entry("IT103", 3, "5.00", remarks="INC")
        result = compute_gwa(self.student, self.semester)
        self.assertEqual(result["gwa"], Decimal("1.50"))
        self.assertEqual(result["total_units"], Decimal("3"))
        self.assertFalse(result["is_complete"])  # the INC class makes it incomplete (DROPPED doesn't count against it)

    def test_gwa_incomplete_when_a_class_is_not_released_yet(self):
        subject = Subject.objects.create(code="IT201", title="Pending", units=Decimal("3.0"), term=Term.FIRST)
        class_offering = ClassOffering.objects.create(subject=subject, semester=self.semester, instructor=self.instructor)
        class_offering.sections.set([self.section])
        ClassRosterEntry.objects.create(student=self.student, class_offering=class_offering)

        result = compute_gwa(self.student, self.semester)
        self.assertFalse(result["is_complete"])
        self.assertIsNone(result["gwa"])


class FinalRemarksSnapshotTests(ApprovalsTestBase):
    """Regression tests for the bug where a submitted/released
    GradeSheetEntry could be frozen with a provisional ON_TRACK/AT_RISK
    label (grading.services.StudentGradeResult.remarks, meant for mid-term
    display only) instead of a FINAL PASSED/FAILED one. Root cause: a
    sparse gradebook (some component with zero items — "not yet set up")
    doesn't block submit (missing_score_students only checks existing,
    unencoded items), but made is_grade_complete False, which routed
    submit_grade_sheet through the provisional label. Fixed by always
    snapshotting `result.final_remarks` (never `result.remarks`)."""

    def test_submit_with_a_not_yet_set_up_component_stores_passed_or_failed_only(self):
        # Only Quizzes gets items — Attendance/Recitation/Project/Examination
        # are left at zero items ("not yet set up"), same shape as the real
        # bug report. Nothing here is "missing" from missing_score_students'
        # point of view, so submit succeeds.
        quiz_items = self.make_items("Quizzes", [20])
        self.set_scores(self.roster_entry, quiz_items, [19])  # would show "ON_TRACK" pre-fix

        sheet = submit_grade_sheet(self.class_offering, self.instructor)
        entry = sheet.entries.get(roster_entry=self.roster_entry)
        self.assertIn(entry.remarks, ("PASSED", "FAILED"))
        self.assertNotIn(entry.remarks, ("ON_TRACK", "AT_RISK"))

    def test_submit_boundary_grade_of_exactly_3_00_is_passed(self):
        items_by_component = {
            name: self.make_items(name, [10]) for name in ("Attendance", "Quizzes", "Recitation", "Project", "Examination")
        }
        for items in items_by_component.values():
            self.set_scores(self.roster_entry, items, [5])  # every component grade == 3.00 exactly

        sheet = submit_grade_sheet(self.class_offering, self.instructor)
        entry = sheet.entries.get(roster_entry=self.roster_entry)
        self.assertEqual(entry.final_grade, Decimal("3.00"))
        self.assertEqual(entry.remarks, "PASSED")

    def test_invalid_remarks_rejected_at_the_database_level(self):
        """Model-level guard: even a direct .create() bypassing full_clean()
        can't write a provisional label into the frozen snapshot."""
        from django.db import IntegrityError, transaction

        self.fully_score_class()
        sheet = submit_grade_sheet(self.class_offering, self.instructor)
        entry = sheet.entries.first()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                GradeSheetEntry.objects.create(
                    sheet=sheet, roster_entry=entry.roster_entry, final_grade=Decimal("4.80"), remarks="ON_TRACK"
                )

    def test_reports_and_pdf_never_show_provisional_labels(self):
        """End-to-end: the Reports page's class-performance counts and the
        Grade Sheet PDF both read straight off the snapshot — if the
        snapshot is fixed, neither can surface a provisional label."""
        quiz_items = self.make_items("Quizzes", [20])
        self.set_scores(self.roster_entry, quiz_items, [19])
        sheet = submit_grade_sheet(self.class_offering, self.instructor)
        approve_grade_sheet(sheet, self.program_head)
        release_grade_sheet(sheet, self.program_head)

        from reports.services import class_performance_rows

        rows = class_performance_rows(self.semester, Program.objects.filter(pk=self.program.pk))
        self.assertEqual(rows[0]["counts"]["PASSED"] + rows[0]["counts"]["FAILED"], 1)
        self.assertNotIn("ON_TRACK", rows[0]["counts"])
        self.assertNotIn("AT_RISK", rows[0]["counts"])

        self.client.force_login(self.instructor)
        response = self.client.get(reverse("reports:grade_sheet_pdf", args=[sheet.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"ON_TRACK", response.content)
        self.assertNotIn(b"AT_RISK", response.content)

    def test_gwa_unaffected_by_the_remarks_fix(self):
        """GWA has always summed final_grade directly and only excludes
        DROPPED/INC remarks — it never keyed off PASSED vs FAILED, so this
        is a non-regression check, not a behavior change."""
        self.fully_score_class()
        sheet = submit_grade_sheet(self.class_offering, self.instructor)
        approve_grade_sheet(sheet, self.program_head)
        release_grade_sheet(sheet, self.program_head)

        result = compute_gwa(self.roster_entry.student, self.semester)
        entry = sheet.entries.get(roster_entry=self.roster_entry)
        # Single subject -> GWA is just that subject's own final grade.
        self.assertEqual(result["gwa"], entry.final_grade.quantize(Decimal("0.01")))
        self.assertTrue(result["is_complete"])

    def test_gwa_none_when_no_released_entries(self):
        result = compute_gwa(self.student, self.semester)
        self.assertIsNone(result["gwa"])


class IncCompletionTestBase(ApprovalsTestBase):
    """A released sheet with an INC entry — the starting point for every
    INC-completion test below."""

    def setUp(self):
        super().setUp()
        self.roster_entry.is_incomplete = True
        self.roster_entry.incomplete_reason = "Hospitalized"
        self.roster_entry.save()
        self.make_items("Attendance", [10])  # left blank, but INC exempts it from missing_score_students
        sheet = submit_grade_sheet(self.class_offering, self.instructor)
        approve_grade_sheet(sheet, self.program_head)
        self.sheet = release_grade_sheet(sheet, self.program_head)
        self.entry = self.sheet.entries.get(roster_entry=self.roster_entry)
        self.assertEqual(self.entry.remarks, "INC")


class IncCompletionFilingTests(IncCompletionTestBase):
    def test_can_file_when_released_and_inc(self):
        allowed, reason = can_file_inc_completion(self.entry)
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_cannot_file_when_not_inc(self):
        self.entry.remarks = "PASSED"
        self.entry.final_grade = Decimal("1.50")
        self.entry.save()
        allowed, reason = can_file_inc_completion(self.entry)
        self.assertFalse(allowed)

    def test_cannot_file_when_sheet_not_released_or_locked(self):
        self.sheet.status = GradeSheetStatus.SUBMITTED
        self.sheet.save()
        entry = GradeSheetEntry.objects.get(pk=self.entry.pk)
        allowed, reason = can_file_inc_completion(entry)
        self.assertFalse(allowed)

    def test_cannot_file_twice_while_pending(self):
        file_inc_completion(self.entry, self.instructor, Decimal("1.50"), "PASSED", "2026-01-15")
        allowed, reason = can_file_inc_completion(self.entry)
        self.assertFalse(allowed)
        self.assertIn("already filed", reason)

    def test_can_refile_after_a_rejection(self):
        completion = file_inc_completion(self.entry, self.instructor, Decimal("1.50"), "PASSED", "2026-01-15")
        decide_inc_completion(completion, self.program_head, approve=False, decision_remarks="Not enough proof")
        allowed, reason = can_file_inc_completion(self.entry)
        self.assertTrue(allowed)

    def test_filing_must_resolve_to_passed_or_failed(self):
        with self.assertRaises(ValidationError):
            file_inc_completion(self.entry, self.instructor, Decimal("5.00"), "INC", "2026-01-15")

    def test_pending_completion_notifies_program_heads(self):
        file_inc_completion(self.entry, self.instructor, Decimal("1.50"), "PASSED", "2026-01-15")
        self.assertTrue(Notification.objects.filter(recipient=self.program_head, title__icontains="INC").exists())


class IncCompletionWindowTests(IncCompletionTestBase):
    def test_lapsed_window_blocks_filing_with_no_automatic_grade_change(self):
        from reports.models import InstitutionSettings

        InstitutionSettings.get_solo()
        InstitutionSettings.objects.filter(pk=1).update(inc_completion_window_days=0)
        self.sheet.released_at = self.sheet.released_at.replace(year=self.sheet.released_at.year - 1)
        self.sheet.save(update_fields=["released_at"])

        allowed, reason = can_file_inc_completion(self.entry)
        self.assertFalse(allowed)
        self.assertEqual(reason, "INC lapsed — contact Registrar.")
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.remarks, "INC")  # untouched

    def test_configurable_window_allows_filing_within_it(self):
        from reports.models import InstitutionSettings

        InstitutionSettings.get_solo()
        InstitutionSettings.objects.filter(pk=1).update(inc_completion_window_days=3650)
        allowed, reason = can_file_inc_completion(self.entry)
        self.assertTrue(allowed)


class IncCompletionApprovalTests(IncCompletionTestBase):
    def setUp(self):
        super().setUp()
        self.completion = file_inc_completion(
            self.entry, self.instructor, Decimal("1.50"), "PASSED", "2026-01-15", "Submitted late work"
        )

    def test_approval_reuses_correct_grade_mechanism(self):
        decide_inc_completion(self.completion, self.program_head, approve=True)

        self.entry.refresh_from_db()
        self.assertEqual(self.entry.final_grade, Decimal("1.50"))
        self.assertEqual(self.entry.remarks, "PASSED")
        self.assertTrue(GradeCorrection.objects.filter(entry=self.entry).exists())
        self.assertTrue(
            GradeSheetTransition.objects.filter(sheet=self.sheet, from_status=self.sheet.status, to_status=self.sheet.status).exists()
        )

    def test_approval_marks_completion_approved_and_notifies_both(self):
        decide_inc_completion(self.completion, self.program_head, approve=True)
        self.completion.refresh_from_db()
        self.assertEqual(self.completion.status, IncCompletionStatus.APPROVED)
        self.assertEqual(self.completion.decided_by, self.program_head)

        self.assertTrue(Notification.objects.filter(recipient=self.instructor, title__icontains="INC completion approved").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.roster_entry.student, title__icontains="INC completed").exists())

    def test_gwa_reflects_the_corrected_grade_immediately(self):
        before = compute_gwa(self.roster_entry.student, self.semester)
        self.assertFalse(before["is_complete"])  # still INC

        decide_inc_completion(self.completion, self.program_head, approve=True)

        after = compute_gwa(self.roster_entry.student, self.semester)
        self.assertTrue(after["is_complete"])
        self.assertEqual(after["gwa"], Decimal("1.50"))

    def test_cannot_decide_an_already_decided_completion(self):
        decide_inc_completion(self.completion, self.program_head, approve=True)
        with self.assertRaises(ValidationError):
            decide_inc_completion(self.completion, self.program_head, approve=True)


class IncCompletionRejectionTests(IncCompletionTestBase):
    def setUp(self):
        super().setUp()
        self.completion = file_inc_completion(self.entry, self.instructor, Decimal("1.50"), "PASSED", "2026-01-15")

    def test_rejection_requires_remarks(self):
        with self.assertRaises(ValidationError):
            decide_inc_completion(self.completion, self.program_head, approve=False, decision_remarks="")

    def test_rejection_leaves_entry_untouched_and_notifies_only_instructor(self):
        decide_inc_completion(self.completion, self.program_head, approve=False, decision_remarks="Not enough proof")

        self.entry.refresh_from_db()
        self.assertEqual(self.entry.remarks, "INC")
        self.completion.refresh_from_db()
        self.assertEqual(self.completion.status, IncCompletionStatus.REJECTED)

        self.assertTrue(Notification.objects.filter(recipient=self.instructor, title__icontains="rejected").exists())
        self.assertFalse(Notification.objects.filter(recipient=self.roster_entry.student, title__icontains="rejected").exists())


class IncCompletionScopeTests(IncCompletionTestBase):
    def setUp(self):
        super().setUp()
        self.completion = file_inc_completion(self.entry, self.instructor, Decimal("1.50"), "PASSED", "2026-01-15")
        self.other_instructor = make_user(User.Role.INSTRUCTOR, "other_inc_instructor")
        self.other_program_head = make_user(User.Role.PROGRAM_HEAD, "other_inc_ph")

    def test_program_head_only_sees_their_own_program(self):
        self.assertIn(self.completion, pending_inc_completions_for_program_head(self.program_head))
        self.assertNotIn(self.completion, pending_inc_completions_for_program_head(self.other_program_head))

    def test_already_filed_entry_disappears_from_the_to_file_list(self):
        # self.completion (created in setUp) is PENDING for self.entry, so
        # it must no longer appear in the "still needs filing" list.
        self.assertNotIn(self.entry, inc_completions_to_file_for_instructor(self.instructor))

    def test_other_instructor_sees_nothing(self):
        self.assertEqual(inc_completions_to_file_for_instructor(self.other_instructor).count(), 0)

    def test_other_instructor_gets_403_filing(self):
        self.client.force_login(self.other_instructor)
        response = self.client.get(reverse("approvals:inc_completion_file", args=[self.entry.pk]))
        self.assertEqual(response.status_code, 403)

    def test_other_program_head_gets_403_deciding(self):
        self.client.force_login(self.other_program_head)
        response = self.client.get(reverse("approvals:inc_completion_decide", args=[self.completion.pk]))
        self.assertEqual(response.status_code, 403)


class IncCompletionDashboardBadgeTests(IncCompletionTestBase):
    def test_sidebar_badge_includes_pending_inc_completions(self):
        from accounts.context_processors import _sidebar_badges

        file_inc_completion(self.entry, self.instructor, Decimal("1.50"), "PASSED", "2026-01-15")
        badges = _sidebar_badges(self.program_head)
        self.assertEqual(badges.get("approvals:index"), 1)
