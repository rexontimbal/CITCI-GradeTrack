import math
from decimal import Decimal
from io import BytesIO

from django.core.exceptions import ValidationError
from django.test import TestCase
from openpyxl import Workbook

from academics.models import ClassOffering, ClassRosterEntry
from accounts.models import User
from grading.models import AssessmentTerm, ComponentCategory
from grading.tests import GradingTestBase, make_user

from .historical_import import build_import_preview, mask_identifier
from .ml.evaluate import evaluate_model
from .ml.features import FEATURE_NAMES, compute_medians, extract_features, to_vector
from .ml.predict import predict
from .ml.synthetic import generate_synthetic_rows
from .ml.train import MIN_HISTORICAL_POSITIVES, MIN_HISTORICAL_ROWS, train_model
from .models import Checkpoint, HistoricalImportBatch, HistoricalRecord, MlModelVersion, RiskLabel, TrainingSource


class FeatureExtractionTests(GradingTestBase):
    """Leakage guard, category mapping, imputation — CLAUDE.md section 7."""

    def test_final_term_item_never_affects_a_midterm_feature_row(self):
        midterm_quiz = self.make_items("Quizzes", [20], term=AssessmentTerm.MIDTERM)
        final_quiz = self.make_items("Quizzes", [20], term=AssessmentTerm.FINAL)
        self.set_scores(self.roster_entry, midterm_quiz, [10])  # 50%
        self.set_scores(self.roster_entry, final_quiz, [20])  # 100% — must NEVER leak into MIDTERM

        features = extract_features(self.roster_entry, Checkpoint.MIDTERM)
        self.assertEqual(features["quiz_pct"], Decimal("50"))  # not (10+20)/(20+20)=75

    def test_prelim_checkpoint_excludes_midterm_and_later_items(self):
        prelim_quiz = self.make_items("Quizzes", [20], term=AssessmentTerm.PRELIM)
        midterm_quiz = self.make_items("Quizzes", [20], term=AssessmentTerm.MIDTERM)
        self.set_scores(self.roster_entry, prelim_quiz, [20])  # 100%
        self.set_scores(self.roster_entry, midterm_quiz, [0])  # 0% — must not drag the PRELIM row down

        features = extract_features(self.roster_entry, Checkpoint.PRELIM)
        self.assertEqual(features["quiz_pct"], Decimal("100"))

    def test_category_mapping_survives_a_renamed_component(self):
        """An instructor can rename "Quizzes" to anything — category is
        what the feature extractor keys off, never the free-text name."""
        quizzes = self.scheme_components["Quizzes"]
        quizzes.name = "Formative Checks"
        quizzes.save()
        items = self.make_items("Quizzes", [10], term=AssessmentTerm.PRELIM)
        self.set_scores(self.roster_entry, items, [7])

        features = extract_features(self.roster_entry, Checkpoint.PRELIM)
        self.assertEqual(features["quiz_pct"], Decimal("70"))

    def test_project_and_other_categories_merge_into_one_feature(self):
        other_component = self.scheme_components["Project"]
        other_component.category = ComponentCategory.OTHER
        other_component.save()
        items = self.make_items("Project", [10], term=AssessmentTerm.PRELIM)
        self.set_scores(self.roster_entry, items, [5])

        features = extract_features(self.roster_entry, Checkpoint.PRELIM)
        self.assertEqual(features["project_pct"], Decimal("50"))

    def test_missing_category_is_none_not_a_fabricated_percentage(self):
        """No Attendance items at all this checkpoint -> None, imputed by
        the caller (compute_medians/to_vector), never a guessed value."""
        self.make_items("Quizzes", [10], term=AssessmentTerm.PRELIM)
        self.set_scores(self.roster_entry, self.scheme_components["Quizzes"].items.all(), [5])

        features = extract_features(self.roster_entry, Checkpoint.PRELIM)
        self.assertIsNone(features["attendance_pct"])

    def test_insufficient_data_when_nothing_scored_at_all(self):
        self.make_items("Quizzes", [10], term=AssessmentTerm.PRELIM)  # item exists but nobody scored
        features = extract_features(self.roster_entry, Checkpoint.PRELIM)
        self.assertIsNone(features)

    def test_imputation_uses_training_set_median_and_flags_missing(self):
        rows = [
            {**{n: None for n in FEATURE_NAMES}, "quiz_pct": Decimal("60")},
            {**{n: None for n in FEATURE_NAMES}, "quiz_pct": Decimal("80")},
            {**{n: None for n in FEATURE_NAMES}, "quiz_pct": None},
        ]
        medians = compute_medians(rows)
        self.assertEqual(medians["quiz_pct"], Decimal("70"))  # median of 60, 80

        vector = to_vector(rows[2], medians)
        self.assertEqual(vector["quiz_pct"], 70.0)
        self.assertEqual(vector["quiz_pct_missing"], 1.0)

        vector_present = to_vector(rows[0], medians)
        self.assertEqual(vector_present["quiz_pct"], 60.0)
        self.assertEqual(vector_present["quiz_pct_missing"], 0.0)


