"""Loads CITCI's real curriculum (course code/title/units, and where each
subject sits: program/major/year level/term) from the Registrar's
all_subject_per_major.docx into Subject + CurriculumEntry rows.

This file's docx shape turns out to be the SAME shape
import_offerings_docx.py already parses (Course Code/Description/Units/
Instructor/Room/Time columns, one table per program-major-year-level-
term) -- so this command reuses `parse_docx` verbatim and simply ignores
the instructor/room/schedule fields it has no use for. Never creates
Program/Major/ClassOffering/Section/User rows -- those must already
exist (e.g. via seed_citci_academics); a row resolving to an unknown
program/major is skipped and reported, never guessed.

Idempotent: re-running updates the same Subject rows (update_or_create
keyed on code) and the same CurriculumEntry rows (get_or_create keyed on
its unique_curriculum_slot constraint) -- running it twice produces the
same end state, not duplicates.
"""

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from academics.management.commands.import_offerings_docx import parse_docx
from academics.models import CurriculumEntry, Major, Program, Subject

_DATA_ISSUES_SECTION_HEADER = "## Curriculum loading issues (load_citci_curriculum)"
_DOCX_MAJOR_NAME_TO_CODE = {"English": "ENG", "Social Studies": "SS"}
_CODE_FAMILY_RE = re.compile(r"^([A-Za-z]+)\s*(\d+)$")


def _resolve_program_major(program_code, major_name):
    program = Program.objects.filter(code=program_code, is_active=True).first()
    if program is None:
        return None, None, f'Unknown program code "{program_code}".'
    if major_name is None:
        return program, None, None
    major_code = _DOCX_MAJOR_NAME_TO_CODE.get(major_name, major_name)
    major = Major.objects.filter(program=program, code=major_code, is_active=True).first()
    if major is None:
        return program, None, f'Unknown major "{major_name}" ({major_code}) for program {program_code}.'
    return program, major, None


def _is_prefix_variant(a, b):
    """True if `b` is `a` plus a word-boundary suffix (e.g. "PEd 205" ->
    "PEd 205 Elec") -- excludes a sequence-number collision like "PEd
    205" -> "PEd 2050" (next char is a digit, not a boundary)."""
    if a == b or not b.startswith(a):
        return False
    rest = b[len(a):]
    return rest == "" or not rest[0].isdigit()


def _find_near_duplicate_codes(codes):
    """Codes that are NOT identical but one is a word-boundary prefix of
    the other -- flagged for CITCI to confirm, never auto-merged."""
    codes = sorted(set(codes))
    pairs = []
    for i, a in enumerate(codes):
        for b in codes[i + 1 :]:
            if _is_prefix_variant(a, b) or _is_prefix_variant(b, a):
                pairs.append((a, b))
    return pairs


def _find_unit_jumps(subjects_by_code):
    """Flags consecutive-numbered codes sharing an alphabetic prefix
    (e.g. PATHFit 1/2/3 vs PATHFIT 4) whose units differ -- these are
    legitimate, distinct subjects, not a duplicate-code conflict; purely
    an informational flag, never auto-fixed."""
    families = {}
    for code, info in subjects_by_code.items():
        m = _CODE_FAMILY_RE.match(code)
        if not m:
            continue
        prefix, number = m.group(1).lower(), int(m.group(2))
        families.setdefault(prefix, []).append((number, code, info["units"]))

    jumps = []
    for items in families.values():
        items.sort()
        for (n1, c1, u1), (n2, c2, u2) in zip(items, items[1:]):
            if n2 == n1 + 1 and u1 != u2:
                jumps.append((c1, u1, c2, u2))
    return jumps


