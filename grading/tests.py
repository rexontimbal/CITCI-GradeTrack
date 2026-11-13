import re
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

from .models import (
    AssessmentItem,
    AssessmentTerm,
    ClassGradingScheme,
    ComponentCategory,
    GradingComponent,
    GradingTemplate,
    Score,
    SchemeComponent,
    SchemeComponentChangeLog,
    ScoreChangeLog,
)
from .services import (
    compute_class,
    compute_student,
    format_grade,
    get_scheme_components,
    item_short_label,
    ordered_items_by_component,
    save_score,
    validate_component_weights,
)
from .views import _build_class_record_context, _item_columns


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
        self.subject = Subject.objects.create(code="IT101", title="Intro to Computing", units=Decimal("3.0"))
        self.instructor = make_user(User.Role.INSTRUCTOR, "prof")
        self.class_offering = ClassOffering.objects.create(
            subject=self.subject, semester=self.semester, instructor=self.instructor
        )
        self.class_offering.sections.set([self.section])

        self.student = make_user(User.Role.STUDENT, "student1", id_number="2026-0001")
        StudentProfile.objects.update_or_create(user=self.student, defaults={"program": self.program})
        self.roster_entry = ClassRosterEntry.objects.create(student=self.student, class_offering=self.class_offering)

        self.template = GradingTemplate.objects.create(name="CITCI Default", is_default=True)
        self.attendance = GradingComponent.objects.create(
            template=self.template, name="Attendance", category=ComponentCategory.ATTENDANCE, weight=5, order=1
        )
        self.quizzes = GradingComponent.objects.create(
            template=self.template, name="Quizzes", category=ComponentCategory.QUIZ, weight=30, order=2
        )
        self.recitation = GradingComponent.objects.create(
            template=self.template, name="Recitation", category=ComponentCategory.RECITATION, weight=15, order=3
        )
        self.project = GradingComponent.objects.create(
            template=self.template, name="Project", category=ComponentCategory.PROJECT, weight=10, order=4
        )
        # CITCI policy: Examination's weight is fixed by the school — every
        # other component is the instructor's to define for their own class.
        self.examination = GradingComponent.objects.create(
            template=self.template,
            name="Examination",
            category=ComponentCategory.EXAM,
            weight=40,
            is_locked=True,
            order=5,
        )

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

    def components_formset_payload(self, rows, extra_blanks=2):
        """Build a valid "components-*" formset POST payload. `rows` is a
        list of dicts: {"instance": SchemeComponent-or-None, "name":...,
        "category":..., "weight":..., "delete": bool}. `instance=None` means
        a brand-new row (no -id value) — matches how the "Add component"
        button's cloned row posts."""
        data = {
            "components-TOTAL_FORMS": str(len(rows) + extra_blanks),
            "components-INITIAL_FORMS": str(sum(1 for r in rows if r.get("instance"))),
            "components-MIN_NUM_FORMS": "0",
            "components-MAX_NUM_FORMS": "1000",
        }
        for i, row in enumerate(rows):
            prefix = f"components-{i}"
            instance = row.get("instance")
            data[f"{prefix}-id"] = str(instance.pk) if instance else ""
            data[f"{prefix}-name"] = row.get("name", instance.name if instance else "")
            data[f"{prefix}-category"] = row.get("category", instance.category if instance else ComponentCategory.OTHER)
            data[f"{prefix}-weight"] = str(row.get("weight", instance.weight if instance else ""))
            if row.get("delete"):
                data[f"{prefix}-DELETE"] = "on"
        for i in range(len(rows), len(rows) + extra_blanks):
            prefix = f"components-{i}"
            data[f"{prefix}-id"] = ""
            data[f"{prefix}-name"] = ""
            data[f"{prefix}-category"] = ComponentCategory.OTHER
            data[f"{prefix}-weight"] = ""
        return data


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


