"""Dev-only preview of the synthetic data generator — prints row count,
positive rate, and basic feature stats for both checkpoints. Nothing is
persisted to the database: forecasting.ml.train.train_model(source=
synthetic) regenerates the same rows on demand (fixed seed), so there's no
synthetic-data table to populate. `--csv` exports the deterministic
dataset to disk instead, for the paper's appendix/reproducibility — still
no DB persistence, just a file."""

import csv
import statistics

from django.core.management.base import BaseCommand

from forecasting.ml.features import FEATURE_NAMES
from forecasting.ml.synthetic import DEFAULT_N, DEFAULT_POSITIVE_RATE, generate_synthetic_rows
from forecasting.models import Checkpoint


class Command(BaseCommand):
    help = "Preview the synthetic forecasting data generator, or export it to CSV with --csv (see module docstring)."

    def add_arguments(self, parser):
        parser.add_argument("--n", type=int, default=DEFAULT_N)
        parser.add_argument("--positive-rate", type=float, default=DEFAULT_POSITIVE_RATE)
        parser.add_argument("--csv", dest="csv_path", default=None, help="Export features+label per checkpoint to this CSV path (no DB writes).")

    def handle(self, *args, **options):
        if options["csv_path"]:
            self._export_csv(options)
            return

        for checkpoint in (Checkpoint.PRELIM, Checkpoint.MIDTERM):
            rows = generate_synthetic_rows(checkpoint, n=options["n"], positive_rate=options["positive_rate"])
            positives = sum(row["label"] for row in rows)
            self.stdout.write(self.style.SUCCESS(f"\n{checkpoint}: {len(rows)} rows, {positives} positive ({positives / len(rows):.1%})"))
            for name in FEATURE_NAMES:
                values = [row[name] for row in rows]
                self.stdout.write(f"  {name:<18} mean={statistics.mean(values):6.2f}  sd={statistics.pstdev(values):6.2f}")

    def _export_csv(self, options):
        fieldnames = ["checkpoint"] + FEATURE_NAMES + ["label"]
        with open(options["csv_path"], "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            total = 0
            for checkpoint in (Checkpoint.PRELIM, Checkpoint.MIDTERM):
                rows = generate_synthetic_rows(checkpoint, n=options["n"], positive_rate=options["positive_rate"])
                for row in rows:
                    writer.writerow({"checkpoint": checkpoint, **row})
                total += len(rows)
        self.stdout.write(self.style.SUCCESS(f"Exported {total} rows to {options['csv_path']}."))
