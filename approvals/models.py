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
    # Snapshot taken AT SUBMISSION time (never retroactively recomputed if
    # the semester's deadline changes later) — a resubmit after RETURNED
    # recomputes it fresh, consistent with "resubmitting replaces the
    # whole snapshot" elsewhere on this model.
    is_late = models.BooleanField(default=False)
    # De-dup for the 3-day-before-deadline reminder (send_reminders) — set
    # once and never cleared; a deadline doesn't recur, so there's no
    # "episode" concept to reset it for, unlike forecasting's notified_at
    # fields.
    reminder_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["class_offering", "period"], name="unique_sheet_per_class_period")
        ]

    def __str__(self):
        return f"{self.class_offering} · {self.get_period_display()} ({self.get_status_display()})"

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
        constraints = [
            models.UniqueConstraint(fields=["sheet", "roster_entry"], name="unique_entry_per_sheet"),
            # Belt-and-suspenders against grading.services' provisional
            # ON_TRACK/AT_RISK labels ever landing in a frozen snapshot —
            # choices= alone doesn't stop a bare .create()/.save() that
            # skips full_clean(), which is exactly how this bug happened.
            models.CheckConstraint(
                check=models.Q(remarks__in=["PASSED", "FAILED", "INC", "DROPPED"]),
                name="valid_grade_sheet_entry_remarks",
            ),
        ]

    def __str__(self):
        return f"{self.roster_entry.student} · {self.final_grade} ({self.remarks})"

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


class IncCompletionStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"


class IncCompletion(TimeStampedModel):
    """An instructor's request to resolve an INC entry on a RELEASED/LOCKED
    sheet — PENDING until the Program Head approves/rejects. "Completed
    INC" is never a stored flag on GradeSheetEntry (its remarks column is
    DB-constrained to PASSED/FAILED/INC/DROPPED) — it's derived at display
    time from `entry.inc_completions.filter(status=APPROVED).exists()`,
    the same philosophy as forecasting.services.risk_level. Approval
    reuses approvals.services.correct_grade verbatim, so the
    GradeCorrection/GradeSheetTransition/notifications are identical to an
    admin-filed correction."""

    entry = models.ForeignKey(GradeSheetEntry, on_delete=models.CASCADE, related_name="inc_completions")
    filed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    new_grade = models.DecimalField(max_digits=4, decimal_places=2)
    new_remarks = models.CharField(
        max_length=10,
        choices=[(GradeSheetEntry.Remarks.PASSED, "Passed"), (GradeSheetEntry.Remarks.FAILED, "Failed")],
        help_text="An INC completion always resolves to Passed or Failed. It never resolves back to INC/Dropped.",
    )
    date_complied = models.DateField()
    remarks_text = models.TextField(blank=True, help_text="Instructor's notes filing the completion.")
    status = models.CharField(max_length=10, choices=IncCompletionStatus.choices, default=IncCompletionStatus.PENDING)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_remarks = models.TextField(blank=True, help_text="Required on rejection.")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"INC completion for {self.entry.roster_entry.student} ({self.get_status_display()})"
