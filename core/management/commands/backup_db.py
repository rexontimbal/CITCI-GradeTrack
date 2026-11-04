"""Backs up the database (pg_dump, custom format) and a copy of MEDIA_ROOT
to BACKUP_DIR, then prunes anything beyond the last BACKUP_KEEP backups.
Phase 8 part A — see docs/DEPLOYMENT.md "Backups" for scheduling examples
(Windows Task Scheduler / cron).
"""

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Dumps the database (pg_dump -Fc) and copies MEDIA_ROOT into BACKUP_DIR; prunes old backups beyond BACKUP_KEEP."

    def add_arguments(self, parser):
        parser.add_argument(
            "--pg-dump",
            default=None,
            help="Path to the pg_dump executable (default: PG_DUMP_PATH env var, else 'pg_dump' on PATH).",
        )

    def handle(self, *args, **options):
        backup_dir = Path(settings.BACKUP_DIR)
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        db = settings.DATABASES["default"]
        pg_dump = options["pg_dump"] or os.environ.get("PG_DUMP_PATH", "pg_dump")

        dump_path = backup_dir / f"citci_gradetrack_{timestamp}.dump"
        cmd = [
            pg_dump,
            "-Fc",
            "-h", db.get("HOST") or "localhost",
            "-p", str(db.get("PORT") or 5432),
            "-U", db.get("USER") or "",
            "-f", str(dump_path),
            db.get("NAME") or "",
        ]
        env = os.environ.copy()
        if db.get("PASSWORD"):
            env["PGPASSWORD"] = db["PASSWORD"]

        self.stdout.write(f"Running: {' '.join(str(c) for c in cmd)}")
        result = self._run(cmd, env)
        if result.returncode != 0:
            raise CommandError(f"pg_dump failed (exit {result.returncode}): {result.stderr}")

        media_root = Path(settings.MEDIA_ROOT)
        if media_root.exists():
            media_backup_dir = backup_dir / f"media_{timestamp}"
            shutil.copytree(media_root, media_backup_dir)
            self.stdout.write(f"Copied media/ to {media_backup_dir.name}")

        removed = self._prune(backup_dir)
        if removed:
            self.stdout.write(f"Pruned {removed} backup(s) beyond the last {settings.BACKUP_KEEP}.")

        self.stdout.write(self.style.SUCCESS(f"Backup complete: {dump_path.name}"))

    def _run(self, cmd, env):
        """Isolated so tests can mock subprocess without a real pg_dump."""
        return subprocess.run(cmd, env=env, capture_output=True, text=True)

    def _prune(self, backup_dir):
        keep = settings.BACKUP_KEEP
        removed = 0
        dumps = sorted(backup_dir.glob("citci_gradetrack_*.dump"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in dumps[keep:]:
            old.unlink()
            removed += 1
        media_dirs = sorted(backup_dir.glob("media_*"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in media_dirs[keep:]:
            shutil.rmtree(old, ignore_errors=True)
            removed += 1
        return removed
