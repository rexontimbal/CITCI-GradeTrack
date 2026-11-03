from django.conf import settings
from django.db import models

from academics.models import ClassOffering, ClassRosterEntry
from core.models import TimeStampedModel


class GradeSheetPeriod(models.TextChoices):
    """FINAL is the only period actually submitted today. MIDTERM is
    reserved — CITCI hasn't confirmed whether midterm grades go through
    their own submit/approve cycle — so the unique (class_offering, period)
    constraint already supports it with no schema change later."""

    FINAL = "FINAL", "Final"
    MIDTERM = "MIDTERM", "Midterm"


class GradeSheetStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    RETURNED = "RETURNED", "Returned"
    APPROVED = "APPROVED", "Approved"
    RELEASED = "RELEASED", "Released"
    LOCKED = "LOCKED", "Locked"


class GradeSheet(TimeStampedModel):
    """One per (ClassOffering, period). Status transitions only ever happen
    through approvals/services.py — never set directly from a view — so
    every change is role-checked and logged to GradeSheetTransition."""

    class_offering = models.ForeignKey(ClassOffering, on_delete=models.CASCADE, related_name="grade_sheets")
    period = models.CharField(max_length=10, choices=GradeSheetPeriod.choices, default=GradeSheetPeriod.FINAL)
    status = models.CharField(max_length=10, choices=GradeSheetStatus.choices, default=GradeSheetStatus.DRAFT)

    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    released_at = models.DateTimeField(null=True, blank=True)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # Most recent return remarks — shown prominently on the class grading
    # page while RETURNED; superseded (not cleared) by the next return.
    return_remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["class_offering", "period"], name="unique_sheet_per_class_period")
        ]

    def __str__(self):
        return f"{self.class_offering} — {self.get_period_display()} ({self.get_status_display()})"

    @property
    def is_editable(self):
        """Instructor can edit scores/items/components only in these two
        statuses — grading/views.py consults this via approvals.services."""
        return self.status in (GradeSheetStatus.DRAFT, GradeSheetStatus.RETURNED)

    @classmethod
    def get_or_create_draft(cls, class_offering, period=GradeSheetPeriod.FINAL):
        sheet, _ = cls.objects.get_or_create(class_offering=class_offering, period=period)
        return sheet


class GradeSheetEntry(TimeStampedModel):
    """A frozen snapshot of one student's grade, taken AT SUBMISSION time.
    Approved/released grades always read from here, never recomputed live
    — re-submitting (after a return) replaces the whole snapshot."""

    class Remarks(models.TextChoices):
        PASSED = "PASSED", "Passed"
        FAILED = "FAILED", "Failed"
        INC = "INC", "INC"
        DROPPED = "DROPPED", "Dropped"

    sheet = models.ForeignKey(GradeSheet, on_delete=models.CASCADE, related_name="entries")
    roster_entry = models.ForeignKey(ClassRosterEntry, on_delete=models.PROTECT, related_name="grade_sheet_entries")
    final_grade = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    remarks = models.CharField(max_length=10, choices=Remarks.choices)
    inc_reason = models.CharField(max_length=255, blank=True)
    # [{"name", "category", "weight", "earned", "possible", "grade"}, ...] —
    # earned/possible/grade stored as strings (Decimal isn't JSON-native).
    components_json = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["roster_entry__student__last_name", "roster_entry__student__first_name"]
        constraints = [models.UniqueConstraint(fields=["sheet", "roster_entry"], name="unique_entry_per_sheet")]

    def __str__(self):
        return f"{self.roster_entry.student} — {self.final_grade} ({self.remarks})"

    @property
    def is_corrected(self):
        return self.corrections.exists()


class GradeSheetTransition(TimeStampedModel):
    """Audit trail + the timeline shown on a sheet's review page. Also used
    (from_status == to_status) to log a grade correction against the sheet,
    since a correction doesn't itself change the sheet's status."""

    sheet = models.ForeignKey(GradeSheet, on_delete=models.CASCADE, related_name="transitions")
    from_status = models.CharField(max_length=10, choices=GradeSheetStatus.choices, blank=True)
    to_status = models.CharField(max_length=10, choices=GradeSheetStatus.choices, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.sheet}: {self.from_status} -> {self.to_status}"


class GradeCorrection(TimeStampedModel):
    """Admin-only edit to one student's grade on a RELEASED/LOCKED sheet —
    always requires a reason, always logged (this row + a matching
    GradeSheetTransition on the sheet's timeline)."""

    entry = models.ForeignKey(GradeSheetEntry, on_delete=models.CASCADE, related_name="corrections")
    old_grade = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    new_grade = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    old_remarks = models.CharField(max_length=10, blank=True)
    new_remarks = models.CharField(max_length=10, blank=True)
    reason = models.TextField()
    corrected_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Correction: {self.entry} ({self.old_grade} -> {self.new_grade})"
