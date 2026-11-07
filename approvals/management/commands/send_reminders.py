"""Reminds instructors with an unsubmitted grade sheet 3 days before their
semester's submission deadline. A separate command from forecasting's
run_forecasts — grade-submission deadlines are an approvals-domain
concern, not a forecasting one. No task queue (CLAUDE.md section 7);
schedule this via Windows Task Scheduler / cron, same as run_forecasts.

De-dup is per-sheet (GradeSheet.reminder_sent_at, set once and never
cleared — a deadline doesn't recur, unlike forecasting's episode-based
notified_at fields). A class with no GradeSheet row yet (never opened)
has nowhere to record "already reminded," so this command materializes
its DRAFT row via get_or_create_draft specifically so the de-dup field has
somewhere to live.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from academics.models import ClassOffering, Semester
from approvals.models import GradeSheet, GradeSheetPeriod, GradeSheetStatus
from dashboard.services import notify


class Command(BaseCommand):
    help = "Notifies instructors with unsubmitted grade sheets 3 days before their semester's submission deadline."

    def handle(self, *args, **options):
        semesters = Semester.objects.filter(is_active=True, submission_deadline__isnull=False)
        reminded = 0

        for semester in semesters:
            cutoff = semester.submission_deadline - timedelta(days=3)
            now = timezone.now()
            if not (cutoff <= now < semester.submission_deadline):
                continue

            classes = ClassOffering.objects.filter(semester=semester, instructor__isnull=False).select_related(
                "subject", "instructor"
            )
            for class_offering in classes:
                sheet = GradeSheet.get_or_create_draft(class_offering, GradeSheetPeriod.FINAL)
                if sheet.status not in (GradeSheetStatus.DRAFT, GradeSheetStatus.RETURNED):
                    continue  # already submitted
                if sheet.reminder_sent_at:
                    continue  # already reminded for this deadline

                notify(
                    class_offering.instructor,
                    "Grade submission deadline approaching",
                    f"{class_offering} is due {semester.submission_deadline:%b %d, %Y %H:%M} "
                    f"and hasn't been submitted yet.",
                    link=f"/grading/classes/{class_offering.pk}/",
                )
                sheet.reminder_sent_at = timezone.now()
                sheet.save(update_fields=["reminder_sent_at"])
                reminded += 1

        self.stdout.write(self.style.SUCCESS(f"Sent {reminded} deadline reminder(s)."))
