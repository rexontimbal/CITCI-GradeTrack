from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction

from academics.models import ClassOffering, ClassRosterEntry
from core.models import TimeStampedModel


class AssessmentTerm(models.TextChoices):
    """The four grading periods on CITCI's actual class record (grading-system.xlsx)
    — not to be confused with academics.Term (1st Sem / 2nd Sem / Summer)."""

    PRELIM = "PRELIM", "Prelim"
    MIDTERM = "MIDTERM", "Midterm"
    SEMIFINAL = "SEMIFINAL", "Semi-Final"
    FINAL = "FINAL", "Final"


# Display/sort order for the four terms above — used wherever a breakdown
# needs to be grouped or sorted chronologically instead of alphabetically.
ASSESSMENT_TERM_ORDER = {
    AssessmentTerm.PRELIM: 0,
    AssessmentTerm.MIDTERM: 1,
    AssessmentTerm.SEMIFINAL: 2,
    AssessmentTerm.FINAL: 3,
}


class GradingTemplate(TimeStampedModel):
    """A reusable set of grading components (e.g. "CITCI Default": Attendance
    5%, Quizzes 30%, Recitation 15%, Project 10%, Examination 40%). Classes
    never reference this directly — they get a frozen copy, see
    ClassGradingScheme — so editing a template never changes grades already
    in progress."""

    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-is_default", "name"]

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.is_default:
                GradingTemplate.objects.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)
            super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    @property
    def weight_total(self):
        return sum((c.weight for c in self.components.all()), Decimal("0"))


class GradingComponent(TimeStampedModel):
    template = models.ForeignKey(GradingTemplate, on_delete=models.CASCADE, related_name="components")
    name = models.CharField(max_length=100)
    weight = models.DecimalField(max_digits=5, decimal_places=2, help_text="Percent, e.g. 30.00 for 30%.")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["template", "name"], name="unique_component_name_per_template")
        ]

    def __str__(self):
        return f"{self.name} ({self.weight}%)"


class ClassGradingScheme(TimeStampedModel):
    """One per ClassOffering — a snapshot copy of a template's components at
    the moment it is applied, so later edits to the source template never
    change a class's existing grades. Auto-created with the default template
    the first time anyone opens a class's grading page."""

    class_offering = models.OneToOneField(ClassOffering, on_delete=models.CASCADE, related_name="grading_scheme")
    source_template = models.ForeignKey(
        GradingTemplate, on_delete=models.PROTECT, null=True, blank=True, related_name="class_schemes"
    )

    def __str__(self):
        return f"Grading scheme for {self.class_offering}"

    @classmethod
    def apply_template(cls, class_offering, template):
        """(Re)snapshot `template`'s current components onto this class. Only
        safe to call when the class has no scores yet — see
        ClassGradingSchemeForm for the "can't change template once scores
        exist" rule."""
        weight_total = sum((c.weight for c in template.components.all()), Decimal("0"))
        if weight_total != Decimal("100"):
            raise ValidationError(
                f"'{template}' components total {weight_total}%, not 100% — fix the template before using it."
            )
        scheme, _ = cls.objects.update_or_create(
            class_offering=class_offering, defaults={"source_template": template}
        )
        scheme.components.all().delete()
        for component in template.components.all():
            SchemeComponent.objects.create(
                scheme=scheme, name=component.name, weight=component.weight, order=component.order
            )
        return scheme

    @classmethod
    def get_or_create_default(cls, class_offering):
        try:
            return class_offering.grading_scheme
        except cls.DoesNotExist:
            template = (
                GradingTemplate.objects.filter(is_default=True, is_active=True).first()
                or GradingTemplate.objects.filter(is_active=True).order_by("name").first()
            )
            if not template:
                raise ValidationError("No active grading template exists to apply to this class.")
            return cls.apply_template(class_offering, template)

    @property
    def has_scores(self):
        return Score.objects.filter(item__component__scheme=self, score__isnull=False).exists()


class SchemeComponent(TimeStampedModel):
    """A component row copied from a GradingTemplate's GradingComponent at
    the time the scheme was created/re-applied."""

    scheme = models.ForeignKey(ClassGradingScheme, on_delete=models.CASCADE, related_name="components")
    name = models.CharField(max_length=100)
    weight = models.DecimalField(max_digits=5, decimal_places=2)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.name} ({self.weight}%)"


class AssessmentItem(TimeStampedModel):
    """A single gradeable item within a component, e.g. "Quiz 1" (Quizzes
    component, Prelim term, max 20)."""

    class_offering = models.ForeignKey(ClassOffering, on_delete=models.CASCADE, related_name="assessment_items")
    component = models.ForeignKey(SchemeComponent, on_delete=models.PROTECT, related_name="items")
    title = models.CharField(max_length=100)
    max_score = models.DecimalField(max_digits=6, decimal_places=2)
    term = models.CharField(
        max_length=10,
        choices=AssessmentTerm.choices,
        help_text="Grading period this item belongs to — also drives forecasting checkpoints later.",
    )
    date = models.DateField(null=True, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["component__order", "order", "id"]

    def clean(self):
        if self.max_score is not None and self.max_score <= 0:
            raise ValidationError("Max score must be greater than zero.")

    @property
    def has_scores(self):
        return self.scores.filter(score__isnull=False).exists()

    def __str__(self):
        return f"{self.title} ({self.get_term_display()}, /{self.max_score})"


class Score(TimeStampedModel):
    """A student's score on one assessment item. A null `score` means "not
    yet encoded" — distinct from a zero score."""

    roster_entry = models.ForeignKey(ClassRosterEntry, on_delete=models.CASCADE, related_name="scores")
    item = models.ForeignKey(AssessmentItem, on_delete=models.CASCADE, related_name="scores")
    score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=["roster_entry", "item"], name="unique_score_per_item")]

    def clean(self):
        if self.score is not None and self.item_id and (self.score < 0 or self.score > self.item.max_score):
            raise ValidationError(f"Max is {self.item.max_score}")

    def __str__(self):
        return f"{self.roster_entry.student} – {self.item}: {self.score if self.score is not None else '—'}"


class ScoreChangeLog(models.Model):
    """Audit trail written on every Score change — will matter once grade
    sheets go through the approval workflow in a later phase."""

    score = models.ForeignKey(Score, on_delete=models.CASCADE, related_name="change_logs")
    old_value = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    new_value = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at"]

    def __str__(self):
        return f"{self.score} : {self.old_value} -> {self.new_value}"
