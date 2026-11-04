"""Shared guard for every demo/seed management command (Phase 8 part A):
refuse to run against the production settings module unless --force-demo is
explicitly passed — seeding fake students/instructors/grades onto a live
CITCI production database would be a serious mistake to make by habit (e.g.
running the same setup script you always run).

Deliberately checks the settings MODULE name, not settings.DEBUG: Django's
test runner always forces DEBUG=False for every test run regardless of the
settings module (so results don't depend on dev-only behavior) — using
DEBUG here would make this guard fire on every test that calls a seed
command, which is not what "production" means."""

from django.conf import settings
from django.core.management.base import CommandError


def is_production_settings():
    return settings.SETTINGS_MODULE.endswith(".prod")


def ensure_demo_allowed(force_demo):
    if not is_production_settings() or force_demo:
        return
    raise CommandError(
        "Refusing to seed demo data: running under the production settings module "
        f"({settings.SETTINGS_MODULE}). Pass --force-demo if you really want fake "
        "accounts/grades on this database."
    )


def add_force_demo_argument(parser):
    parser.add_argument(
        "--force-demo",
        action="store_true",
        help="Allow running this seeder even when DEBUG=False (production settings).",
    )
