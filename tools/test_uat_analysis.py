"""Tests for tools/uat_analysis.py — standalone unittest (not a Django app,
so not part of `manage.py test`). Run with:

    python -m unittest tools.test_uat_analysis -v

from the repo root, or `python tools/test_uat_analysis.py`.
"""

import csv
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uat_analysis  # noqa: E402
from generate_uat_docs import CHAR_NAMES  # noqa: E402


class ReadResponsesTests(unittest.TestCase):
    def test_reads_rows_grouped_by_role(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["role", "FS1", "FS2"])
            writer.writerow(["Student", "5", "4"])
            writer.writerow(["Student", "3", ""])
            writer.writerow(["Staff", "4", "4"])
            path = f.name
        try:
            by_role = uat_analysis.read_responses(path)
            self.assertEqual(len(by_role["Student"]), 2)
            self.assertEqual(len(by_role["Staff"]), 1)
            self.assertEqual(by_role["Student"][0]["FS1"], 5)
            self.assertIsNone(by_role["Student"][1]["FS2"])
        finally:
            os.unlink(path)


class ItemStatsTests(unittest.TestCase):
    def test_mean_and_sd_computed_correctly(self):
        responses = [{"FS1": 5}, {"FS1": 3}, {"FS1": 4}, {"FS1": None}]
        mean, sd, n, distribution = uat_analysis.item_stats(responses, "FS1")
        self.assertAlmostEqual(mean, 4.0)
        self.assertEqual(n, 3)
        self.assertEqual(distribution[5], 1)
        self.assertEqual(distribution[1], 0)

    def test_no_answers_returns_none(self):
        mean, sd, n, distribution = uat_analysis.item_stats([{"FS1": None}], "FS1")
        self.assertIsNone(mean)
        self.assertEqual(n, 0)


class InterpretTests(unittest.TestCase):
    def test_bands_match_the_documented_ranges(self):
        self.assertEqual(uat_analysis.interpret(4.5), "Excellent")
        self.assertEqual(uat_analysis.interpret(4.21), "Excellent")
        self.assertEqual(uat_analysis.interpret(4.20), "Very Good")
        self.assertEqual(uat_analysis.interpret(3.0), "Good")
        self.assertEqual(uat_analysis.interpret(2.0), "Fair")
        self.assertEqual(uat_analysis.interpret(1.0), "Poor")
        self.assertEqual(uat_analysis.interpret(None), "N/A")


class AnalyzeAndAnovaTests(unittest.TestCase):
    def test_analyze_produces_a_characteristic_and_overall_mean_per_role(self):
        by_role = {
            "Student": [{"FS1": 5, "FS2": 5, "FS3": 5, "FS4": 5}],
        }
        report = uat_analysis.analyze(by_role)
        student = report["roles"]["Student"]
        self.assertEqual(student["n_respondents"], 1)
        fs_row = next(r for r in student["characteristics"] if r["characteristic"] == "FS")
        self.assertAlmostEqual(fs_row["mean"], 5.0)
        self.assertEqual(fs_row["interpretation"], "Excellent")
        self.assertAlmostEqual(student["overall_mean"], 5.0)

    def test_anova_runs_between_two_groups_sharing_a_characteristic(self):
        by_role = {
            "Student": [{"FS1": 5, "FS2": 5} for _ in range(5)],
            "Staff": [{"FS1": 2, "FS2": 2} for _ in range(5)],
        }
        report = uat_analysis.analyze(by_role)
        self.assertIn("FS", report["anova"])
        result = report["anova"]["FS"]["result"]
        self.assertIsNotNone(result)
        f_stat, p_value = result
        # Two groups with zero within-group variance and a clear mean gap
        # must be a significant difference.
        self.assertLess(p_value, 0.05)

    def test_no_anova_entry_when_only_one_group_answers_a_characteristic(self):
        by_role = {"ITExpert": [{"MAIN1": 4, "MAIN2": 4, "MAIN3": 4, "MAIN4": 4}]}
        report = uat_analysis.analyze(by_role)
        self.assertNotIn("MAIN", report["anova"])


class EndToEndOutputTests(unittest.TestCase):
    """Exercises the real sample CSV shipped alongside the questionnaire
    and confirms both output formats are produced without error."""

    def test_sample_responses_csv_produces_xlsx_and_markdown(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sample_csv = os.path.join(repo_root, "docs", "uat", "sample_responses.csv")
        self.assertTrue(os.path.exists(sample_csv), "docs/uat/sample_responses.csv is missing")

        with tempfile.TemporaryDirectory() as tmp:
            xlsx_path = os.path.join(tmp, "out.xlsx")
            md_path = os.path.join(tmp, "out.md")
            by_role = uat_analysis.read_responses(sample_csv)
            self.assertIn("Student", by_role)
            report = uat_analysis.analyze(by_role)
            uat_analysis.write_markdown(report, md_path)
            uat_analysis.write_xlsx(report, xlsx_path)
            self.assertTrue(os.path.exists(xlsx_path))
            self.assertTrue(os.path.exists(md_path))
            with open(md_path, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("UAT Analysis Summary", content)
            self.assertIn(CHAR_NAMES["FS"], content)


if __name__ == "__main__":
    unittest.main()