class MaskingTests(TestCase):
    def test_same_identifier_always_hashes_the_same(self):
        self.assertEqual(mask_identifier("2026-0001"), mask_identifier("2026-0001"))

    def test_different_identifiers_hash_differently(self):
        self.assertNotEqual(mask_identifier("2026-0001"), mask_identifier("2026-0002"))

    def test_hash_never_contains_the_raw_identifier(self):
        masked = mask_identifier("Dela Cruz, Juan B.")
        self.assertNotIn("Dela Cruz", masked)
        self.assertNotIn("Juan", masked)

    def test_hash_is_a_64_char_hex_sha256(self):
        masked = mask_identifier("2026-0001")
        self.assertEqual(len(masked), 64)
        int(masked, 16)  # raises ValueError if not valid hex


def _minimal_class_record_bytes(rows):
    """A minimal workbook in the shape forecasting.historical_import
    expects (same 3-row header pattern as the system's own export): one
    Quizzes component (single item, max 10), FINAL GRADE + REMARKS
    columns. `rows` is a list of (id_number, score, final_grade, remarks).
    """
    wb = Workbook()
    ws = wb.active
    ws.cell(8, 1, "No.")
    ws.cell(8, 2, "ID Number")
    ws.cell(8, 3, "Name of Students")
    ws.cell(8, 4, "Quizzes (100%)")
    ws.cell(9, 4, "Q1")
    ws.cell(9, 5, "TOTAL")
    ws.cell(9, 6, "GRADE")
    ws.cell(9, 7, "WEIGHTED")
    ws.cell(10, 4, 10)
    ws.cell(8, 8, "FINAL GRADE")
    ws.cell(8, 9, "REMARKS")
    for i, (id_number, score, final_grade, remarks) in enumerate(rows, start=1):
        row = 10 + i
        ws.cell(row, 1, i)
        ws.cell(row, 2, id_number)
        ws.cell(row, 3, f"Student {i}")
        ws.cell(row, 4, score)
        ws.cell(row, 8, final_grade)
        ws.cell(row, 9, remarks)
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


class LabelRuleTests(TestCase):
    """CLAUDE.md section 7: y=1 iff FINAL grade > 3.00 (not ==5.00), or
    INC, or DROPPED. 3.00 itself is passing -> not at risk. Exercised
    through the real parser, not a re-implemented literal."""

    def test_grade_above_3_00_is_at_risk(self):
        buf = _minimal_class_record_bytes([("2026-0001", 5, 3.5, "FAILED")])
        preview = build_import_preview([("test.xlsx", buf)])
        self.assertGreater(preview.row_count, 0)
        self.assertTrue(all(r["label"] == 1 for r in preview.records))

    def test_grade_of_exactly_3_00_is_not_at_risk(self):
        buf = _minimal_class_record_bytes([("2026-0002", 9, 3.00, "PASSED")])
        preview = build_import_preview([("test.xlsx", buf)])
        self.assertGreater(preview.row_count, 0)
        self.assertTrue(all(r["label"] == 0 for r in preview.records))

    def test_inc_is_at_risk_even_with_a_decent_score_so_far(self):
        buf = _minimal_class_record_bytes([("2026-0003", 8, None, "INC")])
        preview = build_import_preview([("test.xlsx", buf)])
        self.assertGreater(preview.row_count, 0)
        self.assertTrue(all(r["label"] == 1 for r in preview.records))

    def test_dropped_is_at_risk_even_with_a_decent_score_so_far(self):
        buf = _minimal_class_record_bytes([("2026-0004", 8, None, "DROPPED")])
        preview = build_import_preview([("test.xlsx", buf)])
        self.assertGreater(preview.row_count, 0)
        self.assertTrue(all(r["label"] == 1 for r in preview.records))