class Command(BaseCommand):
    help = (
        "Loads CITCI's real curriculum (Subject + CurriculumEntry rows) from the "
        "Registrar's docs/source/all_subject_per_major.docx."
    )

    def add_arguments(self, parser):
        parser.add_argument("path", type=str, help="Path to the curriculum .docx file.")

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"File not found: {path}")

        rows = parse_docx(path)

        # One (title, units) per code -- the source file lists BSED's
        # tables before TCP's, so a dict keyed by code naturally keeps
        # the first-seen (BSED) value; later, differing occurrences are
        # recorded as a conflict but never overwrite it.
        subjects_by_code = {}
        conflicts = []
        for row in rows:
            code = row["code"]
            existing = subjects_by_code.get(code)
            if existing is None:
                subjects_by_code[code] = {"title": row["description"], "units": row["units"]}
            elif existing["title"] != row["description"] or existing["units"] != row["units"]:
                conflicts.append((code, existing["title"], existing["units"], row["description"], row["units"]))

        near_duplicates = _find_near_duplicate_codes(subjects_by_code.keys())
        unit_jumps = _find_unit_jumps(subjects_by_code)

        subjects_created = subjects_updated = 0
        entries_created = 0
        skipped = []
        entries_per_slot = {}

        with transaction.atomic():
            for code, info in subjects_by_code.items():
                try:
                    units_value = Decimal(info["units"]) if info["units"] else None
                except InvalidOperation:
                    units_value = None
                if units_value is None:
                    skipped.append((code, f'invalid units "{info["units"]}"'))
                    continue
                subject, created = Subject.objects.update_or_create(
                    code=code, defaults={"title": info["title"], "units": units_value}
                )
                if created:
                    subjects_created += 1
                else:
                    subjects_updated += 1

            for row in rows:
                subject = Subject.objects.filter(code=row["code"]).first()
                if subject is None:
                    continue  # already recorded in `skipped` above
                program, major, error = _resolve_program_major(row["program"], row["major"])
                if error:
                    skipped.append((row["code"], error))
                    continue
                entry, created = CurriculumEntry.objects.get_or_create(
                    program=program, major=major, year_level=row["year_level"], term=row["semester"], subject=subject
                )
                if created:
                    entries_created += 1
                    key = (program.code, major.code if major else "-", row["year_level"], row["semester"])
                    entries_per_slot[key] = entries_per_slot.get(key, 0) + 1

        self._write_data_issues(conflicts, near_duplicates, unit_jumps)

        self.stdout.write(self.style.SUCCESS(f"Subjects: {subjects_created} created, {subjects_updated} updated."))
        self.stdout.write(self.style.SUCCESS(f"Curriculum entries created: {entries_created}."))
        for key in sorted(entries_per_slot):
            program_code, major_code, year_level, term = key
            label = f"{program_code}-{major_code}" if major_code != "-" else program_code
            self.stdout.write(f"  {label} Year {year_level or '-'} {term}: {entries_per_slot[key]}")
        if skipped:
            self.stdout.write(self.style.WARNING(f"Skipped {len(skipped)} row(s):"))
            for code, reason in skipped:
                self.stdout.write(f"  {code}: {reason}")
        if conflicts:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(conflicts)} exact-code conflict(s) -- kept the first-seen (BSED) value, see DATA_ISSUES.md."
                )
            )
        if near_duplicates:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(near_duplicates)} possible near-duplicate code pair(s) -- not merged, see DATA_ISSUES.md."
                )
            )
        if unit_jumps:
            self.stdout.write(
                self.style.WARNING(f"{len(unit_jumps)} unit jump(s) in a numbered code family -- see DATA_ISSUES.md.")
            )

    def _write_data_issues(self, conflicts, near_duplicates, unit_jumps):
        issues_path = Path(settings.BASE_DIR) / "docs" / "source" / "DATA_ISSUES.md"
        existing = issues_path.read_text(encoding="utf-8") if issues_path.exists() else (
            "# Data issues found while parsing Registrar sheets\n"
        )
        # Strip any previous run's own section so re-running this command
        # stays idempotent in the doc too, not just the DB -- leaves
        # import_offerings_docx's own section (if present) untouched.
        pattern = re.compile(re.escape(_DATA_ISSUES_SECTION_HEADER) + r".*?(?=\n## |\Z)", re.DOTALL)
        existing = pattern.sub("", existing).rstrip() + "\n"

        lines = [
            "",
            _DATA_ISSUES_SECTION_HEADER,
            "",
            "Generated by `python manage.py load_citci_curriculum <path>`. These are NOT",
            "auto-merged/auto-fixed -- confirm with CITCI first.",
            "",
            "### Same code, conflicting title/units across tables (kept the BSED value)",
            "",
        ]
        if conflicts:
            for code, bsed_title, bsed_units, other_title, other_units in conflicts:
                lines.append(
                    f"- **{code}**: kept {bsed_title!r} ({bsed_units} units) -- also seen as "
                    f"{other_title!r} ({other_units} units)."
                )
        else:
            lines.append("None found.")
        lines += ["", "### Possible duplicate codes (not merged)", ""]
        if near_duplicates:
            for a, b in near_duplicates:
                lines.append(f"- **{a!r}** vs **{b!r}** — possibly the same subject, confirm with CITCI.")
        else:
            lines.append("None found.")
        lines += ["", "### Unit jumps within a numbered code family (informational only)", ""]
        if unit_jumps:
            for c1, u1, c2, u2 in unit_jumps:
                lines.append(f"- **{c1}** = {u1} units, **{c2}** = {u2} units.")
        else:
            lines.append("None found.")

        issues_path.write_text(existing + "\n".join(lines) + "\n", encoding="utf-8")
