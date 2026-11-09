from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction

from accounts.models import User
from core.models import TimeStampedModel

YEAR_LEVEL_CHOICES = [
    (1, "1st Year"),
    (2, "2nd Year"),
    (3, "3rd Year"),
    (4, "4th Year"),
]


class Term(models.TextChoices):
    FIRST = "FIRST", "1st Sem"
    SECOND = "SECOND", "2nd Sem"
    SUMMER = "SUMMER", "Summer"


class AcademicYear(TimeStampedModel):
    start_year = models.PositiveIntegerField(unique=True)
    end_year = models.PositiveIntegerField(editable=False)

    class Meta:
        ordering = ["-start_year"]

    def clean(self):
        if self.start_year:
            self.end_year = self.start_year + 1

    def save(self, *args, **kwargs):
        self.end_year = self.start_year + 1
        super().save(*args, **kwargs)

    def __str__(self):
        return f"A.Y. {self.start_year}–{self.end_year}"


class Semester(TimeStampedModel):
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="semesters")
    term = models.CharField(max_length=10, choices=Term.choices)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=False)
    submission_deadline = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Grade sheets submitted after this are still accepted but flagged Late.",
    )

    class Meta:
        ordering = ["-academic_year__start_year", "term"]
        constraints = [
            models.UniqueConstraint(fields=["academic_year", "term"], name="unique_semester_per_year")
        ]

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.is_active:
                Semester.objects.exclude(pk=self.pk).filter(is_active=True).update(is_active=False)
            super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_term_display()}, {self.academic_year}"


class Program(TimeStampedModel):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=150)
    program_head = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"role": User.Role.PROGRAM_HEAD, "is_active": True},
        related_name="headed_programs",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.code


class Major(TimeStampedModel):
    """Optional specialization within a program (e.g. BSED-English,
    BSED-Social Studies). A program may have no majors at all (e.g. TCP)."""

    program = models.ForeignKey(Program, on_delete=models.PROTECT, related_name="majors")
    code = models.CharField(max_length=20, help_text="e.g. ENG, SS")
    name = models.CharField(max_length=150)
    program_head = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"role": User.Role.PROGRAM_HEAD, "is_active": True},
        related_name="headed_majors",
        help_text="Takes precedence over the program's own head for this one major. Leave blank "
        "for this major to be covered by the program-level head.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["program__code", "code"]
        constraints = [models.UniqueConstraint(fields=["program", "code"], name="unique_major_per_program")]

    def __str__(self):
        return f"{self.program.code}-{self.code}"


class Section(TimeStampedModel):
    program = models.ForeignKey(Program, on_delete=models.PROTECT, related_name="sections")
    major = models.ForeignKey(
        Major, on_delete=models.PROTECT, null=True, blank=True, related_name="sections"
    )
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="sections")
    year_level = models.PositiveSmallIntegerField(choices=YEAR_LEVEL_CHOICES, null=True, blank=True)
    name = models.CharField(max_length=10, blank=True)

    class Meta:
        ordering = ["program__code", "year_level", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["program", "major", "academic_year", "year_level", "name"], name="unique_section"
            )
        ]

    def __str__(self):
        label = f"{self.program.code}-{self.major.code}" if self.major else self.program.code
        if self.year_level:
            label += f" {self.year_level}"
        if self.name:
            label += f" {self.name}"
        return label


class Subject(TimeStampedModel):
    code = models.CharField(max_length=20, unique=True)
    title = models.CharField(max_length=200)
    units = models.DecimalField(max_digits=3, decimal_places=1)
    program = models.ForeignKey(
        Program,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="subjects",
        help_text="Leave blank for a subject shared across programs (most General Education / "
        "Professional Education subjects).",
    )
    major = models.ForeignKey(
        Major,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="subjects",
        help_text="Leave blank unless this subject belongs to one specific major.",
    )
    year_level = models.PositiveSmallIntegerField(choices=YEAR_LEVEL_CHOICES, null=True, blank=True)
    term = models.CharField(max_length=10, choices=Term.choices, help_text="Recommended term.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.code


class StudentProfile(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        COMPLETED = "COMPLETED", "Completed"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={"role": User.Role.STUDENT},
        related_name="student_profile",
    )
    program = models.ForeignKey(
        Program, on_delete=models.PROTECT, null=True, blank=True, related_name="student_profiles"
    )
    major = models.ForeignKey(
        Major, on_delete=models.PROTECT, null=True, blank=True, related_name="student_profiles"
    )
    year_level = models.PositiveSmallIntegerField(choices=YEAR_LEVEL_CHOICES, null=True, blank=True)
    section = models.ForeignKey(
        Section, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_profiles"
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ACTIVE,
        help_text="Set to Completed by the New Academic Year wizard for 4th-years/TCP finishers — "
        "the account stays loginable (historical grades remain visible), they just drop out of "
        "'currently enrolled' counts and pickers.",
    )

    def __str__(self):
        return self.user.full_name


class ClassOffering(TimeStampedModel):
    """A class as taught in a semester. Usually one section, but sometimes
    one class serves multiple sections at once (e.g. a General Education
    subject shared by two majors in the same year level) — same instructor,
    room, and schedule for all of them."""

    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="class_offerings")
    sections = models.ManyToManyField(Section, related_name="class_offerings")
    semester = models.ForeignKey(Semester, on_delete=models.PROTECT, related_name="class_offerings")
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"role": User.Role.INSTRUCTOR},
        related_name="class_offerings",
    )
    schedule = models.CharField(max_length=150, blank=True)
    room = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-semester__academic_year__start_year", "semester__term", "subject__code"]

    def clean(self):
        if self.semester_id and self.pk:
            mismatched = self.sections.exclude(academic_year_id=self.semester.academic_year_id)
            if mismatched.exists():
                raise ValidationError("Every section's academic year must match the semester's academic year.")

    @property
    def roster_count(self):
        return self.roster_entries.filter(status=ClassRosterEntry.Status.ACTIVE).count()

    def __str__(self):
        section_names = ", ".join(str(s) for s in self.sections.all())
        return f"{self.subject.code} – {section_names}" if section_names else self.subject.code