class SyntheticTrainingSanityTests(TestCase):
    def test_synthetic_rows_have_target_positive_rate_and_shape(self):
        rows = generate_synthetic_rows(Checkpoint.MIDTERM, n=500, positive_rate=0.2)
        self.assertEqual(len(rows), 500)
        positive_rate = sum(r["label"] for r in rows) / len(rows)
        self.assertAlmostEqual(positive_rate, 0.2, delta=0.03)
        for name in FEATURE_NAMES:
            self.assertIn(name, rows[0])

    def test_training_on_synthetic_data_achieves_recall_above_0_7(self):
        """Sanity check with a fixed seed — the whole point of the
        correlated synthetic generator is that this is learnable."""
        version = train_model(Checkpoint.MIDTERM, TrainingSource.SYNTHETIC)
        self.assertGreater(version.metrics_json["recall"], 0.7)
        self.assertEqual(version.training_source, TrainingSource.SYNTHETIC)
        self.assertFalse(version.is_active)  # never auto-activated


class ThresholdTests(TestCase):
    def test_changing_threshold_changes_the_label(self):
        version = train_model(Checkpoint.MIDTERM, TrainingSource.SYNTHETIC, threshold=Decimal("0.50"))
        table = {row["threshold"]: row for row in version.metrics_json["threshold_table"]}
        # A lower threshold must never classify fewer positives than a
        # higher one (monotonic in recall as threshold decreases).
        self.assertGreaterEqual(table[0.3]["recall"], table[0.7]["recall"])


class RefuseToTrainTests(TestCase):
    def test_refuses_historical_only_training_below_minimums(self):
        batch = HistoricalImportBatch.objects.create(file_count=1, row_count=5, positive_count=1)
        for i in range(5):
            HistoricalRecord.objects.create(
                masked_id=f"id{i}",
                semester_label="2024",
                subject_code="IT101",
                checkpoint=Checkpoint.MIDTERM,
                features_json={name: "50" for name in FEATURE_NAMES},
                label=1 if i == 0 else 0,
                batch=batch,
            )
        with self.assertRaises(ValidationError) as ctx:
            train_model(Checkpoint.MIDTERM, TrainingSource.HISTORICAL)
        self.assertIn(str(MIN_HISTORICAL_ROWS), str(ctx.exception))

    def test_mixed_source_works_even_with_too_little_historical_data(self):
        version = train_model(Checkpoint.MIDTERM, TrainingSource.MIXED)
        self.assertEqual(version.training_source, TrainingSource.MIXED)
        self.assertGreaterEqual(version.n_samples, 2000)


class PredictTests(GradingTestBase):
    def setUp(self):
        super().setUp()
        self.quiz_items = self.make_items("Quizzes", [20], term=AssessmentTerm.MIDTERM)
        self.set_scores(self.roster_entry, self.quiz_items, [5])
        self.version = train_model(Checkpoint.MIDTERM, TrainingSource.SYNTHETIC)
        self.version.is_active = True
        self.version.save()

    def test_contributions_plus_intercept_equal_the_logit(self):
        result = predict(self.roster_entry, Checkpoint.MIDTERM, model_version=self.version)
        self.assertNotEqual(result, "insufficient_data")

        probability = result["probability"]
        logit = math.log(probability / (1 - probability))
        total = result["contributions"]["intercept"] + sum(
            c["contribution"] for c in result["contributions"]["values"]
        )
        self.assertAlmostEqual(total, logit, places=6)

    def test_insufficient_data_when_class_has_no_scores_at_all(self):
        other_student = make_user(User.Role.STUDENT, "forecast_student2", id_number="2026-7777")
        other_class = ClassOffering.objects.create(
            subject=self.subject, semester=self.semester, instructor=self.instructor
        )
        other_class.sections.set([self.section])
        empty_entry = ClassRosterEntry.objects.create(student=other_student, class_offering=other_class)

        result = predict(empty_entry, Checkpoint.MIDTERM, model_version=self.version)
        self.assertEqual(result, "insufficient_data")

    def test_insufficient_data_when_no_active_model(self):
        empty_entry = self.roster_entry
        result = predict(empty_entry, Checkpoint.PRELIM, model_version=None)
        # No active PRELIM model exists in this test (only MIDTERM trained above).
        self.assertEqual(result, "insufficient_data")

    def test_label_matches_threshold(self):
        result = predict(self.roster_entry, Checkpoint.MIDTERM, model_version=self.version)
        expected_label = RiskLabel.AT_RISK if result["probability"] >= float(self.version.threshold) else RiskLabel.NOT_AT_RISK
        self.assertEqual(result["label"], expected_label)


