"""Predicts for every active class-list entry at both checkpoints. No task
queue (CLAUDE.md section 7 — Celery/Redis decided against; predictions are
cheap enough to run synchronously). Schedule this via Windows Task
Scheduler / cron for a nightly/periodic refresh; Phase 7 will also call the
same primitive (forecasting.ml.predict.predict_and_store) after an
instructor saves scores and from a "Recompute" button.
"""

from django.core.management.base import BaseCommand

from academics.models import ClassRosterEntry
from forecasting.ml.predict import predict_and_store
from forecasting.models import Checkpoint


class Command(BaseCommand):
    help = "Computes/refreshes forecasts for every active class-list entry at both checkpoints."

    def handle(self, *args, **options):
        roster_entries = ClassRosterEntry.objects.filter(status=ClassRosterEntry.Status.ACTIVE).select_related(
            "class_offering"
        )
        counts = {"predicted": 0, "insufficient_data": 0}

        for entry in roster_entries:
            for checkpoint in Checkpoint.values:
                result = predict_and_store(entry, checkpoint)
                if result == "insufficient_data":
                    counts["insufficient_data"] += 1
                else:
                    counts["predicted"] += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Forecasts refreshed: {counts['predicted']} predicted, "
                f"{counts['insufficient_data']} skipped (insufficient data or no active model)."
            )
        )
