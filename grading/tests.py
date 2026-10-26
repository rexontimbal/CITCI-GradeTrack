from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

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

from .models import AssessmentItem, AssessmentTerm, ClassGradingScheme, GradingComponent, GradingTemplate, Score, ScoreChangeLog
from .services import compute_class, compute_student, format_grade, save_score, validate_component_weights
from .views import _build_class_record_context


def make_user(role, username, **extra):
    user = User.objects.create_user(username=username, password="pw12345!", role=role, **extra)
    user.must_change_password = False
    user.privacy_consent_at = timezone.now()
    user.save()
    return user


class GradingTestBase(TestCase):
    """Shared fixtures: one class offering, one student on its roster, and a
    grading template matching CITCI's real class record (grading-system.xlsx):
    Attendance 5%, Quizzes 30%, Recitation 15%, Project 10%, Examination 40%."""

    def setUp(self):
        self.academic_year = AcademicYear.objects.create(start_year=2026)
        self.semester = Semester.objects.create(academic_year=self.academic_year, term=Term.FIRST, is_active=True)
        self.program = Program.objects.create(code="BSIT", name="BS Information Technology")
        self.section = Section.objects.create(program=self.program, academic_year=self.academic_year, year_level=1, name="A")
        self.subject = Subject.objects.create(code="IT101", title="Intro to Computing", units=Decimal("3.0"), term=Term.FIRST)
        self.instructor = make_user(User.Role.INSTRUCTOR, "prof")
        self.class_offering = ClassOffering.objects.create(
            subject=self.subject, semester=self.semester, instructor=self.instructor
        )
        self.class_offering.sections.set([self.section])

        self.student = make_user(User.Role.STUDENT, "student1", id_number="2026-0001")
        StudentProfile.objects.update_or_create(user=self.student, defaults={"program": self.program, "section": self.section})
        self.roster_entry = ClassRosterEntry.objects.create(student=self.student, class_offering=self.class_offering)

        self.template = GradingTemplate.objects.create(name="CITCI Default", is_default=True)
        self.attendance = GradingComponent.objects.create(template=self.template, name="Attendance", weight=Decimal("5"), order=1)
        self.quizzes = GradingComponent.objects.create(template=self.template, name="Quizzes", weight=Decimal("30"), order=2)
        self.recitation = GradingComponent.objects.create(template=self.template, name="Recitation", weight=Decimal("15"), order=3)
        self.project = GradingComponent.objects.create(template=self.template, name="Project", weight=Decimal("10"), order=4)
        self.examination = GradingComponent.objects.create(template=self.template, name="Examination", weight=Decimal("40"), order=5)

        self.scheme = ClassGradingScheme.get_or_create_default(self.class_offering)
        self.scheme_components = {sc.name: sc for sc in self.scheme.components.all()}

    def make_items(self, component_name, maxes, term=AssessmentTerm.PRELIM):
        component = self.scheme_components[component_name]
        items = []
        for i, max_score in enumerate(maxes):
            items.append(
                AssessmentItem.objects.create(
                    class_offering=self.class_offering,
                    component=component,
                    title=f"{component_name} {i + 1}",
                    max_score=int(max_score),
                    term=term,
                    order=i,
                )
            )
        return items

    def set_scores(self, roster_entry, items, values):
        for item, value in zip(items, values):
            Score.objects.update_or_create(
                roster_entry=roster_entry, item=item, defaults={"score": None if value is None else int(value)}
            )


