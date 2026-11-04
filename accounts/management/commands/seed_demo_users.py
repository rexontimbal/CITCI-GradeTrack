from django.core.management.base import BaseCommand

from accounts.models import User
from core.management.guards import add_force_demo_argument, ensure_demo_allowed

DEMO_PASSWORD = "Demo@1234"

DEMO_USERS = [
    {
        "username": "admin",
        "first_name": "Ma. Theresa",
        "last_name": "Villanueva",
        "role": User.Role.ADMIN,
        "id_number": "EMP-0001",
        "email": "admin@citci.edu.ph",
        "is_staff": True,
        "is_superuser": True,
    },
    {
        "username": "program_head",
        "first_name": "Ramil",
        "last_name": "Ocampo",
        "role": User.Role.PROGRAM_HEAD,
        "id_number": "EMP-0002",
        "email": "program_head@citci.edu.ph",
    },
    {
        "username": "instructor",
        "first_name": "Jessa",
        "last_name": "Mansueto",
        "role": User.Role.INSTRUCTOR,
        "id_number": "EMP-0003",
        "email": "instructor@citci.edu.ph",
    },
    {
        "username": "student",
        "first_name": "Carlo",
        "last_name": "Dagohoy",
        "role": User.Role.STUDENT,
        "id_number": "2026-00123",
        "email": "student@citci.edu.ph",
    },
]


class Command(BaseCommand):
    help = "Creates (or updates) one demo account per role, all with password Demo@1234."

    def add_arguments(self, parser):
        add_force_demo_argument(parser)

    def handle(self, *args, **options):
        ensure_demo_allowed(options.get("force_demo"))
        for data in DEMO_USERS:
            username = data["username"]
            user, created = User.objects.update_or_create(
                username=username,
                defaults={
                    "first_name": data["first_name"],
                    "last_name": data["last_name"],
                    "role": data["role"],
                    "id_number": data["id_number"],
                    "email": data["email"],
                    "is_staff": data.get("is_staff", False),
                    "is_superuser": data.get("is_superuser", False),
                    "is_active": True,
                    "must_change_password": True,
                    "privacy_consent_at": None,
                },
            )
            user.set_password(DEMO_PASSWORD)
            user.save()
            verb = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f"{verb} {user.role} account: {username}"))

        self.stdout.write(self.style.SUCCESS(f"\nAll demo accounts use password: {DEMO_PASSWORD}"))
