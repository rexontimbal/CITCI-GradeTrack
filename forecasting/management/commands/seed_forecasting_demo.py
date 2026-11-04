"""Ensures the demo environment has real forecasting content to look at
(CLAUDE.md section 7 part 2 — Phase 7 demo data):

    - An active synthetic model for each checkpoint (trained if missing —
      never auto-activates a HISTORICAL model, matching the admin-review
      rule everywhere else).
    - A real mix of AT RISK / WATCH / ON TRACK predictions across the demo
      classes seed_grading_demo/seed_student_portal_demo already set up
      (their low-performer students naturally skew at-risk; nudged with
      one extra low-scoring student per class if a run produces no
      variety at all).
    - A couple of logged Interventions for an at-risk student, so the
      instructor/program-head At-Risk pages and the forecast drawer aren't
      empty on a fresh environment.

Idempotent — safe to re-run.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand

from academics.models import ClassOffering, ClassRosterEntry
from accounts.models import User
from core.management.guards import add_force_demo_argument, ensure_demo_allowed
from forecasting.ml.train import train_model
from forecasting.models import Checkpoint, Intervention, InterventionType, MlModelVersion, TrainingSource
from forecasting.services import recompute_and_notify, risk_level


class Command(BaseCommand):
    help = "Fills in demo forecasting content (active models, a mix of risk levels, logged interventions). Idempotent."

    def add_arguments(self, parser):
        add_force_demo_argument(parser)

    def handle(self, *args, **options):
        ensure_demo_allowed(options.get("force_demo"))
        self._ensure_active_models()
        predictions = self._recompute_demo_classes()
        self._log_demo_interventions(predictions)
        self.stdout.write(self.style.SUCCESS("Forecasting demo data ready."))

    def _ensure_active_models(self):
        for checkpoint in (Checkpoint.PRELIM, Checkpoint.MIDTERM):
            if MlModelVersion.objects.filter(checkpoint=checkpoint, is_active=True).exists():
                continue
            version = train_model(checkpoint, TrainingSource.SYNTHETIC)
            version.is_active = True
            version.save()
            self.stdout.write(self.style.SUCCESS(f"Activated a new synthetic {checkpoint} model (v{version.pk})."))

    def _recompute_demo_classes(self):
        """Classes with assessment items + an instructor — the same demo
        classes seed_grading_demo/seed_student_portal_demo already scored."""
        classes = ClassOffering.objects.filter(
            assessment_items__isnull=False, instructor__isnull=False
        ).distinct()[:6]

        entries = ClassRosterEntry.objects.filter(
            class_offering__in=classes, status=ClassRosterEntry.Status.ACTIVE
        )
        recompute_and_notify(entries)

        from forecasting.services import current_checkpoint_for_class
        from forecasting.models import Prediction

        predictions = []
        for class_offering in classes:
            checkpoint = current_checkpoint_for_class(class_offering)
            if checkpoint is None:
                continue
            predictions.extend(
                Prediction.objects.filter(
                    roster_entry__class_offering=class_offering, checkpoint=checkpoint
                ).select_related("model_version", "roster_entry__student")
            )

        levels = {risk_level(p.probability, p.model_version.threshold) for p in predictions}
        if len(levels) < 2 and predictions:
            self._nudge_one_student_at_risk(classes)
            recompute_and_notify(entries)
            predictions = []
            for class_offering in classes:
                checkpoint = current_checkpoint_for_class(class_offering)
                if checkpoint is None:
                    continue
                predictions.extend(
                    Prediction.objects.filter(
                        roster_entry__class_offering=class_offering, checkpoint=checkpoint
                    ).select_related("model_version", "roster_entry__student")
                )

        self.stdout.write(self.style.SUCCESS(f"Recomputed forecasts for {len(predictions)} roster entries across {classes.count()} demo classes."))
        return predictions

    def _nudge_one_student_at_risk(self, classes):
        """Guarantees at least one genuinely low score exists somewhere,
        in case the seeded demo scores happened to all land comfortably
        passing for every student this run."""
        from grading.models import AssessmentItem

        for class_offering in classes:
            item = AssessmentItem.objects.filter(class_offering=class_offering, component__category="EXAM").first()
            entry = class_offering.roster_entries.filter(status=ClassRosterEntry.Status.ACTIVE).first()
            if item is None or entry is None:
                continue
            from grading.services import save_score

            instructor = class_offering.instructor
            save_score(entry, item, 0, instructor)
            self.stdout.write(self.style.SUCCESS(f"Nudged {entry.student.full_name} in {class_offering} toward at-risk for demo variety."))
            return

    def _log_demo_interventions(self, predictions):
        if Intervention.objects.exists():
            return  # already seeded on a previous run

        from forecasting.models import Prediction

        all_predictions = Prediction.objects.select_related("model_version", "roster_entry__class_offering__instructor", "roster_entry__student")
        at_risk_predictions = [
            p
            for p in all_predictions
            if risk_level(p.probability, p.model_version.threshold) == "AT_RISK" and p.roster_entry.class_offering.instructor_id
        ]
        if not at_risk_predictions:
            return

        prediction = at_risk_predictions[0]
        roster_entry = prediction.roster_entry
        instructor = roster_entry.class_offering.instructor
        if instructor is None:
            return

        Intervention.objects.create(
            roster_entry=roster_entry,
            created_by=instructor,
            date=prediction.computed_at.date(),
            type=InterventionType.CONSULTATION,
            notes="Checked in with the student about recent scores and encouraged attending consultation hours.",
            outcome="PENDING",
        )
        if len(at_risk_predictions) > 1:
            second = at_risk_predictions[1]
            Intervention.objects.create(
                roster_entry=second.roster_entry,
                created_by=second.roster_entry.class_offering.instructor,
                date=second.computed_at.date(),
                type=InterventionType.REMEDIAL,
                notes="Assigned a short remedial activity covering the weakest topic area.",
                outcome="IMPROVED",
            )
        self.stdout.write(self.style.SUCCESS("Logged demo intervention(s)."))