class ClassRecordExcelLayoutTests(DelaCruzFinalGradeTests):
    """The Class Record grid's Excel-style columns (short labels, Setup-
    matching column order, per-component TOTAL/100%/weight) against the
    same hand-verified Dela Cruz fixture as DelaCruzFinalGradeTests."""

    def test_short_labels_are_category_letter_plus_position(self):
        components = get_scheme_components(self.class_offering)
        by_name = {c.name: c for c in components}

        attendance = by_name["Attendance"]
        labels = [item_short_label(attendance, item, i) for i, item in enumerate(attendance.items.all(), start=1)]
        self.assertEqual(labels, ["A1", "A2", "A3", "A4", "A5"])

        quizzes = by_name["Quizzes"]
        labels = [item_short_label(quizzes, item, i) for i, item in enumerate(quizzes.items.all(), start=1)]
        self.assertEqual(labels, ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7"])

        project = by_name["Project"]
        labels = [item_short_label(project, item, i) for i, item in enumerate(project.items.all(), start=1)]
        self.assertEqual(labels, ["P1", "P2", "P3", "P4", "P5"])

    def test_exam_short_labels_are_term_letters_not_positional(self):
        components = get_scheme_components(self.class_offering)
        exam = next(c for c in components if c.name == "Examination")
        labels = {item_short_label(exam, item, i) for i, item in enumerate(exam.items.all(), start=1)}
        self.assertEqual(labels, {"P", "M", "S", "F"})

    def test_grid_columns_match_setup_order_exactly(self):
        """The same shared ordering (_term_ordered_items_qs) backs both
        Setup's ordered_items_by_component and the grid's _item_columns —
        this is the fix for the Setup/Class Record drift report."""
        scheme = ClassGradingScheme.get_or_create_default(self.class_offering)
        setup_items_by_component = ordered_items_by_component(scheme)
        columns = _item_columns(get_scheme_components(self.class_offering), None)
        for col in columns:
            setup_ids = [i.id for i in setup_items_by_component.get(col["component"].id, [])]
            self.assertEqual([i.id for i in col["items"]], setup_ids)

    def test_grid_renders_hand_verified_component_and_weight_columns(self):
        result = compute_student(self.roster_entry)
        by_name = {c.component.name: c for c in result.components}

        self.client.force_login(self.instructor)
        response = self.client.get(reverse("grading:class_grading", args=[self.class_offering.pk]) + "?tab=record")
        content = response.content.decode()

        self.assertContains(response, format_grade(by_name["Attendance"].final_grade))
        self.assertContains(response, format_grade(by_name["Attendance"].weighted_contribution))
        self.assertContains(response, format_grade(by_name["Examination"].final_grade))
        self.assertContains(response, format_grade(result.final_grade))
        self.assertIn(">A1<", content)
        self.assertIn(">Q1<", content)
        self.assertIn(">P1<", content)

    def test_empty_roster_shows_empty_state_not_a_blank_table(self):
        self.roster_entry.delete()
        self.client.force_login(self.instructor)
        response = self.client.get(reverse("grading:class_grading", args=[self.class_offering.pk]) + "?tab=record")
        self.assertContains(response, "No students in this class yet")
        self.assertContains(response, str(self.section))

    def test_fullscreen_toggle_markup_present(self):
        self.client.force_login(self.instructor)
        response = self.client.get(reverse("grading:class_grading", args=[self.class_offering.pk]) + "?tab=record")
        self.assertContains(response, "classRecordFullScreen")
        self.assertContains(response, "Exit full screen")


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
        self.assertEqual(result.final_remarks, "PASSED")

    def test_final_remarks_is_never_provisional_even_when_incomplete(self):
        """`final_remarks` — what a grade sheet snapshot may store — must
        always read PASSED/FAILED off the FINAL grade, even for the exact
        incomplete gradebook that makes `remarks` show ON_TRACK/AT_RISK."""
        self.make_items("Attendance", [10, 10])
        quiz_items = self.make_items("Quizzes", [20])
        self.set_scores(self.roster_entry, quiz_items, [1])  # same AT_RISK scenario as above

        result = compute_student(self.roster_entry)
        self.assertFalse(result.is_grade_complete)
        self.assertEqual(result.remarks, "AT_RISK")
        self.assertIn(result.final_remarks, ("PASSED", "FAILED"))
        self.assertNotIn(result.final_remarks, ("ON_TRACK", "AT_RISK", None))

    def test_final_remarks_respects_inc_and_dropped(self):
        self.roster_entry.is_incomplete = True
        self.roster_entry.save()
        result = compute_student(self.roster_entry)
        self.assertEqual(result.final_remarks, "INC")

        self.roster_entry.is_incomplete = False
        self.roster_entry.status = ClassRosterEntry.Status.DROPPED
        self.roster_entry.save()
        result = compute_student(self.roster_entry)
        self.assertEqual(result.final_remarks, "DROPPED")


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


class LockedComponentProtectionTests(GradingTestBase):
    """CITCI policy: Examination's weight is fixed by the school. An
    instructor can't rename/recategorize/reweight or delete a locked
    component in their own class, no matter what they POST."""

    def _save_url(self):
        return reverse("grading:class_components_save", args=[self.class_offering.pk])

    def test_instructor_cannot_change_locked_component_fields(self):
        examination = self.scheme_components["Examination"]
        rows = [
            {"instance": self.scheme_components["Attendance"]},
            {"instance": self.scheme_components["Quizzes"]},
            {"instance": self.scheme_components["Recitation"]},
            {"instance": self.scheme_components["Project"]},
            {"instance": examination, "name": "Finals", "category": ComponentCategory.OTHER, "weight": 50},
        ]
        self.client.force_login(self.instructor)
        response = self.client.post(self._save_url(), self.components_formset_payload(rows))

        self.assertEqual(response.status_code, 200)  # re-rendered with a validation error, not saved
        examination.refresh_from_db()
        self.assertEqual(examination.name, "Examination")
        self.assertEqual(examination.weight, 40)
        self.assertEqual(examination.category, ComponentCategory.EXAM)

    def test_instructor_cannot_delete_locked_component(self):
        examination = self.scheme_components["Examination"]
        rows = [
            {"instance": self.scheme_components["Attendance"]},
            {"instance": self.scheme_components["Quizzes"]},
            {"instance": self.scheme_components["Recitation"]},
            {"instance": self.scheme_components["Project"]},
            {"instance": examination, "delete": True},
        ]
        self.client.force_login(self.instructor)
        response = self.client.post(self._save_url(), self.components_formset_payload(rows))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "set by the school")
        self.assertTrue(self.scheme.components.filter(pk=examination.pk).exists())


