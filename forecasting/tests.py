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
