from django.conf import settings
from django.db import models, transaction

from academics.models import ClassRosterEntry
from core.models import TimeStampedModel


class Checkpoint(models.TextChoices):
    """CITCI's class record has no separate "midterm grade" field (section
    4) — only the four grading periods. A forecast is computed at one of
    these two checkpoints; Semi-final/Final items must never reach a
    feature row (data leakage) — see forecasting/ml/features.py."""

    PRELIM = "PRELIM", "Prelim"
    MIDTERM = "MIDTERM", "Midterm"


class TrainingSource(models.TextChoices):
    SYNTHETIC = "SYNTHETIC", "Synthetic"
    HISTORICAL = "HISTORICAL", "Historical"
    MIXED = "MIXED", "Mixed"


class RiskLabel(models.TextChoices):
    """Internal/staff-facing value. Student-facing copy is "Needs
    Attention"/"On Track" (CLAUDE.md section 3) — applied at the template
    layer in Phase 7, never stored under those words."""

    AT_RISK = "AT_RISK", "At risk"
    NOT_AT_RISK = "NOT_AT_RISK", "Not at risk"


class MlModelVersion(TimeStampedModel):
    """One trained model for one checkpoint. At most one ACTIVE version per
    checkpoint at a time — `save()` deactivates any other active version
    for the same checkpoint, same single-active pattern as
    academics.Semester / grading.GradingTemplate."""

    checkpoint = models.CharField(max_length=10, choices=Checkpoint.choices)
    trained_at = models.DateTimeField(auto_now_add=True)
    training_source = models.CharField(max_length=10, choices=TrainingSource.choices)
    n_samples = models.PositiveIntegerField()
    positive_rate = models.DecimalField(max_digits=5, decimal_places=4)
    threshold = models.DecimalField(max_digits=3, decimal_places=2, default=0.50)

    metrics_json = models.JSONField(help_text="accuracy/precision/recall/f1/roc_auc + 95% bootstrap CIs")
    cv_json = models.JSONField(help_text="5-fold stratified CV mean +/- SD per metric")
    confusion_matrix_json = models.JSONField()
    coefficients_json = models.JSONField(help_text="[{feature, coefficient, odds_ratio}, ...]")
    feature_list = models.JSONField(help_text="feature names/order + imputation medians used at train time")

    is_active = models.BooleanField(default=False)
    model_file = models.CharField(max_length=255, help_text="joblib path under MEDIA_ROOT/models/ — not committed to git.")

    class Meta:
        ordering = ["-trained_at"]

    def __str__(self):
        return f"{self.get_checkpoint_display()} model v{self.pk} ({self.get_training_source_display()})"

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.is_active:
                MlModelVersion.objects.exclude(pk=self.pk).filter(checkpoint=self.checkpoint, is_active=True).update(
                    is_active=False
                )
            super().save(*args, **kwargs)


class Prediction(TimeStampedModel):
    roster_entry = models.ForeignKey(ClassRosterEntry, on_delete=models.CASCADE, related_name="forecast_predictions")
    checkpoint = models.CharField(max_length=10, choices=Checkpoint.choices)
    model_version = models.ForeignKey(MlModelVersion, on_delete=models.PROTECT, related_name="predictions")
    probability = models.DecimalField(max_digits=6, decimal_places=5)
    label = models.CharField(max_length=15, choices=RiskLabel.choices)
    contributions_json = models.JSONField(help_text="per-feature contribution + plain-language reasons, sorted by impact")
    computed_at = models.DateTimeField(auto_now_add=True)

    # Early-warning de-duplication (CLAUDE.md section 7 part 2) — set when a
    # notification was actually sent for the CURRENT at-risk/watch episode
    # at this (roster_entry, checkpoint); cleared back to None once the
    # level drops, so a later episode can notify again. Never re-notify on
    # every recompute while still at the same level.
    instructor_notified_at = models.DateTimeField(null=True, blank=True)
    student_notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-computed_at"]
        constraints = [
            models.UniqueConstraint(fields=["roster_entry", "checkpoint"], name="one_prediction_per_roster_entry_checkpoint")
        ]

    def __str__(self):
        return f"{self.roster_entry} @ {self.get_checkpoint_display()}: {self.get_label_display()} ({self.probability})"


class HistoricalImportBatch(TimeStampedModel):
    """One admin upload of past CITCI class records (possibly many files at
    once). `term_assignment_note` records the disclosed, non-silent
    assumption for old sheets whose non-exam items carry no term —
    chronological-order-by-position, split into quarters (section 7)."""

    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    file_count = models.PositiveIntegerField()
    row_count = models.PositiveIntegerField()
    positive_count = models.PositiveIntegerField()
    term_assignment_note = models.TextField(
        default="Non-exam items with no recorded term were assigned to a grading period by column "
        "position (chronological order assumed), split into quarters — Prelim/Midterm/Semi-final/"
        "Final. This is a stated limitation, not a verified term."
    )
    skipped_rows_json = models.JSONField(default=list, blank=True, help_text="[{file, row, reason}, ...]")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Batch #{self.pk} — {self.file_count} file(s), {self.row_count} row(s)"


class HistoricalRecord(models.Model):
    """Training data only — masked, no names, no FK to User/StudentProfile
    anywhere on this model, by design. `masked_id` is SHA-256(app secret
    salt + real identifier); the same student always hashes to the same
    masked_id within a batch, but the real identifier is never stored."""

    masked_id = models.CharField(max_length=64)
    semester_label = models.CharField(max_length=100)
    subject_code = models.CharField(max_length=20)
    checkpoint = models.CharField(max_length=10, choices=Checkpoint.choices)
    features_json = models.JSONField()
    label = models.PositiveSmallIntegerField(help_text="1 = at risk, 0 = not at risk")
    batch = models.ForeignKey(HistoricalImportBatch, on_delete=models.CASCADE, related_name="records")

    class Meta:
        indexes = [models.Index(fields=["checkpoint"])]

    def __str__(self):
        return f"{self.subject_code} ({self.semester_label}) @ {self.checkpoint} — label={self.label}"


class InterventionType(models.TextChoices):
    CONSULTATION = "CONSULTATION", "Consultation"
    REMEDIAL = "REMEDIAL", "Remedial activity"
    REFERRAL = "REFERRAL", "Referral to guidance"
    PARENT_CONTACT = "PARENT_CONTACT", "Parent or guardian contact"
    OTHER = "OTHER", "Other"


class InterventionOutcome(models.TextChoices):
    PENDING = "PENDING", "Pending"
    IMPROVED = "IMPROVED", "Improved"
    NO_CHANGE = "NO_CHANGE", "No change"


class Intervention(TimeStampedModel):
    """An instructor's (or program head's) free-text note on an at-risk
    student — visible to instructor and program head, never to students
    (CLAUDE.md section 7 part 2)."""

    roster_entry = models.ForeignKey(ClassRosterEntry, on_delete=models.CASCADE, related_name="interventions")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    date = models.DateField()
    type = models.CharField(max_length=20, choices=InterventionType.choices)
    notes = models.TextField(blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    outcome = models.CharField(max_length=10, choices=InterventionOutcome.choices, default=InterventionOutcome.PENDING)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.get_type_display()} for {self.roster_entry} on {self.date}"