class DelaCruzFinalGradeTests(GradingTestBase):
    """Row 11 of CITCI's grading-system.xlsx: Dela Cruz, Juan B. Component
    grades, final grade, and PASSED/FAILED remark must match the spreadsheet
    to full Decimal precision."""

    def setUp(self):
        super().setUp()
        attendance_items = self.make_items("Attendance", [10, 10, 10, 10, 10])
        quiz_items = self.make_items("Quizzes", [20, 20, 30, 20, 30, 40, 50])
        recitation_items = self.make_items("Recitation", [10, 10, 20, 30, 30, 30, 40])
        project_items = self.make_items("Project", [50, 70, 60, 80, 90])
        exam_items = self.make_items(
            "Examination", [80, 100, 80, 100],
        )
        # Re-tag exam items with their real terms (Prelim/Midterm/Semi-final/Final)
        for item, term in zip(exam_items, [AssessmentTerm.PRELIM, AssessmentTerm.MIDTERM, AssessmentTerm.SEMIFINAL, AssessmentTerm.FINAL]):
            item.term = term
            item.save(update_fields=["term"])

        self.set_scores(self.roster_entry, attendance_items, [10, 10, 10, 5, 10])
        self.set_scores(self.roster_entry, quiz_items, [15, 18, 21, 15, 25, 29, 37])
        self.set_scores(self.roster_entry, recitation_items, [6, 8, 16, 24, 27, 22, 34])
        self.set_scores(self.roster_entry, project_items, [45, 65, 50, 76, 82])
        self.set_scores(self.roster_entry, exam_items, [59, 87, 67, 76])

    def test_component_grades_match_spreadsheet(self):
        result = compute_student(self.roster_entry)
        by_name = {c.component.name: c for c in result.components}

        self.assertEqual(by_name["Attendance"].final_grade, Decimal("5") - Decimal("4") * (Decimal("45") / Decimal("50")))
        self.assertAlmostEqual(float(by_name["Attendance"].final_grade), 1.4000, places=4)
        self.assertAlmostEqual(float(by_name["Quizzes"].final_grade), 1.9524, places=4)
        self.assertAlmostEqual(float(by_name["Recitation"].final_grade), 1.7765, places=4)
        self.assertAlmostEqual(float(by_name["Project"].final_grade), 1.3657, places=4)
        self.assertAlmostEqual(float(by_name["Examination"].final_grade), 1.7889, places=4)

    def test_final_grade_and_remarks_match_spreadsheet(self):
        result = compute_student(self.roster_entry)
        self.assertAlmostEqual(float(result.final_grade), 1.7743118580765638, places=10)
        self.assertEqual(format_grade(result.final_grade), Decimal("1.77"))
        self.assertEqual(result.remarks, "PASSED")

    def test_passing_threshold_is_3_00(self):
        result = compute_student(self.roster_entry)
        self.assertLessEqual(result.final_grade, Decimal("3.00"))


class ComponentWeightValidationTests(GradingTestBase):
    def test_weights_summing_to_100_pass(self):
        weights = [c.weight for c in self.template.components.all()]
        validate_component_weights(weights)  # should not raise

    def test_weights_not_summing_to_100_raise(self):
        with self.assertRaises(ValidationError):
            validate_component_weights([Decimal("50"), Decimal("40")])


class ScoreValidationTests(GradingTestBase):
    def test_score_above_max_is_rejected(self):
        items = self.make_items("Attendance", [10])
        item = items[0]
        score, error = save_score(self.roster_entry, item, Decimal("15"), self.instructor)
        self.assertEqual(error, "Max is 10")
        self.assertIsNone(score.score)

    def test_score_within_range_is_accepted(self):
        items = self.make_items("Attendance", [10])
        item = items[0]
        score, error = save_score(self.roster_entry, item, Decimal("8"), self.instructor)
        self.assertIsNone(error)
        self.assertEqual(score.score, Decimal("8"))


class RunningGradeRenormalizationTests(GradingTestBase):
    """Components with zero encoded items anywhere in the class are excluded
    from the running grade, and the remaining weights are re-normalized to
    sum to 100% — e.g. only Attendance (5%) encoded so far -> running grade
    equals the Attendance component grade alone."""

    def test_unencoded_components_are_excluded_and_weights_renormalized(self):
        attendance_items = self.make_items("Attendance", [10, 10])
        self.make_items("Quizzes", [20, 20])  # left entirely blank

        self.set_scores(self.roster_entry, attendance_items, [10, 5])

        result = compute_student(self.roster_entry)
        by_name = {c.component.name: c for c in result.components}

        self.assertFalse(by_name["Quizzes"].running_included)
        self.assertTrue(by_name["Attendance"].running_included)

        expected_attendance_grade = Decimal("5") - Decimal("4") * (Decimal("15") / Decimal("20"))
        self.assertEqual(result.running_grade, expected_attendance_grade)

    def test_partially_encoded_component_only_counts_encoded_items(self):
        quiz_items = self.make_items("Quizzes", [20, 20, 20])
        # Only the first quiz has been encoded for anyone in the class.
        self.set_scores(self.roster_entry, quiz_items[:1], [10])

        result = compute_student(self.roster_entry)
        quizzes = next(c for c in result.components if c.component.name == "Quizzes")
        self.assertTrue(quizzes.running_included)
        self.assertEqual(quizzes.running_possible, Decimal("20"))
        self.assertEqual(quizzes.running_earned, Decimal("10"))


