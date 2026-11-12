"""Preview + commit logic for the "Import class list" feature. CITCI
GradeTrack doesn't handle enrollment — this just turns a Registrar-exported
spreadsheet (ID Number, Last Name, First Name, Middle Name) into roster
rows, matching existing students by ID number and flagging new ones.
File parsing itself is shared — see core.importing."""

from django.utils.crypto import get_random_string

from accounts.models import User
from core.importing import SpreadsheetImportError, get_cell, parse_spreadsheet_file  # noqa: F401 (re-exported)

from .models import ClassRosterEntry, SectionMembership, StudentProfile

REQUIRED_HEADERS = ["id number", "last name", "first name"]
OPTIONAL_HEADERS = ["middle name"]

# Backwards-compatible alias (this module used to raise its own exception type).
RosterImportError = SpreadsheetImportError


def parse_roster_file(uploaded_file):
    return parse_spreadsheet_file(uploaded_file, REQUIRED_HEADERS, OPTIONAL_HEADERS)


def build_preview(class_offering, index, data_rows):
    """Classifies every row as new / existing / already / invalid without
    writing anything to the database."""
    already_in_list = set(
        class_offering.roster_entries.values_list("student__id_number", flat=True)
    )
    preview = []

    for row_number, row in enumerate(data_rows, start=2):  # row 1 is the header
        if row is None or not any(row):
            continue

        id_number = get_cell(row, index, "id number")
        last_name = get_cell(row, index, "last name")
        first_name = get_cell(row, index, "first name")
        middle_name = get_cell(row, index, "middle name")

        entry = {
            "row_number": row_number,
            "id_number": id_number,
            "last_name": last_name,
            "first_name": first_name,
            "middle_name": middle_name,
        }

        if not id_number or not last_name or not first_name:
            entry["kind"] = "invalid"
            entry["reason"] = "Missing ID Number, Last Name, or First Name."
            preview.append(entry)
            continue

        if id_number in already_in_list:
            entry["kind"] = "already"
            preview.append(entry)
            continue

        existing_user = User.objects.filter(id_number=id_number, role=User.Role.STUDENT).first()
        entry["kind"] = "existing" if existing_user else "new"
        preview.append(entry)

    return preview


def commit_import(class_offering, rows, target_section):
    """Creates any missing student users + profiles, then adds everyone
    who isn't already on the roster. `rows` is the preview list (dicts with
    kind in {new, existing, already, invalid})."""
    created_users = 0
    added_to_roster = 0

    for row in rows:
        if row["kind"] not in ("new", "existing"):
            continue

        user = User.objects.filter(id_number=row["id_number"], role=User.Role.STUDENT).first()
        if user is None:
            username = row["id_number"]
            user = User.objects.create_user(
                username=username,
                password=get_random_string(16),
                role=User.Role.STUDENT,
                id_number=row["id_number"],
                first_name=row["first_name"],
                last_name=row["last_name"],
                middle_name=row["middle_name"],
            )
            user.must_change_password = True
            user.save(update_fields=["must_change_password"])
            created_users += 1

        StudentProfile.objects.update_or_create(
            user=user,
            defaults={
                "program": target_section.program,
                "major": target_section.major,
            },
        )
        # Section/year level are per-semester (SectionMembership), scoped
        # to THIS class's own semester -- never overwrites a membership
        # the student already has for some other semester.
        SectionMembership.objects.update_or_create(
            student=user, semester=class_offering.semester, defaults={"section": target_section}
        )

        _, was_created = ClassRosterEntry.objects.get_or_create(
            student=user, class_offering=class_offering, defaults={"status": ClassRosterEntry.Status.ACTIVE}
        )
        if was_created:
            added_to_roster += 1

    return {"created_users": created_users, "added_to_roster": added_to_roster}
