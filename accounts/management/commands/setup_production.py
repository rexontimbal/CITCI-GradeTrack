"""First-run setup for a real (non-demo) CITCI GradeTrack deployment:
creates the first admin account, the Institution Settings singleton
(defaults — the admin edits the real school header/signatories afterward
via System → Settings), and the CITCI Default grading template. Deliberately
creates NO demo students/instructors/classes/grades — see the demo seeders
(seed_demo_users, seed_citci_academics, ...) for that, which all refuse to
run under DEBUG=False unless --force-demo is passed (see
core/management/guards.py).

Interactive by default (prompts for username/email/password like Django's
own createsuperuser); pass all three options for non-interactive use (e.g.
a deploy script or a test).
"""

import getpass

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User


class Command(BaseCommand):
    help = "First-run setup: creates the first admin account, Institution Settings, and the CITCI Default grading template. No demo data."

    def add_arguments(self, parser):
        parser.add_argument("--username", default=None)
        parser.add_argument("--email", default=None)
        parser.add_argument("--password", default=None, help="Omit to be prompted (recommended outside of scripts/tests).")

    def handle(self, *args, **options):
        from grading.services import ensure_default_grading_template
        from reports.models import InstitutionSettings

        if User.objects.filter(role=User.Role.ADMIN).exists():
            self.stdout.write(self.style.WARNING("An admin account already exists — skipping admin creation."))
        else:
            self._create_first_admin(options)

        InstitutionSettings.get_solo()
        self.stdout.write(self.style.SUCCESS("Institution Settings ready (edit the real school header/signatories in System -> Settings)."))

        ensure_default_grading_template()
        self.stdout.write(self.style.SUCCESS("CITCI Default grading template ready."))

        self.stdout.write(self.style.SUCCESS("First-run setup complete. No demo data was created."))

    def _create_first_admin(self, options):
        username = options["username"] or input("Admin username: ").strip()
        if not username:
            raise CommandError("Username is required.")
        if User.objects.filter(username=username).exists():
            raise CommandError(f"A user named '{username}' already exists.")

        email = options["email"]
        if email is None:
            email = input("Admin email (optional): ").strip()

        password = options["password"]
        if password is None:
            password = getpass.getpass("Admin password: ")
            confirm = getpass.getpass("Confirm password: ")
            if password != confirm:
                raise CommandError("Passwords did not match.")
        if not password:
            raise CommandError("Password is required.")

        user = User(
            username=username,
            email=email or "",
            role=User.Role.ADMIN,
            is_staff=True,
            is_superuser=True,
            must_change_password=False,
        )
        user.set_password(password)
        user.full_clean(exclude=["password"])
        user.save()
        self.stdout.write(self.style.SUCCESS(f"Admin account '{username}' created."))
