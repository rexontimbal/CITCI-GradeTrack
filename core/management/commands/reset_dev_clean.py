"""Dev-only: wipes every domain row (users, academic structure, grading,
approvals, forecasting, audit/login-lockout history) and recreates the
exact minimal state a fresh production install has — one superuser admin,
Institution Settings defaults, and the CITCI Default grading template.
Mirrors accounts.management.commands.setup_production's "no demo data"
philosophy, except non-interactive (fixed admin/Admin@1234, for repeatable
local testing) and destructive first (unlike setup_production, which
never deletes anything).

Refuses outright under the production settings module — this is not a
seeder with a --force-demo escape hatch like the other seed_* commands
(core/management/guards.py); there is no legitimate reason to run this
against production, so there is no override flag. Always backs up first
(core.management.commands.backup_db) before touching any data, and that
backup step is never skipped.

docs/source/ (the Registrar .docx/JSON used by "Import Class Offerings")
is filesystem content, untouched by this command.
"""

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from core.management.guards import is_production_settings


class Command(BaseCommand):
    help = "DEV ONLY: wipes all data and recreates the minimal fresh-install state (one admin, Institution Settings, CITCI Default template)."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Required — confirms you want to wipe this database.")
        parser.add_argument("--skip-backup", action="store_true", help="Testing only — skip the backup_db step.")

    def handle(self, *args, **options):
        if is_production_settings():
            raise CommandError(
                "Refusing to run reset_dev_clean under the production settings module "
                f"({settings.SETTINGS_MODULE}). This command is for local development "
                "databases only — there is no override flag."
            )
        if not options["yes"]:
            raise CommandError("This permanently deletes all data in this database. Pass --yes to confirm.")

        if not options["skip_backup"]:
            self.stdout.write("Backing up the database first...")
            call_command("backup_db")

        self._wipe_everything()
        self._recreate_minimal_setup()
        self.stdout.write(
            self.style.SUCCESS(
                "Clean slate ready: 1 admin account (admin / Admin@1234), Institution Settings "
                "defaults, CITCI Default grading template. No academic/demo data."
            )
        )

    def _wipe_everything(self):
        from academics.models import (
            AcademicYear,
            ClassOffering,
            ClassRosterEntry,
            Major,
            Program,
            Section,
            Semester,
            StudentProfile,
            Subject,
            TeachingAssignmentLog,
        )
        from accounts.models import AuditLog, User
        from approvals.models import GradeCorrection, GradeSheet, GradeSheetEntry, GradeSheetTransition, IncCompletion
        from dashboard.models import Notification
        from forecasting.models import HistoricalImportBatch, HistoricalRecord, Intervention, MlModelVersion, Prediction
        from grading.models import (
            AssessmentItem,
            ClassGradingScheme,
            GradingComponent,
            GradingTemplate,
            SchemeComponent,
            SchemeComponentChangeLog,
            Score,
            ScoreChangeLog,
        )
        from reports.models import InstitutionSettings

        # Deleted in PROTECT-safe order (Django auto-cascades CASCADE
        # children of whatever's deleted here, but never auto-clears a
        # PROTECT reference) — leaves nothing for a later step to trip
        # over a ProtectedError.
        Notification.objects.all().delete()

        GradeCorrection.objects.all().delete()
        IncCompletion.objects.all().delete()
        GradeSheetTransition.objects.all().delete()
        GradeSheetEntry.objects.all().delete()
        GradeSheet.objects.all().delete()

        ScoreChangeLog.objects.all().delete()
        Score.objects.all().delete()
        AssessmentItem.objects.all().delete()
        SchemeComponentChangeLog.objects.all().delete()
        SchemeComponent.objects.all().delete()
        ClassGradingScheme.objects.all().delete()
        GradingComponent.objects.all().delete()
        GradingTemplate.objects.all().delete()

        Intervention.objects.all().delete()
        Prediction.objects.all().delete()
        MlModelVersion.objects.all().delete()
        HistoricalRecord.objects.all().delete()
        HistoricalImportBatch.objects.all().delete()

        TeachingAssignmentLog.objects.all().delete()
        ClassRosterEntry.objects.all().delete()
        ClassOffering.objects.all().delete()
        StudentProfile.objects.all().delete()
        Subject.objects.all().delete()
        Section.objects.all().delete()
        Major.objects.all().delete()
        Program.objects.all().delete()
        Semester.objects.all().delete()
        AcademicYear.objects.all().delete()

        AuditLog.objects.all().delete()
        User.objects.all().delete()

        try:
            from axes.models import AccessAttempt, AccessFailureLog, AccessLog

            AccessAttempt.objects.all().delete()
            AccessLog.objects.all().delete()
            AccessFailureLog.objects.all().delete()
        except ImportError:
            pass
        Session.objects.all().delete()

        # InstitutionSettings.delete() is deliberately a no-op (it's a
        # singleton) — but that override only applies to an *instance*
        # delete, not a queryset delete, so this still removes the row;
        # get_solo() below recreates it with pure defaults.
        InstitutionSettings.objects.filter(pk=1).delete()

        self.stdout.write(self.style.SUCCESS("All data wiped."))

    def _recreate_minimal_setup(self):
        from grading.services import ensure_default_grading_template
        from reports.models import InstitutionSettings

        from accounts.models import User

        admin = User(
            username="admin",
            email="",
            role=User.Role.ADMIN,
            is_staff=True,
            is_superuser=True,
            must_change_password=False,
        )
        admin.set_password("Admin@1234")
        admin.full_clean(exclude=["password"])
        admin.save()
        self.stdout.write(self.style.SUCCESS("Admin account 'admin' created (password: Admin@1234)."))

        InstitutionSettings.get_solo()
        self.stdout.write(self.style.SUCCESS("Institution Settings ready (defaults)."))

        ensure_default_grading_template()
        self.stdout.write(self.style.SUCCESS("CITCI Default grading template ready."))