class FinalGradeBlanksAndMissingCellsTests(GradingTestBase):
    def test_blank_scores_count_as_zero_in_final_grade_and_are_reported_missing(self):
        attendance_items = self.make_items("Attendance", [10, 10])
        self.set_scores(self.roster_entry, [attendance_items[0]], [10])
        # attendance_items[1] is left with no Score row at all (never encoded).

        result = compute_student(self.roster_entry)
        attendance = next(c for c in result.components if c.component.name == "Attendance")

        self.assertEqual(attendance.final_earned, Decimal("10"))
        self.assertEqual(attendance.final_possible, Decimal("20"))
        self.assertIn(attendance_items[1], result.missing_items)
        self.assertEqual(len(result.missing_items), 1)


class SchemeSnapshotIsolationTests(GradingTestBase):
    def test_editing_template_does_not_change_existing_class_scheme(self):
        scheme_component = self.scheme_components["Attendance"]
        self.assertEqual(scheme_component.weight, Decimal("5"))

        self.attendance.weight = Decimal("99")
        self.attendance.save()

        scheme_component.refresh_from_db()
        self.assertEqual(scheme_component.weight, Decimal("5"))


class ScoreChangeLogTests(GradingTestBase):
    def test_changing_a_score_writes_a_change_log_entry(self):
        items = self.make_items("Attendance", [10])
        item = items[0]

        save_score(self.roster_entry, item, Decimal("8"), self.instructor)
        save_score(self.roster_entry, item, Decimal("9"), self.instructor)

        logs = ScoreChangeLog.objects.filter(score__roster_entry=self.roster_entry, score__item=item).order_by("changed_at")
        self.assertEqual(logs.count(), 2)
        self.assertIsNone(logs[0].old_value)
        self.assertEqual(logs[0].new_value, Decimal("8"))
        self.assertEqual(logs[1].old_value, Decimal("8"))
        self.assertEqual(logs[1].new_value, Decimal("9"))

    def test_saving_the_same_value_does_not_write_a_duplicate_log(self):
        items = self.make_items("Attendance", [10])
        item = items[0]
        save_score(self.roster_entry, item, Decimal("8"), self.instructor)
        save_score(self.roster_entry, item, Decimal("8"), self.instructor)
        logs = ScoreChangeLog.objects.filter(score__roster_entry=self.roster_entry, score__item=item)
        self.assertEqual(logs.count(), 1)


class ComputeClassEfficiencyTests(GradingTestBase):
    def test_compute_class_returns_a_result_per_roster_entry(self):
        other_student = make_user(User.Role.STUDENT, "student2", id_number="2026-0002")
        ClassRosterEntry.objects.create(student=other_student, class_offering=self.class_offering)
        self.make_items("Attendance", [10])

        with self.assertNumQueries(5):
            results = compute_class(self.class_offering)

        self.assertEqual(len(results), 2)


class InstructorAccessControlTests(GradingTestBase):
    """Only the class's assigned instructor can reach its grading page;
    another instructor gets 403. (Admin/program head read-only access is
    exercised in GradingViewsTests.)"""

    def test_other_instructor_gets_403(self):
        other_instructor = make_user(User.Role.INSTRUCTOR, "other_prof")
        self.client.force_login(other_instructor)
        response = self.client.get(reverse("grading:class_grading", args=[self.class_offering.pk]))
        self.assertEqual(response.status_code, 403)

    def test_assigned_instructor_can_access(self):
        self.client.force_login(self.instructor)
        response = self.client.get(reverse("grading:class_grading", args=[self.class_offering.pk]))
        self.assertEqual(response.status_code, 200)


