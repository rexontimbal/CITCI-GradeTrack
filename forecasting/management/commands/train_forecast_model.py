from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from forecasting.ml.train import train_model
from forecasting.models import Checkpoint, TrainingSource


class Command(BaseCommand):
    help = "Trains and evaluates a new (inactive) forecasting model for one checkpoint. Activate it from the Model Performance page."

    def add_arguments(self, parser):
        parser.add_argument("--checkpoint", required=True, choices=[c.lower() for c in Checkpoint.values])
        parser.add_argument("--source", required=True, choices=[s.lower() for s in TrainingSource.values])
        parser.add_argument("--threshold", type=str, default="0.50")

    def handle(self, *args, **options):
        checkpoint = options["checkpoint"].upper()
        source = options["source"].upper()
        threshold = Decimal(options["threshold"])

        try:
            version = train_model(checkpoint, source, threshold=threshold)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Trained {version} — n={version.n_samples}, positive_rate={version.positive_rate}, "
                f"recall={version.metrics_json['recall']:.3f}, roc_auc={version.metrics_json['roc_auc']:.3f}. "
                f"Inactive — activate it from the Model Performance page (version id {version.pk})."
            )
        )
