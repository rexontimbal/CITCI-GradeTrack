"""Predicts for every active class-list entry at its class's CURRENT
checkpoint, fires early-warning notifications for new at-risk/watch
episodes, and sends one daily digest per program head summarizing new
at-risk students across their own programs. No task queue (CLAUDE.md
section 7 — Celery/Redis decided against; predictions are cheap enough to
run synchronously). Schedule this via Windows Task Scheduler / cron;
Phase 7's "after score save" and "Recompute" button both call the same
underlying primitive (forecasting.services.recompute_and_notify).
"""

from collections import defaultdict

from django.core.management.base import BaseCommand

from academics.models import ClassRosterEntry, Program
from dashboard.services import notify
from forecasting.services import recompute_and_notify


class Command(BaseCommand):
    help = "Refreshes forecasts for every active class-list entry and sends early-warning + program-head digest notifications."

    def handle(self, *args, **options):
        roster_entries = ClassRosterEntry.objects.filter(status=ClassRosterEntry.Status.ACTIVE).select_related(
            "class_offering__subject", "class_offering__instructor"
        )
        newly_at_risk = recompute_and_notify(roster_entries)

        by_program_head = defaultdict(set)
        for entry in newly_at_risk:
            programs = Program.objects.filter(
                sections__class_offerings=entry.class_offering, program_head__isnull=False
            ).distinct()
            for program in programs:
                by_program_head[program.program_head].add(entry.pk)

        for program_head, entry_ids in by_program_head.items():
            count = len(entry_ids)
            notify(
                program_head,
                "Daily at-risk summary",
                f"{count} student{'s' if count != 1 else ''} newly flagged as at risk in your program(s) today.",
                link="/forecasting/at-risk/",
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Forecasts refreshed: {len(newly_at_risk)} newly at-risk this run; "
                f"digests sent to {len(by_program_head)} program head(s)."
            )
        )