class ClassRosterEntry(TimeStampedModel):
    """The official class list for grading — who is on a class's roster,
    as imported/managed from the Registrar's enrollment records. CITCI
    GradeTrack does not handle enrollment itself; it only stores the
    resulting roster."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        DROPPED = "DROPPED", "Dropped"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        limit_choices_to={"role": User.Role.STUDENT},
        related_name="class_roster_entries",
    )
    class_offering = models.ForeignKey(ClassOffering, on_delete=models.PROTECT, related_name="roster_entries")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    date_added = models.DateField(auto_now_add=True)
    date_dropped = models.DateField(null=True, blank=True)
    is_incomplete = models.BooleanField(
        default=False, help_text="Instructor marks INC (Incomplete) for this class manually."
    )
    incomplete_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["student__last_name", "student__first_name"]
        constraints = [
            models.UniqueConstraint(fields=["student", "class_offering"], name="unique_class_roster_entry")
        ]

    def __str__(self):
        return f"{self.student.full_name} – {self.class_offering}"


class TeachingAssignmentLog(TimeStampedModel):
    """One row per instructor assignment/reassignment on a class — the
    per-domain change log the Audit Log page combines in (same pattern as
    grading.ScoreChangeLog), plus the source for a class's own small
    "Assignment history" list. Teaching loads are normally a Program
    Head's call (CITCI confirmed practice); `is_admin_override` marks a
    change made by an admin instead, through the admin Classes page."""

    class_offering = models.ForeignKey(ClassOffering, on_delete=models.CASCADE, related_name="assignment_logs")
    old_instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    new_instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    is_admin_override = models.BooleanField(default=False)
    reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        old = self.old_instructor.full_name if self.old_instructor else "Unassigned"
        new = self.new_instructor.full_name if self.new_instructor else "Unassigned"
        return f"{self.class_offering}: {old} → {new}"


class AcademicSetupChangeLog(TimeStampedModel):
    """One row per create/update/deactivate/reactivate on a Section,
    Subject, or ClassOffering (plus the shared-class SECTION_JOINED/
    SECTION_LEFT actions) — the Program Head academic-setup equivalent of
    TeachingAssignmentLog above. A single shared model rather than three
    per-domain ones: these three entities go through near-identical CRUD
    flows and need an identical audit shape (who/role/scope/admin-override/
    before-after), unlike ScoreChangeLog/TeachingAssignmentLog which each
    capture a genuinely different kind of value change.

    `object_id` is a plain integer, not a real FK, so a log row survives
    the object's own deletion; `object_repr` snapshots its str() at the
    time of the change for display once that's no longer possible to
    recompute. `program`/`major` record the *scope* the changed object
    belonged to at the time (SET_NULL — never blocks deleting a Program/
    Major years later)."""

    class ModelName(models.TextChoices):
        SECTION = "SECTION", "Section"
        SUBJECT = "SUBJECT", "Subject"
        CLASS = "CLASS", "Class"

    class Action(models.TextChoices):
        CREATED = "CREATED", "Created"
        UPDATED = "UPDATED", "Updated"
        DEACTIVATED = "DEACTIVATED", "Deactivated"
        REACTIVATED = "REACTIVATED", "Reactivated"
        SECTION_JOINED = "SECTION_JOINED", "Section joined"
        SECTION_LEFT = "SECTION_LEFT", "Section left"

    model_name = models.CharField(max_length=10, choices=ModelName.choices)
    object_id = models.PositiveIntegerField()
    object_repr = models.CharField(max_length=255)
    action = models.CharField(max_length=20, choices=Action.choices)
    program = models.ForeignKey(Program, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    major = models.ForeignKey(Major, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    is_admin_override = models.BooleanField(default=False)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_model_name_display()} {self.get_action_display()}: {self.object_repr}"
