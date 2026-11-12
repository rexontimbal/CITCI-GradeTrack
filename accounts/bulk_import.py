"""Bulk "Import Students" / "Import Instructors" (.xlsx/.csv, admin only).
Same preview -> confirm shape as the Phase 2.1 class-list importer, built on
the same shared file parser (core.importing) — existing accounts (matched by
ID number) are updated, not duplicated; new ones get a temporary password
that's only ever available right after that import's confirm step."""

import re

from academics.models import Program, Section, SectionMembership, StudentProfile
from core.importing import get_cell, parse_spreadsheet_file

from .models import User
from .utils import generate_temp_password

STUDENT_REQUIRED = ["id number", "last name", "first name", "program code"]
STUDENT_OPTIONAL = ["middle name", "major code", "year level", "email"]

INSTRUCTOR_REQUIRED = ["employee id", "last name", "first name"]
INSTRUCTOR_OPTIONAL = ["middle name", "title", "email"]

VALID_TITLES = {"mr.", "ms.", "mrs.", "dr."}


def parse_student_file(uploaded_file):
    return parse_spreadsheet_file(uploaded_file, STUDENT_REQUIRED, STUDENT_OPTIONAL)


def parse_instructor_file(uploaded_file):
    return parse_spreadsheet_file(uploaded_file, INSTRUCTOR_REQUIRED, INSTRUCTOR_OPTIONAL)


def _slugify_username(last_name, taken):
    base = re.sub(r"[^a-z0-9]", "", (last_name or "").lower()) or "user"
    username = base
    n = 2
    while username in taken:
        username = f"{base}{n}"
        n += 1
    taken.add(username)
    return username


def build_student_preview(index, data_rows, active_semester):
    active_academic_year = active_semester.academic_year if active_semester else None
    preview = []
    for row_number, row in enumerate(data_rows, start=2):
        if row is None or not any(row):
            continue

        id_number = get_cell(row, index, "id number")
        last_name = get_cell(row, index, "last name")
        first_name = get_cell(row, index, "first name")
        middle_name = get_cell(row, index, "middle name")
        program_code = get_cell(row, index, "program code")
        major_code = get_cell(row, index, "major code")
        year_level = get_cell(row, index, "year level")
        email = get_cell(row, index, "email")

        entry = {
            "row_number": row_number,
            "id_number": id_number,
            "last_name": last_name,
            "first_name": first_name,
            "middle_name": middle_name,
            "program_code": program_code,
            "major_code": major_code,
            "year_level": year_level,
            "email": email,
        }

        if not id_number or not last_name or not first_name or not program_code:
            entry["kind"] = "invalid"
            entry["reason"] = "Missing ID Number, Last Name, First Name, or Program Code."
            preview.append(entry)
            continue

        program = Program.objects.filter(code__iexact=program_code).first()
        if not program:
            entry["kind"] = "invalid"
            entry["reason"] = f"No program with code '{program_code}'."
            preview.append(entry)
            continue

        major = None
        if major_code:
            major = program.majors.filter(code__iexact=major_code).first()
            if not major:
                entry["kind"] = "invalid"
                entry["reason"] = f"No major '{major_code}' under program '{program_code}'."
                preview.append(entry)
                continue

        year_level_int = None
        if year_level:
            try:
                year_level_int = int(year_level)
            except ValueError:
                entry["kind"] = "invalid"
                entry["reason"] = f"Year level '{year_level}' isn't a number."
                preview.append(entry)
                continue

        # Year Level/Section are optional now (per-semester SectionMembership,
        # not account-level) -- an old import file that still has this column
        # keeps working: if a value is given, it's resolved to a section and
        # becomes a SectionMembership for the active semester at commit time;
        # if blank, the row is still valid with no section membership (a
        # perfectly normal student who joins classes by code, or whose
        # section Admin will set from the Program Head's Sections page).
        section = None
        if year_level_int is not None:
            if not active_academic_year:
                entry["kind"] = "invalid"
                entry["reason"] = "No active semester — set one before importing a Year Level."
                preview.append(entry)
                continue
            section = Section.objects.filter(
                program=program, major=major, academic_year=active_academic_year, year_level=year_level_int
            ).first()
            if not section:
                entry["kind"] = "invalid"
                entry["reason"] = "No matching section for this program/major/year level in the active academic year."
                preview.append(entry)
                continue

        # Session storage is JSON (django.contrib.sessions), so only plain
        # values go in the preview row — never model instances; commit_student_import
        # re-fetches by these IDs.
        entry["program_id"] = program.pk
        entry["major_id"] = major.pk if major else None
        entry["section_id"] = section.pk if section else None
        entry["semester_id"] = active_semester.pk if section else None
        entry["kind"] = "update" if User.objects.filter(id_number=id_number).exists() else "new"
        preview.append(entry)

    return preview


