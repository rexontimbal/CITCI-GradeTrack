"""Parses CITCI's official "all subject per major.docx" class-offering
sheet into docs/source/citci_offerings_2026_2027.json.

Document shape (as of the 2026-2027 sheet): a heading paragraph names the
major ("... MAJOR IN ENGLISH" / "... MAJOR IN SOCIAL STUDIES" / "TEACHER
CERTIFICATE PROGRAM (TCP)") and the semester ("1ST Semester ..." / "2ND
Semester ..."), followed by one table per year level (TCP has no year
level, just one table). Each table's first row is a merged header like
"FIRST YEAR – 1ST Semester S.Y. 2026-2027", the second row is the column
header (Course Code / Course Description / Units / Instructor / Room
Assignment / Time and Day), and the rest are data rows.

This command only understands that specific shape — it is not a general
docx-table parser.
"""

import json
import re
from pathlib import Path

import docx
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from docx.table import Table
from docx.text.paragraph import Paragraph

TITLE_RE = re.compile(r"^(Mr|Mrs|Ms|Dr)\.(?=\S)")
WHITESPACE_RE = re.compile(r"\s+")
YEAR_LEVEL_WORDS = {"FIRST": 1, "SECOND": 2, "THIRD": 3, "FOURTH": 4}


def normalize_space(text):
    return WHITESPACE_RE.sub(" ", (text or "").strip())


def normalize_instructor(raw):
    s = normalize_space(raw)
    s = TITLE_RE.sub(lambda m: f"{m.group(1)}. ", s)
    return s


def normalize_schedule(raw):
    s = normalize_space(raw)
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)
    s = re.sub(r"(?<=[A-Za-z0-9])\(", " (", s)  # ensure a space before "("
    s = normalize_space(s)
    open_count, close_count = s.count("("), s.count(")")
    if open_count > close_count:
        s += ")" * (open_count - close_count)
    return s


def levenshtein(a, b):
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        row = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            row.append(min(row[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = row
    return prev[-1]


def find_suspicious_name_pairs(names):
    """Flags distinct instructor strings close enough to plausibly be the
    same person misspelled/mistitled — never auto-merged, just reported."""
    names = sorted(names)
    pairs = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            if levenshtein(a, b) <= 2:
                pairs.append((a, b))
    return pairs


def parse_docx(path):
    document = docx.Document(path)
    body = document.element.body

    major = None
    is_tcp = False
    semester = None
    rows = []

    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            text = Paragraph(child, document).text.strip()
            if "MAJOR IN ENGLISH" in text:
                major, is_tcp = "English", False
            elif "MAJOR IN SOCIAL STUDIES" in text:
                major, is_tcp = "Social Studies", False
            elif "TEACHER CERTIFICATE PROGRAM" in text:
                major, is_tcp = None, True
            if text.upper().startswith("1ST SEMESTER"):
                semester = "FIRST"
            elif text.upper().startswith("2ND SEMESTER"):
                semester = "SECOND"

        elif child.tag.endswith("}tbl"):
            table = Table(child, document)
            header_text = table.rows[0].cells[0].text.strip().upper()
            year_level = None
            for word, level in YEAR_LEVEL_WORDS.items():
                if header_text.startswith(word):
                    year_level = level
                    break

            for row in table.rows[2:]:
                cells = [c.text.strip() for c in row.cells]
                if not any(cells) or len(cells) < 6:
                    continue
                code, description, units, instructor, room, time = cells[:6]
                if not code:
                    continue
                rows.append(
                    {
                        "semester": semester,
                        "program": "TCP" if is_tcp else "BSED",
                        "major": major,
                        "year_level": year_level,
                        "code": normalize_space(code),
                        "description": normalize_space(description),
                        "units": normalize_space(units),
                        "instructor": normalize_instructor(instructor),
                        "room": normalize_space(room),
                        "schedule": normalize_schedule(time),
                    }
                )

    return rows


def group_shared_classes(rows):
    """Groups rows that represent ONE class shared across sections: same
    semester + code + instructor + room + schedule. Returns a list of
    classes, each with its list of (program, major, year_level) sections."""
    groups = {}
    order = []
    for row in rows:
        key = (row["semester"], row["code"], row["instructor"], row["room"], row["schedule"])
        if key not in groups:
            groups[key] = {
                "semester": row["semester"],
                "code": row["code"],
                "description": row["description"],
                "units": row["units"],
                "instructor": row["instructor"],
                "room": row["room"],
                "schedule": row["schedule"],
                "sections": [],
            }
            order.append(key)
        groups[key]["sections"].append(
            {"program": row["program"], "major": row["major"], "year_level": row["year_level"]}
        )
    return [groups[k] for k in order]


class Command(BaseCommand):
    help = "Parses the Registrar's class-offering .docx into docs/source/citci_offerings_2026_2027.json."

    def add_arguments(self, parser):
        parser.add_argument("path", type=str, help="Path to the .docx file.")

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"File not found: {path}")

        rows = parse_docx(path)
        classes = group_shared_classes(rows)

        out_path = Path(settings.BASE_DIR) / "docs" / "source" / "citci_offerings_2026_2027.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(classes, indent=2, ensure_ascii=False), encoding="utf-8")

        instructor_names = sorted({row["instructor"] for row in rows})
        suspicious = find_suspicious_name_pairs(instructor_names)

        issues_path = Path(settings.BASE_DIR) / "docs" / "source" / "DATA_ISSUES.md"
        lines = [
            "# Data issues found while parsing the Registrar's class-offering sheet",
            "",
            "Generated by `python manage.py import_offerings_docx <path>`. These are NOT",
            "auto-merged — confirm with CITCI before treating any pair as the same person.",
            "",
            "## Suspicious instructor name pairs",
            "",
        ]
        if suspicious:
            for a, b in suspicious:
                lines.append(f"- **{a!r}** vs **{b!r}** — similar enough to possibly be the same person.")
        else:
            lines.append("None found.")
        issues_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        shared = [c for c in classes if len(c["sections"]) > 1]
        self.stdout.write(self.style.SUCCESS(f"Parsed {len(rows)} subject rows into {len(classes)} classes."))
        self.stdout.write(self.style.SUCCESS(f"{len(shared)} classes are shared across more than one section."))
        self.stdout.write(self.style.SUCCESS(f"{len(instructor_names)} distinct instructor name strings."))
        if suspicious:
            self.stdout.write(self.style.WARNING(f"{len(suspicious)} suspicious instructor name pair(s) — see {issues_path}"))
        self.stdout.write(self.style.SUCCESS(f"Wrote {out_path}"))