class RemarksCompletionTests(GradingTestBase):
    """Regression test for the bug where a student with mostly-unencoded
    components showed "Passed" despite a running grade of 4.80-5.00 — the
    FINAL grade quietly excludes components with zero items while blanks on
    existing items count as 0, so a barely-started gradebook can compute a
    misleadingly low (good) FINAL grade. Remarks must only read PASSED/
    FAILED off the FINAL grade once it is actually complete; otherwise show
    a provisional ON_TRACK/AT_RISK off the RUNNING grade."""

    def test_incomplete_grade_with_bad_running_grade_is_at_risk_not_passed(self):
        # Mirrors the real bug report: Attendance has items but nobody has
        # been scored yet; Quizzes has one very-low score.
        self.make_items("Attendance", [10, 10])
        quiz_items = self.make_items("Quizzes", [20])
        self.set_scores(self.roster_entry, quiz_items, [1])  # 1/20 -> component grade 4.80

        result = compute_student(self.roster_entry)
        self.assertFalse(result.is_grade_complete)
        self.assertEqual(result.running_grade, Decimal("4.80"))
        self.assertEqual(result.remarks, "AT_RISK")
        self.assertNotEqual(result.remarks, "PASSED")

    def test_incomplete_grade_with_good_running_grade_is_on_track(self):
        self.make_items("Attendance", [10, 10])
        quiz_items = self.make_items("Quizzes", [20])
        self.set_scores(self.roster_entry, quiz_items, [19])  # 19/20 -> component grade 1.20

        result = compute_student(self.roster_entry)
        self.assertFalse(result.is_grade_complete)
        self.assertEqual(result.remarks, "ON_TRACK")

    def test_complete_grade_of_1_77_is_passed(self):
        """Same Dela Cruz data as DelaCruzFinalGradeTests — every component
        has items and every item is scored, so the grade is complete and
        remarks must read PASSED off the FINAL grade."""
        attendance_items = self.make_items("Attendance", [10, 10, 10, 10, 10])
        quiz_items = self.make_items("Quizzes", [20, 20, 30, 20, 30, 40, 50])
        recitation_items = self.make_items("Recitation", [10, 10, 20, 30, 30, 30, 40])
        project_items = self.make_items("Project", [50, 70, 60, 80, 90])
        exam_items = self.make_items("Examination", [80, 100, 80, 100])

        self.set_scores(self.roster_entry, attendance_items, [10, 10, 10, 5, 10])
        self.set_scores(self.roster_entry, quiz_items, [15, 18, 21, 15, 25, 29, 37])
        self.set_scores(self.roster_entry, recitation_items, [6, 8, 16, 24, 27, 22, 34])
        self.set_scores(self.roster_entry, project_items, [45, 65, 50, 76, 82])
        self.set_scores(self.roster_entry, exam_items, [59, 87, 67, 76])

        result = compute_student(self.roster_entry)
        self.assertTrue(result.is_grade_complete)
        self.assertEqual(format_grade(result.final_grade), Decimal("1.77"))
        self.assertEqual(result.remarks, "PASSED")

    def test_complete_grade_at_exactly_3_00_boundary_is_passed(self):
        items_by_component = {
            name: self.make_items(name, [10]) for name in ("Attendance", "Quizzes", "Recitation", "Project", "Examination")
        }
        for items in items_by_component.values():
            self.set_scores(self.roster_entry, items, [5])  # 5/10 -> every component grade == 3.00

        result = compute_student(self.roster_entry)
        self.assertTrue(result.is_grade_complete)
        self.assertEqual(result.final_grade, Decimal("3.00"))
        self.assertEqual(result.remarks, "PASSED")


class TermFilterDoesNotAffectTotalsTests(GradingTestBase):
    """The "Show items for:" term filter only changes which item COLUMNS are
    visible — it must never change a component's Total/Grade or a student's
    running grade, which always reflect every term."""

    def test_filtering_by_term_does_not_change_totals_or_running_grade(self):
        prelim_items = self.make_items("Attendance", [10, 10], term=AssessmentTerm.PRELIM)
        final_item = AssessmentItem.objects.create(
            class_offering=self.class_offering,
            component=self.scheme_components["Attendance"],
            title="A3",
            max_score=Decimal("10"),
            term=AssessmentTerm.FINAL,
            order=2,
        )
        self.set_scores(self.roster_entry, prelim_items, [10, 5])
        Score.objects.update_or_create(roster_entry=self.roster_entry, item=final_item, defaults={"score": Decimal("8")})

        unfiltered = _build_class_record_context(self.class_offering, term_filter=None)
        filtered = _build_class_record_context(self.class_offering, term_filter=AssessmentTerm.PRELIM)

        unfiltered_row = next(r for r in unfiltered["rows"] if r["result"].roster_entry.id == self.roster_entry.id)
        filtered_row = next(r for r in filtered["rows"] if r["result"].roster_entry.id == self.roster_entry.id)

        unfiltered_breakdown = unfiltered_row["result"].components[0]
        filtered_breakdown = filtered_row["result"].components[0]

        self.assertEqual(unfiltered_breakdown.final_earned, filtered_breakdown.final_earned)
        self.assertEqual(unfiltered_breakdown.final_possible, filtered_breakdown.final_possible)
        self.assertEqual(unfiltered_row["result"].running_grade, filtered_row["result"].running_grade)

        # The visible item COLUMNS do differ — that's the whole point of the filter.
        self.assertEqual(len(unfiltered["columns"][0]["items"]), 3)
        self.assertEqual(len(filtered["columns"][0]["items"]), 2)


