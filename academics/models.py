from decimal import Decimal

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
        limit_choices_to={"role": User.Role.PROGRAM_HEAD},
        related_name="headed_programs",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.code


class Section(TimeStampedModel):
    program = models.ForeignKey(Program, on_delete=models.PROTECT, related_name="sections")
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="sections")
    year_level = models.PositiveSmallIntegerField(choices=YEAR_LEVEL_CHOICES)
    name = models.CharField(max_length=10)

    class Meta:
        ordering = ["program__code", "year_level", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["program", "academic_year", "year_level", "name"], name="unique_section"
            )
        ]

    def __str__(self):
        return f"{self.program.code} {self.year_level}-{self.name}"


class Subject(TimeStampedModel):
    code = models.CharField(max_length=20, unique=True)
    title = models.CharField(max_length=200)
    lec_units = models.DecimalField(max_digits=4, decimal_places=1, default=Decimal("0.0"))
    lab_units = models.DecimalField(max_digits=4, decimal_places=1, default=Decimal("0.0"))
    program = models.ForeignKey(
        Program,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="subjects",
        help_text="Leave blank for a general education subject.",
    )
    year_level = models.PositiveSmallIntegerField(choices=YEAR_LEVEL_CHOICES)
    term = models.CharField(max_length=10, choices=Term.choices, help_text="Recommended term.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    @property
    def total_units(self):
        return self.lec_units + self.lab_units

    def __str__(self):
        return self.code


class StudentProfile(TimeStampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={"role": User.Role.STUDENT},
        related_name="student_profile",
    )
    program = models.ForeignKey(
        Program, on_delete=models.PROTECT, null=True, blank=True, related_name="student_profiles"
    )
    year_level = models.PositiveSmallIntegerField(choices=YEAR_LEVEL_CHOICES, null=True, blank=True)
    section = models.ForeignKey(
        Section, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_profiles"
    )

    def __str__(self):
        return self.user.full_name


class ClassOffering(TimeStampedModel):
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="class_offerings")
    section = models.ForeignKey(Section, on_delete=models.PROTECT, related_name="class_offerings")
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
        constraints = [
            models.UniqueConstraint(fields=["subject", "section", "semester"], name="unique_class_offering")
        ]

    def clean(self):
        if self.section_id and self.semester_id and self.section.academic_year_id != self.semester.academic_year_id:
            raise ValidationError("The section's academic year must match the semester's academic year.")

    @property
    def enrolled_count(self):
        return self.enrollments.filter(status=Enrollment.Status.ENROLLED).count()

    def __str__(self):
        return f"{self.subject.code} – {self.section}"


class Enrollment(TimeStampedModel):
    class Status(models.TextChoices):
        ENROLLED = "ENROLLED", "Enrolled"
        DROPPED = "DROPPED", "Dropped"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        limit_choices_to={"role": User.Role.STUDENT},
        related_name="enrollments",
    )
    class_offering = models.ForeignKey(ClassOffering, on_delete=models.PROTECT, related_name="enrollments")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ENROLLED)
    date_enrolled = models.DateField(auto_now_add=True)
    date_dropped = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["student__last_name", "student__first_name"]
        constraints = [
            models.UniqueConstraint(fields=["student", "class_offering"], name="unique_enrollment")
        ]

    def __str__(self):
        return f"{self.student.full_name} – {self.class_offering}"
