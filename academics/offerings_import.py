"""Preview + commit logic for the "Import Class Offerings" admin page —
turns a Registrar spreadsheet (or the existing Registrar .docx format, via
`import_offerings_docx`) into new Subjects/ClassOfferings for a chosen
target semester. Mirrors academics/roster_import.py's upload -> preview ->
confirm shape; file parsing itself is shared via core.importing.

Instructors are matched by exact (case-insensitive) name against existing
INSTRUCTOR users only — an unmatched name is listed for the admin to assign
manually afterward. This module never creates or fuzzy-merges an
instructor account."""

from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied
from django.db import transaction

from accounts.models import User
from core.importing import SpreadsheetImportError, get_cell, parse_spreadsheet_file  # noqa: F401 (re-exported)

from . import scoping
from .management.commands.import_offerings_docx import normalize_instructor, normalize_space, parse_docx
from .models import ClassOffering, CurriculumEntry, Major, Program, Section, Subject

REQUIRED_HEADERS = ["semester", "program", "course code", "description", "units"]
OPTIONAL_HEADERS = ["major", "year level", "room", "schedule", "instructor"]


def parse_offerings_xlsx(uploaded_file):
    return parse_spreadsheet_file(uploaded_file, REQUIRED_HEADERS, OPTIONAL_HEADERS)


def _resolve_program(code):
    if not code:
        return None, "Missing program code."
    program = Program.objects.filter(code__iexact=code, is_active=True).first()
    if program is None:
        return None, f'Unknown program code "{code}".'
    return program, None


def _resolve_major(program, code):
    if not code:
        return None, None
    major = Major.objects.filter(program=program, code__iexact=code, is_active=True).first()
    if major is None:
        return None, f'Unknown major code "{code}" for program {program.code}.'
    return major, None


def _parse_year_level(raw):
    if not raw:
        return None, None
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return None, f'Year level "{raw}" is not a number.'
    if value not in (1, 2, 3, 4):
        return None, f'Year level "{raw}" must be 1-4 (leave blank for a program with no year levels, e.g. TCP).'
    return value, None


def _parse_units(raw):
    try:
        return Decimal(str(raw).strip()), None
    except (InvalidOperation, AttributeError):
        return None, f'Units "{raw}" is not a valid number.'


def _resolve_section(program, major, year_level, academic_year):
    section = Section.objects.filter(
        program=program, major=major, academic_year=academic_year, year_level=year_level
    ).first()
    if section is None:
        return None, (
            f"No section found for {program.code}"
            f"{'-' + major.code if major else ''} year {year_level or '—'} in {academic_year}."
        )
    return section, None


def _classify_row(row_number, semester_label, program_code, major_code, year_level_raw, code, description, units_raw,
                   room, schedule, instructor_name, target_semester, user=None):
    entry = {
        "row_number": row_number,
        "semester_label": semester_label,
        "program_code": program_code,
        "major_code": major_code,
        "code": code,
        "description": description,
        "room": room,
        "schedule": normalize_space(schedule),
        "instructor_name": normalize_instructor(instructor_name) if instructor_name else "",
    }

    if not code or not description:
        entry["kind"] = "invalid"
        entry["reason"] = "Missing Course Code or Description."
        return entry

    program, error = _resolve_program(program_code)
    if error:
        entry["kind"] = "invalid"
        entry["reason"] = error
        return entry

    major, error = _resolve_major(program, major_code)
    if error:
        entry["kind"] = "invalid"
        entry["reason"] = error
        return entry

    year_level, error = _parse_year_level(year_level_raw)
    if error:
        entry["kind"] = "invalid"
        entry["reason"] = error
        return entry

    units, error = _parse_units(units_raw)
    if error:
        entry["kind"] = "invalid"
        entry["reason"] = error
        return entry

    if user is not None and not scoping.is_in_scope(user, program.id, major.id if major else None):
        entry["kind"] = "invalid"
        entry["reason"] = f'{program.code}{"-" + major.code if major else ""} is outside your scope.'
        return entry

    section, error = _resolve_section(program, major, year_level, target_semester.academic_year)
    if error:
        entry["kind"] = "invalid"
        entry["reason"] = error
        return entry

    entry["kind"] = "ok"
    entry["program_id"] = program.id
    entry["major_id"] = major.id if major else None
    entry["year_level"] = year_level
    entry["units"] = str(units)
    entry["section_id"] = section.id
    return entry


def _match_instructor(name):
    if not name:
        return None
    full_name_parts = name.strip().split()
    if not full_name_parts:
        return None
    for user in User.objects.filter(role=User.Role.INSTRUCTOR):
        if user.full_name.strip().upper() == name.strip().upper():
            return user
    return None


def _group_into_classes(valid_rows):
    """Groups preview rows representing one shared class: same course
    code + room + schedule + instructor name. Mirrors
    import_offerings_docx.group_shared_classes's grouping key, generalized
    to work off already-classified rows."""
    groups = {}
    order = []
    for row in valid_rows:
        key = (row["code"], row["room"], row["schedule"], row["instructor_name"])
        if key not in groups:
            groups[key] = {
                "code": row["code"],
                "description": row["description"],
                "units": row["units"],
                "room": row["room"],
                "schedule": row["schedule"],
                "instructor_name": row["instructor_name"],
                "program_ids": [],
                "section_ids": [],
            }
            order.append(key)
        group = groups[key]
        if row["program_id"] not in group["program_ids"]:
            group["program_ids"].append(row["program_id"])
        if row["section_id"] not in group["section_ids"]:
            group["section_ids"].append(row["section_id"])
    return [groups[k] for k in order]


