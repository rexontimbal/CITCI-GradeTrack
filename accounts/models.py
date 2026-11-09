from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models

from core.models import TimeStampedModel


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

    @property
    def program_head_scope_label(self):
        """"BSED – English, BSED – Social Studies" / "BSIT (all majors)" —
        formats academics.scoping.scope_for(self) for display (Users page,
        Program Head dashboard). Empty string for anyone not a Program
        Head, or one with no assignment yet. Lazy import — academics
        depends on accounts, not the other way around."""
        if not self.is_program_head:
            return ""
        from academics.models import Program
        from academics.scoping import scope_for

        scope = scope_for(self)
        if not scope:
            return "Unassigned"
        programs = {p.id: p for p in Program.objects.filter(pk__in={program_id for program_id, _ in scope})}
        labels = []
        for program_id, major_id in sorted(scope, key=lambda t: (t[0], t[1] or 0)):
            program = programs.get(program_id)
            if program is None:
                continue
            if major_id is None:
                labels.append(f"{program.code} (all majors)")
            else:
                major = next((m for m in program.majors.all() if m.id == major_id), None)
                labels.append(f"{program.code} – {major.name}" if major else program.code)
        return ", ".join(labels)

    def __str__(self):
        return f"{self.full_name} ({self.get_role_display()})"


class AuditLog(TimeStampedModel):
    """Account-management + login-security events (Phase 8 part A). One row
    per event — `actor` is who did it (null for a system/axes-originated
    event like a lockout), `target_user` is who it was done to. `details`
    is a small JSON dict of non-personal context (e.g. {"role": "INSTRUCTOR"}
    for a role change, {"ip_address": "..."} for a lockout) — never a name,
    ID number, or password.

    This is intentionally separate from the per-domain change logs
    (grading.ScoreChangeLog, grading.SchemeComponentChangeLog,
    approvals.GradeSheetTransition/GradeCorrection) rather than a single
    shared table — those already exist with their own FKs into their own
    domain models; the admin Audit Log page (accounts/audit.py) reads all
    of them and normalizes into one combined, filterable view instead of
    forcing a schema migration onto working code."""

    class Action(models.TextChoices):
        USER_CREATED = "USER_CREATED", "User created"
        USER_UPDATED = "USER_UPDATED", "User updated"
        USER_DEACTIVATED = "USER_DEACTIVATED", "User deactivated"
        USER_REACTIVATED = "USER_REACTIVATED", "User reactivated"
        PASSWORD_RESET = "PASSWORD_RESET", "Password reset"
        ACCOUNT_UNLOCKED = "ACCOUNT_UNLOCKED", "Account unlocked (admin)"
        ACCOUNT_LOCKED_OUT = "ACCOUNT_LOCKED_OUT", "Account locked out (too many failed logins)"
        ACADEMIC_YEAR_WIZARD_RUN = "ACADEMIC_YEAR_WIZARD_RUN", "New Academic Year wizard run"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    action = models.CharField(max_length=30, choices=Action.choices)
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_action_display()} — {self.target_user} ({self.created_at:%Y-%m-%d %H:%M})"
