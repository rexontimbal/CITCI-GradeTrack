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


class ComponentCategory(models.TextChoices):
    """What a component actually measures — independent of its (instructor-
    chosen) display name, e.g. a renamed "Participation" component is still
    category=ATTENDANCE. Forecasting (a later phase) keys off this, not the
    free-text name, since instructors can name components however they like."""

    ATTENDANCE = "ATTENDANCE", "Attendance"
    QUIZ = "QUIZ", "Quiz"
    RECITATION = "RECITATION", "Recitation"
    PROJECT = "PROJECT", "Project / Performance Task"
    EXAM = "EXAM", "Exam"
    OTHER = "OTHER", "Other"


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
        return sum(c.weight for c in self.components.all())

    @property
    def locked_weight_total(self):
        return sum(c.weight for c in self.components.filter(is_locked=True))

    @property
    def instructor_share(self):
        """100 minus the locked (school-fixed) weight — what's left for an
        instructor to distribute across their own class's unlocked components."""
        return 100 - self.locked_weight_total


class GradingComponent(TimeStampedModel):
    template = models.ForeignKey(GradingTemplate, on_delete=models.CASCADE, related_name="components")
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=12, choices=ComponentCategory.choices, default=ComponentCategory.OTHER)
    weight = models.PositiveIntegerField(help_text="Whole-number percent, e.g. 30 for 30%.")
    is_locked = models.BooleanField(
        default=False,
        help_text="School-fixed weight (e.g. Examination 40%). Instructors can't rename, recategorize, or "
        "reweight a locked component in their class, only the unlocked ones.",
    )
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
        weight_total = sum(c.weight for c in template.components.all())
        if weight_total != 100:
            raise ValidationError(
                f"'{template}' components total {weight_total}%, not 100%. Fix the template before using it."
            )
        scheme, _ = cls.objects.update_or_create(
            class_offering=class_offering, defaults={"source_template": template}
        )
        scheme.components.all().delete()
        for component in template.components.all():
            SchemeComponent.objects.create(
                scheme=scheme,
                name=component.name,
                category=component.category,
                weight=component.weight,
                is_locked=component.is_locked,
                order=component.order,
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
    the time the scheme was created/re-applied — then independently
    customizable per class for the unlocked ones (CITCI policy: the
    Examination weight is fixed by the school; every other component and its
    weight is up to each instructor for their own class)."""

    scheme = models.ForeignKey(ClassGradingScheme, on_delete=models.CASCADE, related_name="components")
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=12, choices=ComponentCategory.choices, default=ComponentCategory.OTHER)
    weight = models.PositiveIntegerField(help_text="Whole-number percent, e.g. 30 for 30%.")
    is_locked = models.BooleanField(
        default=False, help_text="School-fixed: this instructor can't rename/recategorize/reweight it."
    )
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.name} ({self.weight}%)"

    @property
    def has_scored_items(self):
        return self.items.filter(scores__score__isnull=False).exists()


class AssessmentItem(TimeStampedModel):
    """A single gradeable item within a component, e.g. "Quiz 1" (Quizzes
    component, Prelim term, max 20)."""

    class_offering = models.ForeignKey(ClassOffering, on_delete=models.CASCADE, related_name="assessment_items")
    component = models.ForeignKey(SchemeComponent, on_delete=models.PROTECT, related_name="items")
    title = models.CharField(max_length=100)
    max_score = models.PositiveIntegerField(help_text="Whole numbers only. Matches CITCI's class record.")
    term = models.CharField(
        max_length=10,
        choices=AssessmentTerm.choices,
        help_text="Grading period this item belongs to. Also drives forecasting checkpoints later.",
    )
    date = models.DateField(null=True, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["component__order", "order", "id"]

    def clean(self):
        if self.max_score is not None and self.max_score < 1:
            raise ValidationError("Max score must be at least 1.")

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
    score = models.PositiveIntegerField(null=True, blank=True, help_text="Whole numbers only.")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=["roster_entry", "item"], name="unique_score_per_item")]

    def clean(self):
        if self.score is not None and self.item_id and (self.score < 0 or self.score > self.item.max_score):
            raise ValidationError(f"Max is {self.item.max_score}")

    def __str__(self):
        return f"{self.roster_entry.student} · {self.item}: {self.score if self.score is not None else 'Not set'}"


class SchemeComponentChangeLog(models.Model):
    """Audit trail for instructor edits to a class's grading components
    (add/edit/delete) — shown in the Setup tab's "Change history" panel.
    Kept even after the component itself is deleted, so `component` is a
    plain name snapshot rather than a FK."""

    class Action(models.TextChoices):
        ADDED = "ADDED", "Added"
        EDITED = "EDITED", "Edited"
        DELETED = "DELETED", "Deleted"

    scheme = models.ForeignKey(ClassGradingScheme, on_delete=models.CASCADE, related_name="component_change_logs")
    action = models.CharField(max_length=10, choices=Action.choices)
    component_name = models.CharField(max_length=100)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at"]

    def __str__(self):
        return f"{self.get_action_display()} {self.component_name} ({self.scheme})"


class ScoreChangeLog(models.Model):
    """Audit trail written on every Score change — will matter once grade
    sheets go through the approval workflow in a later phase."""

    score = models.ForeignKey(Score, on_delete=models.CASCADE, related_name="change_logs")
    old_value = models.PositiveIntegerField(null=True, blank=True)
    new_value = models.PositiveIntegerField(null=True, blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at"]

    def __str__(self):
        return f"{self.score} : {self.old_value} -> {self.new_value}"
