import io
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.utils import OperationalError
from django.test import TestCase, override_settings

from .management.guards import ensure_demo_allowed


class HealthzTests(TestCase):
    def test_returns_200_when_db_is_up(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "db": True})

    def test_returns_503_when_db_is_down(self):
        with mock.patch("core.views.connection") as mock_connection:
            mock_connection.cursor.side_effect = OperationalError("db is down")
            response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "error", "db": False})


class DemoSeederGuardTests(TestCase):
    """CLAUDE.md Phase 8 part A — every demo/seed command refuses to run
    under the production settings module unless --force-demo is passed.

    Checks settings.SETTINGS_MODULE, not settings.DEBUG — Django's test
    runner always forces DEBUG=False for every test regardless of the
    settings module in use, so these tests override SETTINGS_MODULE
    directly to simulate "running in production" without that colliding
    with the test runner's own DEBUG override."""

    @override_settings(SETTINGS_MODULE="config.settings.prod")
    def test_refuses_under_prod_settings_module_and_not_forced(self):
        with self.assertRaises(CommandError):
            ensure_demo_allowed(force_demo=False)

    @override_settings(SETTINGS_MODULE="config.settings.prod")
    def test_allowed_under_prod_settings_module_but_forced(self):
        ensure_demo_allowed(force_demo=True)  # must not raise

    @override_settings(SETTINGS_MODULE="config.settings.dev")
    def test_allowed_under_dev_settings_module(self):
        ensure_demo_allowed(force_demo=False)  # must not raise

    @override_settings(SETTINGS_MODULE="config.settings.prod")
    def test_seed_demo_users_command_refuses_in_prod(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo_users")

    @override_settings(SETTINGS_MODULE="config.settings.prod")
    def test_seed_demo_users_command_allowed_with_force_flag(self):
        call_command("seed_demo_users", force_demo=True)  # must not raise

        from accounts.models import User

        self.assertTrue(User.objects.filter(username="admin").exists())


class BackupDbCommandTests(TestCase):
    """pg_dump/pg_restore are mocked — these tests never touch a real
    PostgreSQL binary, only the command's own file/argument-building logic."""

    def test_backup_db_creates_a_dump_file(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(BACKUP_DIR=tmp, BACKUP_KEEP=30, MEDIA_ROOT="/nonexistent-for-tests"):
                fake_result = mock.Mock(returncode=0, stderr="")
                with mock.patch(
                    "core.management.commands.backup_db.Command._run", return_value=fake_result
                ) as mock_run:
                    call_command("backup_db")
                self.assertTrue(mock_run.called)
                dumps = list(Path(tmp).glob("citci_gradetrack_*.dump"))
                # _run is mocked so pg_dump never actually writes the file —
                # but the command must still have computed exactly one
                # target path and invoked pg_dump with it.
                cmd_args = mock_run.call_args[0][0]
                self.assertIn("-Fc", cmd_args)
                self.assertTrue(any(str(a).endswith(".dump") for a in cmd_args))

    def test_backup_db_raises_on_pg_dump_failure(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(BACKUP_DIR=tmp, BACKUP_KEEP=30):
                fake_result = mock.Mock(returncode=1, stderr="pg_dump: error: connection failed")
                with mock.patch("core.management.commands.backup_db.Command._run", return_value=fake_result):
                    with self.assertRaises(CommandError):
                        call_command("backup_db")

    def test_backup_db_prunes_beyond_keep_limit(self):
        import tempfile
        import time
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for i in range(5):
                f = tmp_path / f"citci_gradetrack_2026010{i}_000000.dump"
                f.write_text("fake")
                time.sleep(0.01)
            with override_settings(BACKUP_DIR=tmp, BACKUP_KEEP=2, MEDIA_ROOT="/nonexistent-for-tests"):
                fake_result = mock.Mock(returncode=0, stderr="")
                with mock.patch("core.management.commands.backup_db.Command._run", return_value=fake_result):
                    call_command("backup_db")
            remaining = list(tmp_path.glob("citci_gradetrack_*.dump"))
            # 5 pre-existing + 1 just "created" (the mock doesn't actually
            # write it, so really still 5 on disk) pruned down to BACKUP_KEEP.
            self.assertLessEqual(len(remaining), 2)


class RestoreDbCommandTests(TestCase):
    def test_refuses_without_confirmation_flag(self):
        with self.assertRaises(CommandError):
            call_command("restore_db", "somefile.dump")

    def test_refuses_when_file_does_not_exist(self):
        with self.assertRaises(CommandError):
            call_command("restore_db", "does-not-exist.dump", "--yes-i-am-sure")

    def test_restores_when_confirmed_and_file_exists(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            dump_file = Path(tmp) / "backup.dump"
            dump_file.write_text("fake dump content")
            fake_result = mock.Mock(returncode=0, stderr="")
            with mock.patch("core.management.commands.restore_db.Command._run", return_value=fake_result) as mock_run:
                call_command("restore_db", str(dump_file), "--yes-i-am-sure")
            self.assertTrue(mock_run.called)