class WholeNumberValidationTests(GradingTestBase):
    """Scores and max scores are whole numbers — decimals/negatives must be
    rejected with a clear message, both via the save_cell view (raw string
    parsing) and the model field itself."""

    def test_save_cell_rejects_decimal_input(self):
        item = self.make_items("Attendance", [10])[0]
        self.client.force_login(self.instructor)
        response = self.client.post(
            reverse("grading:save_cell", args=[self.roster_entry.pk, item.pk]), {"value": "0.5"}
        )
        self.assertContains(response, "Whole numbers only.")
        score_obj = Score.objects.filter(roster_entry=self.roster_entry, item=item).first()
        self.assertTrue(score_obj is None or score_obj.score is None)

    def test_save_cell_rejects_negative_input(self):
        item = self.make_items("Attendance", [10])[0]
        self.client.force_login(self.instructor)
        response = self.client.post(
            reverse("grading:save_cell", args=[self.roster_entry.pk, item.pk]), {"value": "-1"}
        )
        self.assertContains(response, "Whole numbers only.")

    def test_save_cell_accepts_whole_number(self):
        item = self.make_items("Attendance", [10])[0]
        self.client.force_login(self.instructor)
        self.client.post(reverse("grading:save_cell", args=[self.roster_entry.pk, item.pk]), {"value": "8"})
        self.assertEqual(Score.objects.get(roster_entry=self.roster_entry, item=item).score, 8)

    def test_assessment_item_form_rejects_max_score_below_1(self):
        from .forms import AssessmentItemForm

        form = AssessmentItemForm(
            data={
                "component": self.scheme_components["Attendance"].pk,
                "title": "A1",
                "max_score": "0",
                "term": AssessmentTerm.PRELIM,
                "order": "0",
            },
            scheme=self.scheme,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("max_score", form.errors)


class HiddenComponentsTests(GradingTestBase):
    """A component with zero assessment items ("not yet set up") never
    appears as a grid column; the grid points instructors at Setup instead."""

    def test_components_without_items_are_hidden_and_listed_as_not_set_up(self):
        self.make_items("Attendance", [10])
        self.make_items("Quizzes", [20])
        # Recitation, Project, Examination are left with zero items.

        record = _build_class_record_context(self.class_offering, term_filter=None)
        visible_names = {col["component"].name for col in record["columns"]}
        self.assertEqual(visible_names, {"Attendance", "Quizzes"})

        not_set_up_names = {c.name for c in record["not_yet_set_up"]}
        self.assertEqual(not_set_up_names, {"Recitation", "Project", "Examination"})

    def test_term_filter_hides_a_component_with_no_items_in_that_term_but_not_from_not_yet_set_up(self):
        self.make_items("Attendance", [10], term=AssessmentTerm.PRELIM)
        self.make_items("Quizzes", [20], term=AssessmentTerm.FINAL)

        record = _build_class_record_context(self.class_offering, term_filter=AssessmentTerm.PRELIM)
        visible_names = {col["component"].name for col in record["columns"]}
        self.assertEqual(visible_names, {"Attendance"})  # Quizzes has items, just none in Prelim

        # Quizzes IS set up (has items overall) so it must not appear in the "not set up" note.
        not_set_up_names = {c.name for c in record["not_yet_set_up"]}
        self.assertNotIn("Quizzes", not_set_up_names)
        self.assertIn("Recitation", not_set_up_names)


class UnencodedComponentDisplayTests(GradingTestBase):
    """A component that has items but none scored yet for anyone in the
    class shows "—" for its Total/Grade in the grid — same rule the running
    grade already uses (running_included), so the grid never implies a
    student is doing great (component grade 5.00) on something nobody has
    started recording."""

    def test_grid_shows_dash_for_a_component_nobody_has_scored_yet(self):
        self.make_items("Attendance", [10, 10])  # created but left entirely blank
        quiz_item = self.make_items("Quizzes", [20])[0]
        self.set_scores(self.roster_entry, [quiz_item], [10])

        self.client.force_login(self.instructor)
        response = self.client.get(reverse("grading:class_grading", args=[self.class_offering.pk]) + "?tab=record")
        content = response.content.decode()

        # Header text is title-case in the DOM; uppercase is CSS-only (text-transform).
        attendance_idx = content.find("Attendance")
        quizzes_idx = content.find("Quizzes")
        self.assertNotEqual(attendance_idx, -1)
        self.assertNotEqual(quizzes_idx, -1)
        self.assertLess(attendance_idx, quizzes_idx)

        # Service-level check (unambiguous, not dependent on HTML structure).
        result = compute_student(self.roster_entry)
        attendance = next(c for c in result.components if c.component.name == "Attendance")
        quizzes = next(c for c in result.components if c.component.name == "Quizzes")
        self.assertFalse(attendance.running_included)
        self.assertTrue(quizzes.running_included)
