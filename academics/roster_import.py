"""Parsing + preview logic for the "Import class list" feature. CITCI
GradeTrack doesn't handle enrollment — this just turns a Registrar-exported
spreadsheet (ID Number, Last Name, First Name, Middle Name) into roster
rows, matching existing students by ID number and flagging new ones."""

import csv
import io

import openpyxl
from django.utils.crypto import get_random_string

from accounts.models import User

from .models import ClassRosterEntry, StudentProfile

REQUIRED_HEADERS = ["id number", "last name", "first name"]
OPTIONAL_HEADERS = ["middle name"]


class RosterImportError(Exception):
    pass


def _read_xlsx_rows(file_obj):
    workbook = openpyxl.load_workbook(file_obj, data_only=True)
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    return rows


def _read_csv_rows(file_obj):
    text = file_obj.read().decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text)))


def _normalize_header(cell):
    return str(cell or "").strip().lower()


def parse_roster_file(uploaded_file):
    """Returns (header_index_map, data_rows) or raises RosterImportError."""
    name = uploaded_file.name.lower()
    if name.endswith(".xlsx"):
        rows = _read_xlsx_rows(uploaded_file)
    elif name.endswith(".csv"):
        rows = _read_csv_rows(uploaded_file)
    else:
        raise RosterImportError("Only .xlsx or .csv files are supported.")

    if not rows:
        raise RosterImportError("The file is empty.")

    header = [_normalize_header(c) for c in rows[0]]
    index = {}
    for wanted in REQUIRED_HEADERS + OPTIONAL_HEADERS:
        if wanted in header:
            index[wanted] = header.index(wanted)

    missing = [h for h in REQUIRED_HEADERS if h not in index]
    if missing:
        raise RosterImportError(
            f"Missing required column(s): {', '.join(h.title() for h in missing)}. "
            f"Expected a header row with: ID Number, Last Name, First Name, Middle Name."
        )

    data_rows = rows[1:]
    return index, data_rows


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

        def cell(key):
            idx = index.get(key)
            if idx is None or idx >= len(row):
                return ""
            return str(row[idx] or "").strip()

        id_number = cell("id number")
        last_name = cell("last name")
        first_name = cell("first name")
        middle_name = cell("middle name")

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
                "year_level": target_section.year_level,
                "section": target_section,
            },
        )

        _, was_created = ClassRosterEntry.objects.get_or_create(
            student=user, class_offering=class_offering, defaults={"status": ClassRosterEntry.Status.ACTIVE}
        )
        if was_created:
            added_to_roster += 1

    return {"created_users": created_users, "added_to_roster": added_to_roster}
