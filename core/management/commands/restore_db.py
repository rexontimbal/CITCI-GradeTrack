"""Restores the database from a pg_dump custom-format backup created by
backup_db. DESTRUCTIVE — overwrites the current database — so it refuses to
run without an explicit --yes-i-am-sure flag. Phase 8 part A.
"""

import os
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Restores the database from a backup_db .dump file. DESTRUCTIVE — overwrites the current database."

    def add_arguments(self, parser):
        parser.add_argument("dump_file", help="Path to a .dump file created by backup_db.")
        parser.add_argument(
            "--yes-i-am-sure",
            action="store_true",
            help="Required. Confirms you understand this OVERWRITES the current database.",
        )
        parser.add_argument(
            "--pg-restore",
            default=None,
            help="Path to the pg_restore executable (default: PG_RESTORE_PATH env var, else 'pg_restore' on PATH).",
        )

    def handle(self, *args, **options):
        if not options["yes_i_am_sure"]:
            raise CommandError(
                "Refusing to restore without --yes-i-am-sure — this OVERWRITES the current database "
                "with the contents of the backup file."
            )

        dump_file = Path(options["dump_file"])
        if not dump_file.exists():
            raise CommandError(f"{dump_file} not found.")

        db = settings.DATABASES["default"]
        pg_restore = options["pg_restore"] or os.environ.get("PG_RESTORE_PATH", "pg_restore")

        cmd = [
            pg_restore,
            "--clean",
            "--if-exists",
            "-h", db.get("HOST") or "localhost",
            "-p", str(db.get("PORT") or 5432),
            "-U", db.get("USER") or "",
            "-d", db.get("NAME") or "",
            str(dump_file),
        ]
        env = os.environ.copy()
        if db.get("PASSWORD"):
            env["PGPASSWORD"] = db["PASSWORD"]

        self.stdout.write(f"Running: {' '.join(str(c) for c in cmd)}")
        result = self._run(cmd, env)
        if result.returncode != 0:
            raise CommandError(f"pg_restore failed (exit {result.returncode}): {result.stderr}")

        self.stdout.write(self.style.SUCCESS(f"Restored database from {dump_file.name}."))
        self.stdout.write(
            self.style.WARNING(
                "If the backup included a media/ copy, restore it by hand into MEDIA_ROOT "
                f"({settings.MEDIA_ROOT}) — this command only restores the database."
            )
        )

    def _run(self, cmd, env):
        """Isolated so tests can mock subprocess without a real pg_restore."""
        return subprocess.run(cmd, env=env, capture_output=True, text=True)