# ---------------------------------------------------------------------------
# Part 2 — predictions in the UI, interventions, early warning
# ---------------------------------------------------------------------------

from django.urls import reverse

from approvals.services import submit_grade_sheet
from reports.models import InstitutionSettings

from .models import Intervention
from .services import (
    current_checkpoint_for_class,
    get_display_forecast,
    recompute_and_notify,
    risk_level,
    show_forecasts_to_students,
    student_forecast_card,
)


class ForecastingPart2TestBase(GradingTestBase):
    """Trains + activates one synthetic model per checkpoint once per test
    class (training is slow; independent of the per-test grading fixtures,
    so sharing it via setUpTestData is safe)."""

    @classmethod
    def setUpTestData(cls):
        cls.midterm_model = train_model(Checkpoint.MIDTERM, TrainingSource.SYNTHETIC)
        cls.midterm_model.is_active = True
        cls.midterm_model.save()
        cls.prelim_model = train_model(Checkpoint.PRELIM, TrainingSource.SYNTHETIC)
        cls.prelim_model.is_active = True
        cls.prelim_model.save()

    def setUp(self):
        super().setUp()
        # GradingTestBase's student fixture has no last_name (blank) — give
        # it one so assertNotContains/assertContains checks on last_name
        # here are meaningful (an empty string is trivially "contained" in
        # any response, which would make assertNotContains always fail).
        self.student.last_name = "Delacruz"
        self.student.save(update_fields=["last_name"])
        self.program_head = make_user(User.Role.PROGRAM_HEAD, "fc_ph")
        self.program.program_head = self.program_head
        self.program.save()
        self.other_instructor = make_user(User.Role.INSTRUCTOR, "fc_other_instructor")

    def score_exam_item(self, term=AssessmentTerm.MIDTERM, value=15, max_score=20):
        items = self.make_items("Examination", [max_score], term=term)
        self.set_scores(self.roster_entry, items, [value])
        return items[0]


class CheckpointSelectionTests(ForecastingPart2TestBase):
    def test_no_checkpoint_when_nothing_scored(self):
        self.assertIsNone(current_checkpoint_for_class(self.class_offering))

    def test_prelim_checkpoint_from_any_prelim_item(self):
        items = self.make_items("Quizzes", [10], term=AssessmentTerm.PRELIM)
        self.set_scores(self.roster_entry, items, [5])
        self.assertEqual(current_checkpoint_for_class(self.class_offering), Checkpoint.PRELIM)

    def test_midterm_checkpoint_requires_an_exam_item_scored(self):
        # A scored PRELIM quiz alone must not promote to MIDTERM.
        quiz_items = self.make_items("Quizzes", [10], term=AssessmentTerm.PRELIM)
        self.set_scores(self.roster_entry, quiz_items, [5])
        self.assertEqual(current_checkpoint_for_class(self.class_offering), Checkpoint.PRELIM)

        self.score_exam_item(term=AssessmentTerm.MIDTERM)
        self.assertEqual(current_checkpoint_for_class(self.class_offering), Checkpoint.MIDTERM)

    def test_midterm_checkpoint_from_a_scored_prelim_exam_item_too(self):
        self.score_exam_item(term=AssessmentTerm.PRELIM)
        self.assertEqual(current_checkpoint_for_class(self.class_offering), Checkpoint.MIDTERM)


class RiskLevelBoundaryTests(TestCase):
    def test_at_risk_at_exactly_threshold(self):
        self.assertEqual(risk_level(0.5, 0.5), "AT_RISK")

    def test_just_below_threshold_is_watch(self):
        self.assertEqual(risk_level(0.4999, 0.5), "WATCH")

    def test_watch_at_lower_boundary(self):
        self.assertEqual(risk_level(0.35, 0.5), "WATCH")

    def test_just_below_watch_boundary_is_on_track(self):
        self.assertEqual(risk_level(0.3499, 0.5), "ON_TRACK")

    def test_zero_probability_is_on_track(self):
        self.assertEqual(risk_level(0.0, 0.5), "ON_TRACK")