def commit_student_import(rows):
    created, updated = 0, 0
    for row in rows:
        if row["kind"] not in ("new", "update"):
            continue
        user, created_now = User.objects.update_or_create(
            id_number=row["id_number"],
            defaults={
                "username": row["id_number"],
                "role": User.Role.STUDENT,
                "last_name": row["last_name"],
                "first_name": row["first_name"],
                "middle_name": row["middle_name"],
                "email": row["email"],
            },
        )
        temp_password = None
        if created_now:
            temp_password = generate_temp_password()
            user.set_password(temp_password)
            user.must_change_password = True
            user.save(update_fields=["password", "must_change_password"])
            created += 1
        else:
            updated += 1

        StudentProfile.objects.update_or_create(
            user=user,
            defaults={
                "program_id": row["program_id"],
                "major_id": row["major_id"],
            },
        )
        if row.get("section_id") and row.get("semester_id"):
            SectionMembership.objects.update_or_create(
                student=user, semester_id=row["semester_id"], defaults={"section_id": row["section_id"]}
            )
        row["temp_password"] = temp_password
        row["username"] = user.username

    return {"created": created, "updated": updated}


def build_instructor_preview(index, data_rows):
    preview = []
    for row_number, row in enumerate(data_rows, start=2):
        if row is None or not any(row):
            continue

        employee_id = get_cell(row, index, "employee id")
        last_name = get_cell(row, index, "last name")
        first_name = get_cell(row, index, "first name")
        middle_name = get_cell(row, index, "middle name")
        title = get_cell(row, index, "title")
        email = get_cell(row, index, "email")

        entry = {
            "row_number": row_number,
            "id_number": employee_id,
            "last_name": last_name,
            "first_name": first_name,
            "middle_name": middle_name,
            "title": title,
            "email": email,
        }

        if not employee_id or not last_name or not first_name:
            entry["kind"] = "invalid"
            entry["reason"] = "Missing Employee ID, Last Name, or First Name."
            preview.append(entry)
            continue

        if title and title.lower() not in VALID_TITLES:
            entry["kind"] = "invalid"
            entry["reason"] = "Title must be Mr., Ms., Mrs., or Dr."
            preview.append(entry)
            continue

        entry["kind"] = "update" if User.objects.filter(id_number=employee_id).exists() else "new"
        preview.append(entry)

    return preview


def commit_instructor_import(rows):
    created, updated = 0, 0
    taken_usernames = set(User.objects.values_list("username", flat=True))

    for row in rows:
        if row["kind"] not in ("new", "update"):
            continue

        existing = User.objects.filter(id_number=row["id_number"]).first()
        display_first_name = f"{row['title']} {row['first_name']}".strip() if row["title"] else row["first_name"]

        if existing:
            existing.last_name = row["last_name"]
            existing.first_name = display_first_name
            existing.middle_name = row["middle_name"]
            existing.email = row["email"]
            existing.save(update_fields=["last_name", "first_name", "middle_name", "email"])
            row["username"] = existing.username
            row["temp_password"] = None
            updated += 1
        else:
            username = _slugify_username(row["last_name"], taken_usernames)
            temp_password = generate_temp_password()
            user = User.objects.create_user(
                username=username,
                password=temp_password,
                role=User.Role.INSTRUCTOR,
                id_number=row["id_number"],
                last_name=row["last_name"],
                first_name=display_first_name,
                middle_name=row["middle_name"],
                email=row["email"],
            )
            user.must_change_password = True
            user.save(update_fields=["must_change_password"])
            row["username"] = username
            row["temp_password"] = temp_password
            created += 1

    return {"created": created, "updated": updated}