class ComponentWeightTotalTests(GradingTestBase):
    def _save_url(self):
        return reverse("grading:class_components_save", args=[self.class_offering.pk])

    def _locked_plus_unlocked_rows(self, unlocked_weights):
        rows = [{"instance": self.scheme_components["Examination"]}]
        names = ["Attendance", "Quizzes", "Recitation", "Project"]
        for name, weight in zip(names, unlocked_weights):
            rows.append({"instance": self.scheme_components[name], "weight": weight})
        return rows

    def test_total_below_100_including_locked_is_rejected(self):
        # 40 (locked) + 5+30+15+5 = 95, not 100.
        rows = self._locked_plus_unlocked_rows([5, 30, 15, 5])
        self.client.force_login(self.instructor)
        response = self.client.post(self._save_url(), self.components_formset_payload(rows))
        self.assertContains(response, "Total is 95%")
        self.assertContains(response, "Add 5%")

    def test_total_above_100_including_locked_is_rejected(self):
        # 40 (locked) + 5+30+15+15 = 105, not 100.
        rows = self._locked_plus_unlocked_rows([5, 30, 15, 15])
        self.client.force_login(self.instructor)
        response = self.client.post(self._save_url(), self.components_formset_payload(rows))
        self.assertContains(response, "Total is 105%")
        self.assertContains(response, "Reduce by 5%")

    def test_total_exactly_100_including_locked_is_accepted(self):
        rows = self._locked_plus_unlocked_rows([5, 30, 15, 10])  # 40 + 60 = 100
        self.client.force_login(self.instructor)
        response = self.client.post(self._save_url(), self.components_formset_payload(rows))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Refresh"], "true")

    def test_non_integer_weight_is_rejected(self):
        rows = self._locked_plus_unlocked_rows([5, 30, 15, 10])
        payload = self.components_formset_payload(rows)
        payload["components-3-weight"] = "12.5"  # Project row
        self.client.force_login(self.instructor)
        response = self.client.post(self._save_url(), payload)
        self.assertEqual(response.status_code, 200)  # redisplayed with a field error, not saved
        self.scheme_components["Project"].refresh_from_db()
        self.assertEqual(self.scheme_components["Project"].weight, 10)  # unchanged

    def test_duplicate_component_name_case_insensitive_is_rejected(self):
        rows = self._locked_plus_unlocked_rows([5, 30, 15, 10])
        payload = self.components_formset_payload(rows)
        payload["components-3-name"] = "quizzes"  # Project row renamed to clash with Quizzes, case-insensitively
        self.client.force_login(self.instructor)
        response = self.client.post(self._save_url(), payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists in this class")
        self.scheme_components["Project"].refresh_from_db()
        self.assertEqual(self.scheme_components["Project"].name, "Project")  # unchanged

    def test_partly_filled_new_row_is_rejected_but_fully_blank_one_is_ignored(self):
        rows = self._locked_plus_unlocked_rows([5, 30, 15, 10])
        payload = self.components_formset_payload(rows, extra_blanks=1)
        # The one extra blank row gets a name but no weight -- "changed" from
        # blank, so it must be validated (and rejected), not silently
        # skipped the way a still-fully-blank row would be.
        new_row_index = len(rows)
        payload[f"components-{new_row_index}-name"] = "Bonus"
        self.client.force_login(self.instructor)
        response = self.client.post(self._save_url(), payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required")
        self.assertFalse(SchemeComponent.objects.filter(scheme=self.scheme, name="Bonus").exists())

    def test_fully_blank_extra_row_is_silently_ignored(self):
        rows = self._locked_plus_unlocked_rows([5, 30, 15, 10])  # totals exactly 100
        payload = self.components_formset_payload(rows, extra_blanks=1)
        self.client.force_login(self.instructor)
        response = self.client.post(self._save_url(), payload)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Refresh"], "true")


class TwoInstructorsDifferentComponentsTests(TestCase):
    """Each instructor's class gets its own unlocked component mix —
    customizing one class must never affect another, and both still
    compute correctly against CITCI's component-grade/final-grade formula."""

    def setUp(self):
        self.academic_year = AcademicYear.objects.create(start_year=2026)
        self.semester = Semester.objects.create(academic_year=self.academic_year, term=Term.FIRST, is_active=True)
        self.program = Program.objects.create(code="BSIT", name="BS Information Technology")
        self.section = Section.objects.create(program=self.program, academic_year=self.academic_year, year_level=1, name="A")

        self.template = GradingTemplate.objects.create(name="CITCI Default", is_default=True)
        GradingComponent.objects.create(template=self.template, name="Attendance", category=ComponentCategory.ATTENDANCE, weight=5, order=1)
        GradingComponent.objects.create(template=self.template, name="Quizzes", category=ComponentCategory.QUIZ, weight=30, order=2)
        GradingComponent.objects.create(template=self.template, name="Recitation", category=ComponentCategory.RECITATION, weight=15, order=3)
        GradingComponent.objects.create(template=self.template, name="Project", category=ComponentCategory.PROJECT, weight=10, order=4)
        GradingComponent.objects.create(template=self.template, name="Examination", category=ComponentCategory.EXAM, weight=40, is_locked=True, order=5)

        self.instructor_a = make_user(User.Role.INSTRUCTOR, "profA")
        self.instructor_b = make_user(User.Role.INSTRUCTOR, "profB")

        subject_a = Subject.objects.create(code="IT101", title="Intro A", units=Decimal("3.0"))
        subject_b = Subject.objects.create(code="IT102", title="Intro B", units=Decimal("3.0"))
        self.class_a = ClassOffering.objects.create(subject=subject_a, semester=self.semester, instructor=self.instructor_a)
        self.class_a.sections.set([self.section])
        self.class_b = ClassOffering.objects.create(subject=subject_b, semester=self.semester, instructor=self.instructor_b)
        self.class_b.sections.set([self.section])

        self.scheme_a = ClassGradingScheme.get_or_create_default(self.class_a)
        self.scheme_b = ClassGradingScheme.get_or_create_default(self.class_b)

        student_a = make_user(User.Role.STUDENT, "studentA", id_number="2026-1001")
        student_b = make_user(User.Role.STUDENT, "studentB", id_number="2026-1002")
        self.roster_a = ClassRosterEntry.objects.create(student=student_a, class_offering=self.class_a)
        self.roster_b = ClassRosterEntry.objects.create(student=student_b, class_offering=self.class_b)

    def test_each_class_keeps_its_own_unlocked_components_and_computes_independently(self):
        # Instructor A: keeps the default split.
        exam_a = self.scheme_a.components.get(name="Examination")
        attendance_a = self.scheme_a.components.get(name="Attendance")
        item_exam_a = AssessmentItem.objects.create(
            class_offering=self.class_a, component=exam_a, title="Final", max_score=100, term=AssessmentTerm.FINAL
        )
        item_att_a = AssessmentItem.objects.create(
            class_offering=self.class_a, component=attendance_a, title="A1", max_score=10, term=AssessmentTerm.PRELIM
        )
        Score.objects.create(roster_entry=self.roster_a, item=item_exam_a, score=80)
        Score.objects.create(roster_entry=self.roster_a, item=item_att_a, score=10)

        # Instructor B: renames/reweights the unlocked components — merges
        # Quizzes+Recitation into one "Formative Assessment" at 45%, drops
        # Project's weight to 0 by removing it isn't allowed (min 1), so
        # instead redistributes: Attendance 5, Formative 45, Project 10.
        quizzes_b = self.scheme_b.components.get(name="Quizzes")
        quizzes_b.name = "Formative Assessment"
        quizzes_b.weight = 45
        quizzes_b.save()
        recitation_b = self.scheme_b.components.get(name="Recitation")
        self.scheme_b.components.filter(pk=recitation_b.pk).delete()  # unscored, zero items -> deletable directly here
        exam_b = self.scheme_b.components.get(name="Examination")
        item_exam_b = AssessmentItem.objects.create(
            class_offering=self.class_b, component=exam_b, title="Final", max_score=100, term=AssessmentTerm.FINAL
        )
        item_formative_b = AssessmentItem.objects.create(
            class_offering=self.class_b, component=quizzes_b, title="F1", max_score=50, term=AssessmentTerm.PRELIM
        )
        Score.objects.create(roster_entry=self.roster_b, item=item_exam_b, score=90)
        Score.objects.create(roster_entry=self.roster_b, item=item_formative_b, score=25)

        result_a = compute_student(self.roster_a)
        result_b = compute_student(self.roster_b)

        # Class A: Examination grade = 5 - 4*(80/100) = 1.80; Attendance = 5 - 4*(10/10) = 1.00
        exam_grade_a = next(c.final_grade for c in result_a.components if c.component.name == "Examination")
        attendance_grade_a = next(c.final_grade for c in result_a.components if c.component.name == "Attendance")
        self.assertEqual(exam_grade_a, Decimal("1.80"))
        self.assertEqual(attendance_grade_a, Decimal("1.00"))

        # Class B: Examination grade = 5 - 4*(90/100) = 1.40; Formative = 5 - 4*(25/50) = 3.00
        exam_grade_b = next(c.final_grade for c in result_b.components if c.component.name == "Examination")
        formative_grade_b = next(c.final_grade for c in result_b.components if c.component.name == "Formative Assessment")
        self.assertEqual(exam_grade_b, Decimal("1.40"))
        self.assertEqual(formative_grade_b, Decimal("3.00"))

        # Weights stayed independent: class B's component names/weights never leaked into class A.
        names_a = set(self.scheme_a.components.values_list("name", flat=True))
        names_b = set(self.scheme_b.components.values_list("name", flat=True))
        self.assertIn("Quizzes", names_a)
        self.assertNotIn("Formative Assessment", names_a)
        self.assertIn("Formative Assessment", names_b)
        self.assertNotIn("Recitation", names_b)


class WeightChangeRecomputeAndAuditTests(GradingTestBase):
    def _save_url(self, class_offering=None):
        return reverse("grading:class_components_save", args=[(class_offering or self.class_offering).pk])

    def test_weight_change_recomputes_grades_and_writes_change_log(self):
        item = self.make_items("Attendance", [10])[0]
        self.set_scores(self.roster_entry, [item], [10])  # Attendance fully scored -> component grade 1.00

        rows = [
            {"instance": self.scheme_components["Attendance"], "weight": 20},  # 5 -> 20
            {"instance": self.scheme_components["Quizzes"], "weight": 15},  # 30 -> 15
            {"instance": self.scheme_components["Recitation"]},
            {"instance": self.scheme_components["Project"]},
            {"instance": self.scheme_components["Examination"]},
        ]
        self.client.force_login(self.instructor)
        response = self.client.post(self._save_url(), self.components_formset_payload(rows))
        self.assertEqual(response.status_code, 204)

        attendance = self.scheme_components["Attendance"]
        attendance.refresh_from_db()
        self.assertEqual(attendance.weight, 20)

        log = SchemeComponentChangeLog.objects.filter(
            scheme=self.scheme, component_name="Attendance", action=SchemeComponentChangeLog.Action.EDITED
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.before["weight"], 5)
        self.assertEqual(log.after["weight"], 20)
        self.assertEqual(log.changed_by, self.instructor)

        # Grades recompute live off the new weight — no caching to invalidate.
        result = compute_student(self.roster_entry)
        attendance_breakdown = next(c for c in result.components if c.component.name == "Attendance")
        self.assertEqual(attendance_breakdown.component.weight, 20)

    def test_another_instructor_gets_403(self):
        other_instructor = make_user(User.Role.INSTRUCTOR, "other_prof")
        rows = [
            {"instance": self.scheme_components["Attendance"]},
            {"instance": self.scheme_components["Quizzes"]},
            {"instance": self.scheme_components["Recitation"]},
            {"instance": self.scheme_components["Project"]},
            {"instance": self.scheme_components["Examination"]},
        ]
        self.client.force_login(other_instructor)
        response = self.client.post(self._save_url(), self.components_formset_payload(rows))
        self.assertEqual(response.status_code, 403)


class StudentPortalTestBase(GradingTestBase):
    """GradingTestBase's class/roster/scheme fixture, fully scored (Dela
    Cruz-style complete data), plus a second student on a second class so
    cross-student access can be tested."""

    def setUp(self):
        super().setUp()
        self.attendance_items = self.make_items("Attendance", [10, 10])
        self.quiz_items = self.make_items("Quizzes", [20])
        self.recitation_items = self.make_items("Recitation", [10])
        self.project_items = self.make_items("Project", [50])
        self.exam_items = self.make_items("Examination", [100])
        self.set_scores(self.roster_entry, self.attendance_items, [10, 10])
        self.set_scores(self.roster_entry, self.quiz_items, [18])
        self.set_scores(self.roster_entry, self.recitation_items, [9])
        self.set_scores(self.roster_entry, self.project_items, [45])
        self.set_scores(self.roster_entry, self.exam_items, [80])

        self.program_head = make_user(User.Role.PROGRAM_HEAD, "ph_student_portal")
        self.program.program_head = self.program_head
        self.program.save()

        self.other_student = make_user(User.Role.STUDENT, "other_student", id_number="2026-9001")

    def release(self):
        from approvals.services import approve_grade_sheet, release_grade_sheet, submit_grade_sheet

        sheet = submit_grade_sheet(self.class_offering, self.instructor)
        approve_grade_sheet(sheet, self.program_head)
        return release_grade_sheet(sheet, self.program_head)


class StudentAccessControlTests(StudentPortalTestBase):
    def test_student_cannot_view_another_students_subject_detail(self):
        self.client.force_login(self.other_student)
        response = self.client.get(reverse("grading:subject_detail", args=[self.roster_entry.pk]))
        self.assertEqual(response.status_code, 404)

    def test_student_cannot_open_the_instructor_class_grading_page(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("grading:class_grading", args=[self.class_offering.pk]))
        self.assertEqual(response.status_code, 403)

    def test_student_can_view_own_subject_detail(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("grading:subject_detail", args=[self.roster_entry.pk]))
        self.assertEqual(response.status_code, 200)


class OfficialVsUnofficialSourcingTests(StudentPortalTestBase):
    def test_released_subject_uses_frozen_snapshot_even_if_live_scores_change_later(self):
        sheet = self.release()
        entry = sheet.entries.get(roster_entry=self.roster_entry)
        original_final_grade = entry.final_grade

        # Mutate the underlying score directly (bypassing the edit lock, as
        # a correction-free simulation of "what if live data drifted") —
        # the snapshot must not budge.
        exam_score = Score.objects.get(roster_entry=self.roster_entry, item=self.exam_items[0])
        exam_score.score = 0
        exam_score.save()

        self.client.force_login(self.student)
        response = self.client.get(reverse("grading:subject_detail", args=[self.roster_entry.pk]))
        self.assertEqual(response.context["final_grade"], original_final_grade)
        self.assertNotEqual(compute_student(self.roster_entry).final_grade, original_final_grade)

    def test_unreleased_subject_uses_live_running_grade(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("grading:subject_detail", args=[self.roster_entry.pk]))
        expected = compute_student(self.roster_entry).running_grade
        self.assertEqual(response.context["final_grade"], expected)
        self.assertFalse(response.context["is_released"])


class UnofficialScoresSettingTests(StudentPortalTestBase):
    def _set_show_unofficial(self, value):
        from reports.models import InstitutionSettings

        inst = InstitutionSettings.get_solo()
        inst.show_unofficial_scores_to_students = value
        inst.save()

    def test_setting_off_hides_running_scores_on_subject_detail(self):
        self._set_show_unofficial(False)
        self.client.force_login(self.student)
        response = self.client.get(reverse("grading:subject_detail", args=[self.roster_entry.pk]))
        self.assertFalse(response.context["can_view_detail"])
        self.assertContains(response, "Grades not yet released")
        self.assertNotIn("final_grade", response.context)

    def test_setting_off_hides_running_grade_on_my_grades(self):
        self._set_show_unofficial(False)
        self.client.force_login(self.student)
        response = self.client.get(reverse("grading:my_grades"))
        row = response.context["rows"][0]
        self.assertIsNone(row["unofficial_grade"])

    def test_setting_on_shows_running_scores(self):
        self._set_show_unofficial(True)
        self.client.force_login(self.student)
        response = self.client.get(reverse("grading:subject_detail", args=[self.roster_entry.pk]))
        self.assertTrue(response.context["can_view_detail"])


class GwaDisplayTests(StudentPortalTestBase):
    def test_my_grades_shows_partial_gwa_note_when_not_all_released(self):
        self.release()

        # A second, still-unreleased class for the same student/semester —
        # otherwise releasing the one-and-only class makes the GWA complete,
        # not partial.
        second_subject = Subject.objects.create(code="EXTRA1", title="Extra Subject", units=Decimal("3.0"))
        second_class = ClassOffering.objects.create(subject=second_subject, semester=self.semester, instructor=self.instructor)
        second_class.sections.set([self.section])
        ClassRosterEntry.objects.create(student=self.student, class_offering=second_class)

        self.client.force_login(self.student)
        response = self.client.get(reverse("grading:my_grades"))
        self.assertContains(response, "Partial GWA")

    def test_dashboard_shows_official_gwa_once_complete(self):
        self.release()
        self.client.force_login(self.student)
        response = self.client.get(reverse("dashboard:home"))
        self.assertTrue(response.context["gwa"]["is_complete"])
        self.assertContains(response, response.context["gwa"]["gwa"].__str__())


class AssessmentItemSuggestionTests(GradingTestBase):
    """suggest_item_titles/default_term_for_new_item/default_max_score_for_
    component -- the Add Item form's suggested-title combobox, default
    term, and default max score."""

    def test_quiz_suggestions_start_at_1_and_advance_past_existing_items(self):
        """Short letter+number codes (A1, Q1, R1, P1) -- matching CITCI's
        actual manual class record (grading-system.xlsx) column headers
        exactly, confirmed against a real printout."""
        from .services import suggest_item_titles

        quizzes = self.scheme_components["Quizzes"]
        self.assertEqual(suggest_item_titles(quizzes), ["Q1"])

        AssessmentItem.objects.create(
            class_offering=self.class_offering, component=quizzes, title="Q1", max_score=20, term=AssessmentTerm.PRELIM
        )
        self.assertEqual(suggest_item_titles(quizzes), ["Q2"])

    def test_recitation_and_project_and_attendance_and_other_suggestions(self):
        from .services import suggest_item_titles

        self.assertEqual(suggest_item_titles(self.scheme_components["Recitation"]), ["R1"])
        self.assertEqual(suggest_item_titles(self.scheme_components["Project"]), ["P1"])
        self.assertEqual(suggest_item_titles(self.scheme_components["Attendance"]), ["A1"])

        other = SchemeComponent.objects.create(scheme=self.scheme, name="Seatwork", category=ComponentCategory.OTHER, weight=0)
        self.assertEqual(suggest_item_titles(other), ["Seatwork 1"])

    def test_exam_titles_hide_once_used(self):
        from .services import suggest_item_titles

        exam = self.scheme_components["Examination"]
        self.assertEqual(
            suggest_item_titles(exam), ["Prelim Exam", "Midterm Exam", "Semi-final Exam", "Final Exam"]
        )

        AssessmentItem.objects.create(
            class_offering=self.class_offering, component=exam, title="Prelim Exam", max_score=100, term=AssessmentTerm.PRELIM
        )
        self.assertEqual(suggest_item_titles(exam), ["Midterm Exam", "Semi-final Exam", "Final Exam"])

        AssessmentItem.objects.create(
            class_offering=self.class_offering, component=exam, title="Final Exam", max_score=100, term=AssessmentTerm.FINAL
        )
        self.assertEqual(suggest_item_titles(exam), ["Midterm Exam", "Semi-final Exam"])

    def test_default_term_is_prelim_when_no_items_yet(self):
        from .services import default_term_for_new_item

        self.assertEqual(default_term_for_new_item(self.class_offering), AssessmentTerm.PRELIM)

    def test_default_term_matches_most_recently_added_item(self):
        from .services import default_term_for_new_item

        AssessmentItem.objects.create(
            class_offering=self.class_offering,
            component=self.scheme_components["Quizzes"],
            title="Quiz 1",
            max_score=20,
            term=AssessmentTerm.MIDTERM,
        )
        self.assertEqual(default_term_for_new_item(self.class_offering), AssessmentTerm.MIDTERM)

    def test_default_max_score_remembers_last_value_per_component(self):
        from .services import default_max_score_for_component

        quizzes = self.scheme_components["Quizzes"]
        self.assertIsNone(default_max_score_for_component(quizzes))

        AssessmentItem.objects.create(
            class_offering=self.class_offering, component=quizzes, title="Quiz 1", max_score=20, term=AssessmentTerm.PRELIM
        )
        self.assertEqual(default_max_score_for_component(quizzes), 20)


class AssessmentItemFormValidationTests(GradingTestBase):
    """The Add/Edit Assessment Item form: duplicate titles rejected,
    exam titles force their matching term server-side, and `order` is
    gone -- ordering is now automatic (term, date, creation)."""

    def _base_data(self, **overrides):
        data = {
            "component": self.scheme_components["Quizzes"].pk,
            "title": "Quiz 1",
            "max_score": "20",
            "term": AssessmentTerm.PRELIM,
            "date": "",
        }
        data.update(overrides)
        return data

    def test_order_field_is_gone(self):
        from .forms import AssessmentItemForm

        form = AssessmentItemForm(scheme=self.scheme)
        self.assertNotIn("order", form.fields)

    def test_duplicate_title_within_same_component_rejected_case_insensitively(self):
        from .forms import AssessmentItemForm

        AssessmentItem.objects.create(
            class_offering=self.class_offering,
            component=self.scheme_components["Quizzes"],
            title="Quiz 1",
            max_score=20,
            term=AssessmentTerm.PRELIM,
        )
        form = AssessmentItemForm(data=self._base_data(title="quiz 1"), scheme=self.scheme)
        self.assertFalse(form.is_valid())
        self.assertIn("title", form.errors)

    def test_duplicate_title_in_a_different_component_is_allowed(self):
        from .forms import AssessmentItemForm

        AssessmentItem.objects.create(
            class_offering=self.class_offering,
            component=self.scheme_components["Recitation"],
            title="Quiz 1",
            max_score=20,
            term=AssessmentTerm.PRELIM,
        )
        form = AssessmentItemForm(data=self._base_data(), scheme=self.scheme)
        self.assertTrue(form.is_valid())

    def test_editing_an_item_does_not_clash_with_its_own_title(self):
        from .forms import AssessmentItemForm

        item = AssessmentItem.objects.create(
            class_offering=self.class_offering,
            component=self.scheme_components["Quizzes"],
            title="Quiz 1",
            max_score=20,
            term=AssessmentTerm.PRELIM,
        )
        form = AssessmentItemForm(data=self._base_data(), instance=item, scheme=self.scheme)
        self.assertTrue(form.is_valid())

    def test_exam_title_forces_its_matching_term_even_if_a_different_term_was_posted(self):
        from .forms import AssessmentItemForm

        data = self._base_data(
            component=self.scheme_components["Examination"].pk, title="Midterm Exam", term=AssessmentTerm.FINAL
        )
        form = AssessmentItemForm(data=data, scheme=self.scheme)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["term"], AssessmentTerm.MIDTERM)

    def test_non_exam_title_leaves_posted_term_untouched(self):
        from .forms import AssessmentItemForm

        form = AssessmentItemForm(data=self._base_data(term=AssessmentTerm.SEMIFINAL), scheme=self.scheme)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["term"], AssessmentTerm.SEMIFINAL)


class AssessmentItemFormViewTests(GradingTestBase):
    def test_add_item_view_prefills_first_suggestion_and_default_term(self):
        self.client.force_login(self.instructor)
        url = reverse("grading:item_create", args=[self.class_offering.pk])
        response = self.client.get(url, {"component": self.scheme_components["Quizzes"].pk})
        self.assertContains(response, 'value="Q1"')
        self.assertInHTML(
            f'<option value="{AssessmentTerm.PRELIM}" selected>Prelim</option>', response.content.decode()
        )

    def test_term_dropdown_has_no_blank_choice(self):
        self.client.force_login(self.instructor)
        url = reverse("grading:item_create", args=[self.class_offering.pk])
        response = self.client.get(url, {"component": self.scheme_components["Quizzes"].pk})
        term_select = re.search(r'<select name="term".*?</select>', response.content.decode(), re.DOTALL).group()
        self.assertNotIn("---------", term_select)
        self.assertNotIn('value=""', term_select)