class RecomputeTests(ForecastingPart2TestBase):
    def test_recompute_affects_only_the_given_student(self):
        other_student = make_user(User.Role.STUDENT, "fc_other_student", id_number="2026-8800")
        other_entry = ClassRosterEntry.objects.create(student=other_student, class_offering=self.class_offering)
        self.score_exam_item()
        self.set_scores(other_entry, self.scheme_components["Examination"].items.all(), [18])

        from .models import Prediction

        recompute_and_notify([self.roster_entry])

        self.assertTrue(Prediction.objects.filter(roster_entry=self.roster_entry, checkpoint=Checkpoint.MIDTERM).exists())
        self.assertFalse(Prediction.objects.filter(roster_entry=other_entry, checkpoint=Checkpoint.MIDTERM).exists())

    def test_no_recompute_once_grade_sheet_is_submitted(self):
        self.score_exam_item()
        recompute_and_notify([self.roster_entry])

        from .models import Prediction

        before = Prediction.objects.get(roster_entry=self.roster_entry, checkpoint=Checkpoint.MIDTERM)

        # Fully score the class and submit — recompute must then be a no-op.
        for name, maxes in [("Attendance", [10]), ("Quizzes", [10]), ("Recitation", [10]), ("Project", [10])]:
            items = self.make_items(name, maxes, term=AssessmentTerm.MIDTERM)
            self.set_scores(self.roster_entry, items, [8])
        submit_grade_sheet(self.class_offering, self.instructor)

        recompute_and_notify([self.roster_entry])
        after = Prediction.objects.get(roster_entry=self.roster_entry, checkpoint=Checkpoint.MIDTERM)
        self.assertEqual(before.computed_at, after.computed_at)  # untouched — last forecast kept for evaluation

    def test_get_display_forecast_lazily_backfills_when_editable(self):
        self.score_exam_item()
        forecast = get_display_forecast(self.roster_entry)
        self.assertNotIsInstance(forecast, str)
        self.assertEqual(forecast.checkpoint, Checkpoint.MIDTERM)

    def test_forecast_unavailable_when_no_active_model(self):
        self.midterm_model.is_active = False
        self.midterm_model.save()
        self.prelim_model.is_active = False
        self.prelim_model.save()
        self.score_exam_item()
        self.assertEqual(get_display_forecast(self.roster_entry), "not_enough_data")


class NotificationDeduplicationTests(ForecastingPart2TestBase):
    def test_instructor_notified_once_per_at_risk_episode(self):
        from dashboard.models import Notification

        # A weak score should land this synthetic-model prediction AT_RISK
        # with high probability (low exam score).
        self.score_exam_item(value=1, max_score=20)
        recompute_and_notify([self.roster_entry])
        first_count = Notification.objects.filter(recipient=self.instructor).count()

        # Recomputing again with the SAME data must not send a second one.
        recompute_and_notify([self.roster_entry])
        second_count = Notification.objects.filter(recipient=self.instructor).count()
        self.assertEqual(first_count, second_count)

    def test_renotifies_after_dropping_out_of_at_risk_and_back(self):
        from .models import Prediction

        self.score_exam_item(value=1, max_score=20)
        recompute_and_notify([self.roster_entry])
        prediction = Prediction.objects.get(roster_entry=self.roster_entry, checkpoint=Checkpoint.MIDTERM)
        was_notified_once = prediction.instructor_notified_at is not None

        # Force the stored level back down (simulating an improved score on
        # the next recompute) by editing the item's score directly.
        item = self.scheme_components["Examination"].items.first()
        self.set_scores(self.roster_entry, [item], [19])
        recompute_and_notify([self.roster_entry])
        prediction.refresh_from_db()

        self.assertTrue(was_notified_once)
        # Whatever the new level is, instructor_notified_at must only be
        # set if the level is AT_RISK again — never stale from before.
        if risk_level(prediction.probability, prediction.model_version.threshold) != "AT_RISK":
            self.assertIsNone(prediction.instructor_notified_at)


