"""Class Record Excel import — preview/confirm, mirroring academics/
roster_import.py's pattern. Robustly handles the system's own export
(reports.excel.build_class_record_workbook) since its header layout is
exact; the raw CITCI template shape (grading-system.xlsx) is read with the
same header-scanning logic and works as long as it keeps "ID Number" /
"Name of Students" header cells and one max-score row below the item
titles — a materially different layout needs parser changes.

Known limitation (disclosed, not silently handled): an item column that
doesn't match any existing AssessmentItem by (component, title) is
reported as unmatched and never auto-created — matching the instruction
to never guess.
"""

import re
from dataclasses import dataclass, field

from openpyxl import load_workbook

from grading.models import AssessmentItem, Score
from grading.services import save_score

_WEIGHT_SUFFIX = re.compile(r"\s*\(\d+%\)\s*$")


@dataclass
class InvalidCell:
    row_label: str
    item_title: str
    raw_value: str
    reason: str


@dataclass
class ScoreChange:
    roster_entry_id: int
    item_id: int
    student_label: str
    item_title: str
    old_value: object
    new_value: int


@dataclass
class ImportPreview:
    new_scores: list = field(default_factory=list)  # list[ScoreChange]
    changed_scores: list = field(default_factory=list)  # list[ScoreChange]
    unmatched_students: list = field(default_factory=list)  # list[str]
    unmatched_items: list = field(default_factory=list)  # list[str]
    invalid_cells: list = field(default_factory=list)  # list[InvalidCell]

    @property
    def has_writes(self):
        return bool(self.new_scores or self.changed_scores)

    def to_session(self):
        return {
            "writes": [
                {"roster_entry_id": c.roster_entry_id, "item_id": c.item_id, "new_value": c.new_value}
                for c in (self.new_scores + self.changed_scores)
            ]
        }


def _normalize_name(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().upper()


def _student_label(student):
    middle_initial = f" {student.middle_name[0]}." if student.middle_name else ""
    return f"{student.last_name}, {student.first_name}{middle_initial}"


def _find_header_row(ws):
    """Scan for the (merged, two-row-tall) header row containing "ID
    Number" and "Name of Students" — these labels (and the component
    names) live on the merge's top row; item titles are one row below
    that, and the max-score row one below that again."""
    for row in ws.iter_rows(min_row=1, max_row=30):
        values = {(cell.value or "").strip().upper() if isinstance(cell.value, str) else cell.value: cell.column for cell in row}
        if "ID NUMBER" in values and any(k and "NAME" in str(k) for k in values):
            id_col = values["ID NUMBER"]
            name_col = next(c for k, c in values.items() if k and "NAME" in str(k))
            return row[0].row, id_col, name_col
    raise ValueError('Could not find the "ID Number" / "Name of Students" header row in this file.')


def build_import_preview(class_offering, uploaded_file):
    try:
        wb = load_workbook(uploaded_file, data_only=False)
    except Exception as exc:
        raise ValueError(f"Could not read this file as an Excel workbook: {exc}") from exc
    ws = wb.active

    header_row1, id_col, name_col = _find_header_row(ws)
    header_row2 = header_row1 + 1
    max_row = header_row2 + 1
    first_data_row = max_row + 1
    first_item_col = name_col + 1
    max_col = ws.max_column

    # Figure out which columns are item columns (skip TOTAL/GRADE/WEIGHTED
    # sub-header cells and the trailing FINAL GRADE/REMARKS columns).
    item_cols = []
    last_component_name = ""
    for col in range(first_item_col, max_col + 1):
        row1_val = ws.cell(header_row1, col).value
        row2_val = ws.cell(header_row2, col).value
        if row1_val:
            last_component_name = _WEIGHT_SUFFIX.sub("", str(row1_val)).strip()
        label = str(row2_val).strip().upper() if row2_val else ""
        if label in ("", "TOTAL", "GRADE", "WEIGHTED", "FINAL GRADE", "REMARKS", "(NO ITEMS)"):
            continue
        if last_component_name.upper() in ("FINAL GRADE", "REMARKS"):
            continue
        item_cols.append((col, last_component_name, str(row2_val).strip()))

    # Resolve each item column to an AssessmentItem by (component name, title).
    existing_items = list(
        AssessmentItem.objects.filter(class_offering=class_offering).select_related("component")
    )

    def _lookup_item(component_name, title):
        for item in existing_items:
            if item.component.name.strip().upper() == component_name.strip().upper() and item.title.strip().upper() == title.strip().upper():
                return item
        return None

    preview = ImportPreview()
    resolved_cols = []
    for col, component_name, title in item_cols:
        item = _lookup_item(component_name, title)
        if item is None:
            preview.unmatched_items.append(f"{component_name} — {title}")
        else:
            resolved_cols.append((col, item))

    # Resolve each data row to a ClassRosterEntry, by ID number first then
    # by normalized "Last, First M." name.
    roster_entries = list(class_offering.roster_entries.select_related("student"))
    by_id = {e.student.id_number: e for e in roster_entries if e.student.id_number}
    by_name = {_normalize_name(_student_label(e.student)): e for e in roster_entries}

    existing_scores = {
        (s.roster_entry_id, s.item_id): s.score
        for s in Score.objects.filter(roster_entry__class_offering=class_offering)
    }

    row = first_data_row
    while row <= ws.max_row:
        id_value = ws.cell(row, id_col).value
        name_value = ws.cell(row, name_col).value
        if not id_value and not name_value:
            row += 1
            continue

        entry = None
        if id_value:
            entry = by_id.get(str(id_value).strip())
        if entry is None and name_value:
            entry = by_name.get(_normalize_name(name_value))

        if entry is None:
            preview.unmatched_students.append(str(name_value or id_value))
            row += 1
            continue

        for col, item in resolved_cols:
            raw = ws.cell(row, col).value
            if raw is None or raw == "":
                continue
            row_label = _student_label(entry.student)
            try:
                numeric = float(raw)
            except (TypeError, ValueError):
                preview.invalid_cells.append(InvalidCell(row_label, item.title, str(raw), "Not a number"))
                continue
            if numeric != int(numeric):
                preview.invalid_cells.append(InvalidCell(row_label, item.title, str(raw), "Whole numbers only"))
                continue
            new_value = int(numeric)
            if new_value < 0 or new_value > item.max_score:
                preview.invalid_cells.append(InvalidCell(row_label, item.title, str(raw), f"Max is {item.max_score}"))
                continue

            old_value = existing_scores.get((entry.id, item.id))
            if old_value == new_value:
                continue
            change = ScoreChange(entry.id, item.id, row_label, item.title, old_value, new_value)
            if old_value is None:
                preview.new_scores.append(change)
            else:
                preview.changed_scores.append(change)

        row += 1

    return preview


def commit_import(class_offering, stashed, user):
    items_by_id = {item.id: item for item in AssessmentItem.objects.filter(class_offering=class_offering)}
    entries_by_id = {e.id: e for e in class_offering.roster_entries.all()}
    for write in stashed.get("writes", []):
        entry = entries_by_id.get(write["roster_entry_id"])
        item = items_by_id.get(write["item_id"])
        if entry is None or item is None:
            continue
        save_score(entry, item, write["new_value"], user)
