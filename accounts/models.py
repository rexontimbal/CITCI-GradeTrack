from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """CITCI GradeTrack user. `username` doubles as login for staff; students
    typically log in with their student number or email (both stored on the
    account — see id_number / email)."""

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        PROGRAM_HEAD = "PROGRAM_HEAD", "Program Head"
        INSTRUCTOR = "INSTRUCTOR", "Instructor"
        STUDENT = "STUDENT", "Student"

    role = models.CharField(max_length=20, choices=Role.choices)
    middle_name = models.CharField(max_length=150, blank=True)
    id_number = models.CharField(
        max_length=30,
        unique=True,
        null=True,
        blank=True,
        help_text="Student number or employee number.",
    )
    must_change_password = models.BooleanField(default=True)
    privacy_consent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the user acknowledged the Data Privacy notice (RA 10173).",
    )

    @property
    def is_admin_role(self):
        return self.role == self.Role.ADMIN

    @property
    def is_program_head(self):
        return self.role == self.Role.PROGRAM_HEAD

    @property
    def is_instructor(self):
        return self.role == self.Role.INSTRUCTOR

    @property
    def is_student(self):
        return self.role == self.Role.STUDENT

    @property
    def full_name(self):
        parts = [self.first_name, self.middle_name, self.last_name]
        return " ".join(p for p in parts if p) or self.username

    @property
    def initials(self):
        letters = (self.first_name[:1] + self.last_name[:1]).upper()
        return letters or self.username[:2].upper()

    def __str__(self):
        return f"{self.full_name} ({self.get_role_display()})"