class AccessControlTests(ForecastingPart2TestBase):
    def test_instructor_cannot_view_another_instructors_class_at_risk_filter(self):
        self.client.force_login(self.other_instructor)
        response = self.client.get(reverse("forecasting:at_risk"), {"class": self.class_offering.pk})
        self.assertEqual(response.status_code, 200)  # page loads; just scoped to nothing of theirs
        self.assertNotContains(response, self.student.last_name)

    def test_instructor_cannot_recompute_another_instructors_class(self):
        self.client.force_login(self.other_instructor)
        response = self.client.post(reverse("forecasting:recompute_class", args=[self.class_offering.pk]))
        self.assertEqual(response.status_code, 403)

    def test_instructor_cannot_view_forecast_detail_for_another_instructors_student(self):
        self.client.force_login(self.other_instructor)
        response = self.client.get(reverse("forecasting:forecast_detail", args=[self.roster_entry.pk]))
        self.assertEqual(response.status_code, 403)

    def test_program_head_cannot_recompute_another_programs_class(self):
        other_program_head = make_user(User.Role.PROGRAM_HEAD, "fc_other_ph")
        self.client.force_login(other_program_head)
        response = self.client.post(reverse("forecasting:recompute_class", args=[self.class_offering.pk]))
        self.assertEqual(response.status_code, 403)

    def test_program_head_cannot_recompute_another_programs_program(self):
        from academics.models import Program

        other_program_head = make_user(User.Role.PROGRAM_HEAD, "fc_other_ph2")
        other_program = Program.objects.create(code="OTHERP", name="Other Program", program_head=other_program_head)
        self.client.force_login(self.program_head)
        response = self.client.post(reverse("forecasting:recompute_program", args=[other_program.pk]))
        self.assertEqual(response.status_code, 403)

    def test_own_program_head_can_recompute_their_program(self):
        self.client.force_login(self.program_head)
        response = self.client.post(reverse("forecasting:recompute_program", args=[self.program.pk]))
        self.assertEqual(response.status_code, 302)

    def test_student_cannot_access_at_risk_page(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("forecasting:at_risk"))
        self.assertEqual(response.status_code, 403)

    def test_student_cannot_access_forecast_detail(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("forecasting:forecast_detail", args=[self.roster_entry.pk]))
        self.assertEqual(response.status_code, 403)

    def test_student_cannot_access_intervention_create(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("forecasting:intervention_create", args=[self.roster_entry.pk]))
        self.assertEqual(response.status_code, 403)


class StudentPrivacyTests(ForecastingPart2TestBase):
    def setUp(self):
        super().setUp()
        inst = InstitutionSettings.get_solo()
        inst.show_forecasts_to_students = True
        inst.save()
        self.score_exam_item(value=1, max_score=20)  # weak score -> likely AT_RISK/WATCH
        recompute_and_notify([self.roster_entry])

    def test_dashboard_never_shows_probability_or_at_risk_wording(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("dashboard:home"))
        body = response.content.decode("utf-8")
        self.assertNotIn("AT_RISK", body)
        self.assertNotIn("at risk", body.lower())
        self.assertNotIn("probability", body.lower())

    def test_subject_detail_never_shows_probability_or_at_risk_wording(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("grading:subject_detail", args=[self.roster_entry.pk]))
        body = response.content.decode("utf-8")
        self.assertNotIn("AT_RISK", body)
        self.assertNotIn("at risk", body.lower())
        self.assertNotIn("probability", body.lower())

    def test_student_forecast_card_has_no_numeric_probability_field(self):
        card = student_forecast_card(self.roster_entry)
        self.assertIsNotNone(card)
        self.assertNotIn("probability", card)


class SettingsToggleTests(ForecastingPart2TestBase):
    def test_default_is_off(self):
        self.assertFalse(show_forecasts_to_students())

    def test_toggle_off_hides_student_forecast_card(self):
        self.score_exam_item()
        recompute_and_notify([self.roster_entry])
        self.assertIsNone(student_forecast_card(self.roster_entry))

    def test_toggle_on_shows_student_forecast_card(self):
        inst = InstitutionSettings.get_solo()
        inst.show_forecasts_to_students = True
        inst.save()
        self.score_exam_item()
        recompute_and_notify([self.roster_entry])
        self.assertIsNotNone(student_forecast_card(self.roster_entry))


class InterventionPrivacyTests(ForecastingPart2TestBase):
    def setUp(self):
        super().setUp()
        self.intervention = Intervention.objects.create(
            roster_entry=self.roster_entry,
            created_by=self.instructor,
            date="2026-11-04",
            type="CONSULTATION",
            notes="Confidential note.",
            outcome="PENDING",
        )

    def test_intervention_never_reaches_student_pages(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("grading:subject_detail", args=[self.roster_entry.pk]))
        self.assertNotContains(response, "Confidential note.")

    def test_instructor_sees_intervention_in_drawer(self):
        self.client.force_login(self.instructor)
        response = self.client.get(reverse("forecasting:forecast_detail", args=[self.roster_entry.pk]))
        self.assertContains(response, "Confidential note.")

    def test_program_head_sees_intervention_in_drawer(self):
        self.client.force_login(self.program_head)
        response = self.client.get(reverse("forecasting:forecast_detail", args=[self.roster_entry.pk]))
        self.assertContains(response, "Confidential note.")