def build_offerings_preview(index, data_rows, target_semester, user=None):
    """Classifies every row, never writing anything. Returns a dict with
    the raw per-row results (for an error table) plus grouped `classes`
    ready for commit_offerings_import. When `user` is a scoped Program
    Head (not None/admin), rows outside their scope are marked invalid."""
    rows = []
    for row_number, row in enumerate(data_rows, start=2):  # row 1 is the header
        if row is None or not any(row):
            continue
        rows.append(
            _classify_row(
                row_number,
                get_cell(row, index, "semester"),
                get_cell(row, index, "program"),
                get_cell(row, index, "major"),
                get_cell(row, index, "year level"),
                get_cell(row, index, "course code"),
                get_cell(row, index, "description"),
                get_cell(row, index, "units"),
                get_cell(row, index, "room"),
                get_cell(row, index, "schedule"),
                get_cell(row, index, "instructor"),
                target_semester,
                user=user,
            )
        )
    return _finalize_preview(rows)


def _finalize_preview(rows):
    valid_rows = [r for r in rows if r["kind"] == "ok"]
    classes = _group_into_classes(valid_rows)

    existing_codes = set(Subject.objects.filter(code__in=[c["code"] for c in classes]).values_list("code", flat=True))
    unknown_instructor_names = set()
    for cls in classes:
        cls["is_new_subject"] = cls["code"] not in existing_codes
        cls["is_shared"] = len(cls["section_ids"]) > 1
        matched = _match_instructor(cls["instructor_name"])
        cls["matched_instructor_id"] = matched.id if matched else None
        cls["matched_instructor_name"] = matched.full_name if matched else ""
        if cls["instructor_name"] and matched is None:
            unknown_instructor_names.add(cls["instructor_name"])

    return {
        "rows": rows,
        "classes": classes,
        "unknown_instructor_names": sorted(unknown_instructor_names),
        "new_subject_count": sum(1 for c in classes if c["is_new_subject"]),
        "new_class_count": len(classes),
        "shared_class_count": sum(1 for c in classes if c["is_shared"]),
        "invalid_count": sum(1 for r in rows if r["kind"] == "invalid"),
    }


_DOCX_PROGRAM_CODE = {False: None, True: "TCP"}  # is_tcp -> program code; non-TCP resolved from major below
_DOCX_MAJOR_NAME_TO_CODE = {"English": "ENG", "Social Studies": "SS"}


def parse_offerings_docx_for_preview(uploaded_file, target_semester, user=None):
    """Reuses import_offerings_docx.parse_docx, reshapes its rows into the
    same preview-row shape build_offerings_preview produces, filtered to
    this target semester's term (the docx covers both 1st and 2nd sem in
    one file)."""
    docx_rows = parse_docx(uploaded_file)
    rows = []
    for row_number, docx_row in enumerate(docx_rows, start=2):
        if docx_row["semester"] != target_semester.term:
            continue
        program_code = "TCP" if docx_row["program"] == "TCP" else "BSED"
        major_code = _DOCX_MAJOR_NAME_TO_CODE.get(docx_row["major"], docx_row["major"])
        rows.append(
            _classify_row(
                row_number,
                docx_row["semester"],
                program_code,
                major_code,
                str(docx_row["year_level"]) if docx_row["year_level"] else "",
                docx_row["code"],
                docx_row["description"],
                docx_row["units"],
                docx_row["room"],
                docx_row["schedule"],
                docx_row["instructor"],
                target_semester,
                user=user,
            )
        )
    return _finalize_preview(rows)


def commit_offerings_import(classes, target_semester, user=None):
    """One atomic transaction. `classes` is the grouped list from a
    preview's "classes" key — never re-parses the uploaded file. An
    instructor is only ever set when matched by exact name; otherwise the
    class is created Unassigned, per spec ("never auto-create or
    auto-merge instructors"). When `user` is a scoped Program Head, every
    row's program/major is re-checked against scope_for(user) here too —
    the preview is session-stashed and round-tripped through the browser,
    never trusted blindly at commit time."""
    subjects_created = 0
    classes_created = 0
    shared_classes_detected = 0
    unassigned_instructor_classes = 0

    with transaction.atomic():
        for cls in classes:
            if user is not None:
                for section in Section.objects.filter(pk__in=cls["section_ids"]):
                    if not scoping.is_in_scope(user, section.program_id, section.major_id):
                        raise PermissionDenied("One or more rows are outside your scope.")
            subject = Subject.objects.filter(code=cls["code"]).first()
            if subject is None:
                subject = Subject.objects.create(
                    code=cls["code"],
                    title=cls["description"],
                    units=Decimal(cls["units"]),
                )
                subjects_created += 1

            # Every distinct (program, major, year_level) among this row's
            # sections gets its own curriculum slot for the target
            # semester's term — a class shared across sections/majors
            # places the subject in each of their prospectuses, not just
            # one.
            for section in Section.objects.filter(pk__in=cls["section_ids"]):
                CurriculumEntry.objects.get_or_create(
                    program=section.program,
                    major=section.major,
                    year_level=section.year_level,
                    term=target_semester.term,
                    subject=subject,
                )

            class_offering = ClassOffering.objects.create(
                subject=subject,
                semester=target_semester,
                instructor_id=cls["matched_instructor_id"],
                schedule=cls["schedule"],
                room=cls["room"],
            )
            class_offering.sections.set(cls["section_ids"])
            classes_created += 1
            if len(cls["section_ids"]) > 1:
                shared_classes_detected += 1
            if cls["matched_instructor_id"] is None:
                unassigned_instructor_classes += 1

    return {
        "subjects_created": subjects_created,
        "classes_created": classes_created,
        "shared_classes_detected": shared_classes_detected,
        "unassigned_instructor_classes": unassigned_instructor_classes,
    }
