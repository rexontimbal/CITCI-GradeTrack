"""Dedicated importer for a real third-party gradebook/LMS export CITCI
instructors actually produce -- confirmed by direct inspection of 4 real
sample files (never committed, never stored raw -- see
docs/Historical_data/ locally). Distinct from both `historical_import.py`
(CITCI's own rigid Excel template) and `flexible_import.py` (a generic
single-table CSV/Excel with an admin-confirmed column mapping): this
format needs neither, since it is fully self-describing.

Shape: one workbook, 6 sheets -- `Prelim`/`Midterm`/`Finals` (one per
grading period, each its own full Attendance/Quizzes/Projects/Oral
Recitation/Major Examinations block), `Final` (a year-end summary --
confirmed always blank in every sample seen, not read here), `Transmutation`
(a percentage-to-grade table specific to this software, not needed since
each period sheet already carries its own computed Period Grade/Remarks),
and `Meta` (a JSON descriptor naming each period sheet plus a quarter_id).

Confirmed with the user: this software's year has 3 quarters, not CITCI's
4 periods -- quarter_id 1/2/3 map to PRELIM/MIDTERM/FINAL; nothing here
ever produces a SEMIFINAL-term item.

Meta's own numeric `col`/`studentCol` fields do NOT reliably correspond to
the exported sheet's visible column positions (confirmed by direct
inspection across the 4 samples -- they look like the source software's
internal field-schema numbering, not spreadsheet addresses), so this
module never trusts them for cell addressing. Meta is used only for the
deterministic format fingerprint and each sheet's quarter_id; every column
position is re-derived at runtime by scanning the real header text, the
same philosophy historical_import.py already uses for CITCI's own
template -- never trust a number nobody can see on screen.
"""

import json
import re

from openpyxl import load_workbook

from grading.models import AssessmentTerm

from .historical_import import (
    _CATEGORY_NAME_MAP,
    _SUB_HEADER_SKIP,
    _WEIGHT_SUFFIX,
    HistoricalImportPreview,
    ParsedItem,
    SkippedRow,
    compute_checkpoint_features,
    compute_label,
    mask_identifier,
)
from .models import Checkpoint, HistoricalRecord

_QUARTER_TO_TERM = {1: AssessmentTerm.PRELIM, 2: AssessmentTerm.MIDTERM, 3: AssessmentTerm.FINAL}

_SEMESTER_LABEL_MAX_LENGTH = HistoricalRecord._meta.get_field("semester_label").max_length
_SUBJECT_CODE_MAX_LENGTH = HistoricalRecord._meta.get_field("subject_code").max_length


def _read_meta(wb):
    """Returns the parsed Meta JSON dict, or None if this workbook doesn't
    have a usable one -- never raises, since this is also how detection
    (looks_like_fullyear_gradebook) probes a file."""
    if "Meta" not in wb.sheetnames:
        return None
    raw = wb["Meta"].cell(1, 1).value
    if not raw:
        return None
    try:
        meta = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if meta.get("type") != "fullyear" or not meta.get("sheets"):
        return None
    return meta


def looks_like_fullyear_gradebook(uploaded_file):
    """Detection probe -- a clean, unambiguous fingerprint (a `Meta` sheet
    whose JSON says `"type": "fullyear"`), not a guess. Always resets the
    file pointer afterward so a real parse can run next either way."""
    try:
        wb = load_workbook(uploaded_file, data_only=True)
        return _read_meta(wb) is not None
    except Exception:
        return False
    finally:
        try:
            uploaded_file.seek(0)
        except Exception:
            pass


def _find_student_header_row(ws):
    """This software's name-column header is a bare "Student" cell -- a
    separate, narrowly-scoped probe from historical_import._find_header_row
    (which looks for "NAME OF STUDENTS"/"ID NUMBER"), kept deliberately
    independent so widening what this module recognizes can never affect
    the existing rigid-template fast path's own detection."""
    for row in ws.iter_rows(min_row=1, max_row=10):
        values = {(cell.value or "").strip().upper() if isinstance(cell.value, str) else cell.value: cell.column for cell in row}
        if "STUDENT" in values:
            return row[0].row, values["STUDENT"]
    return None


def _normalize_label(value):
    return re.sub(r"\s+", " ", str(value).strip().upper()) if value is not None else ""


def _find_normalized_label_column(ws, header_row1, header_row2, label, max_col):
    """Same idea as historical_import._find_label_column, but collapses
    whitespace/newlines first -- this software's own "Period\\nGrade"
    header cell has an embedded newline historical_import.py's own exact
    match was never written to expect."""
    for row in (header_row1, header_row2):
        for col in range(1, max_col + 1):
            if _normalize_label(ws.cell(row, col).value) == label:
                return col
    return None


def _scan_period_components(ws, header_row1, header_row2, max_row, first_col, max_col, term):
    """A variant of historical_import._scan_components for one period
    sheet: every item here shares the SAME known term (the whole sheet IS
    one grading period), so this never falls back to quarter-guessing or
    exam sub-label terms the way the rigid scanner does -- it assigns
    `term` to every item uniformly, which is the one real difference from
    the function it's modeled on."""
    components = []
    col = first_col
    while col <= max_col:
        header1 = ws.cell(header_row1, col).value
        if not header1:
            col += 1
            continue
        name = _WEIGHT_SUFFIX.sub("", str(header1)).strip().upper()
        category = _CATEGORY_NAME_MAP.get(name)
        if category is None:
            col += 1
            continue

        item_cols = []
        c = col
        while c <= max_col:
            if c != col and ws.cell(header_row1, c).value:
                break
            label = ws.cell(header_row2, c).value
            label_str = str(label).strip().upper() if label is not None else ""
            if label_str in _SUB_HEADER_SKIP:
                c += 1
                if label_str in ("TOTAL",):
                    break
                continue
            item_cols.append((c, label_str))
            c += 1

        items = []
        for item_col, _label in item_cols:
            max_score = ws.cell(max_row, item_col).value
            try:
                max_score = float(max_score)
            except (TypeError, ValueError):
                continue
            items.append((item_col, ParsedItem(term=term, max_score=max_score)))

        components.append((category, items))
        col = c if c > col else col + 1

    return components


def _scan_sheet(ws):
    """Returns a dict describing one period sheet's layout, or None if it
    doesn't match the expected header shape at all (the whole file is
    then skipped with a clear reason -- never partially parsed)."""
    found = _find_student_header_row(ws)
    if found is None:
        return None
    header_row1, name_col = found
    header_row2 = header_row1 + 1
    max_row = header_row2 + 1
    first_data_row = max_row + 1
    max_col = ws.max_column

    first_item_col = name_col + 1
    for col in range(name_col + 1, max_col + 1):
        header1 = ws.cell(header_row1, col).value
        if header1 and _WEIGHT_SUFFIX.sub("", str(header1)).strip().upper() in _CATEGORY_NAME_MAP:
            first_item_col = col
            break

    period_grade_col = _find_normalized_label_column(ws, header_row1, header_row2, "PERIOD GRADE", max_col)
    remarks_col = _find_normalized_label_column(ws, header_row1, header_row2, "REMARKS", max_col)

    return {
        "name_col": name_col,
        "first_data_row": first_data_row,
        "max_row": max_row,
        "header_row1": header_row1,
        "header_row2": header_row2,
        "max_col": max_col,
        "first_item_col": first_item_col,
        "period_grade_col": period_grade_col,
        "remarks_col": remarks_col,
    }


def _cell_float(ws, row, col):
    if col is None:
        return None
    raw = ws.cell(row, col).value
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _cell_text(ws, row, col):
    if col is None:
        return ""
    raw = ws.cell(row, col).value
    return str(raw).strip().upper() if raw is not None else ""


def parse_gradebook_file(file_name, uploaded_file, semester_label, subject_code):
    """Returns (rows, skipped) in the exact same shape
    historical_import.parse_workbook already returns."""
    try:
        wb = load_workbook(uploaded_file, data_only=True)
    except Exception as exc:
        raise ValueError(f"Could not read {file_name} as an Excel workbook: {exc}") from exc

    meta = _read_meta(wb)
    if meta is None:
        raise ValueError(f"{file_name} is missing a usable fullyear-gradebook Meta sheet.")

    # Per period sheet: term, layout, and a normalized-name -> row map.
    periods = []
    final_period = None
    for entry in meta["sheets"]:
        quarter_id = entry.get("quarter_id")
        term = _QUARTER_TO_TERM.get(quarter_id)
        sheet_name = entry.get("name")
        if term is None or sheet_name not in wb.sheetnames:
            continue  # an unrecognized quarter or missing sheet is skipped, never guessed
        ws = wb[sheet_name]
        layout = _scan_sheet(ws)
        if layout is None:
            continue
        components = _scan_period_components(
            ws, layout["header_row1"], layout["header_row2"], layout["max_row"],
            layout["first_item_col"], layout["max_col"], term,
        )
        rows_by_name = {}
        row = layout["first_data_row"]
        while row <= ws.max_row:
            name_value = ws.cell(row, layout["name_col"]).value
            if name_value:
                rows_by_name[_normalize_label(name_value)] = row
            row += 1
        period = {"term": term, "ws": ws, "layout": layout, "components": components, "rows_by_name": rows_by_name}
        periods.append(period)
        if term == AssessmentTerm.FINAL:
            final_period = period

    if not periods:
        raise ValueError(f"{file_name} has no recognizable grading-period sheets.")
    if final_period is None:
        raise ValueError(f"{file_name} has no Final-quarter sheet to read a label from.")

    all_names = set()
    for period in periods:
        all_names.update(period["rows_by_name"])

    semester_label = (semester_label or file_name.rsplit(".", 1)[0])[:_SEMESTER_LABEL_MAX_LENGTH]
    subject_code = (subject_code or file_name.rsplit(".", 1)[0])[:_SUBJECT_CODE_MAX_LENGTH]

    rows = []
    skipped = []
    for name in sorted(all_names):
        final_row = final_period["rows_by_name"].get(name)
        if final_row is None:
            skipped.append(SkippedRow(file_name, 0, "No Final-quarter row for a student found elsewhere in the file."))
            continue

        layout = final_period["layout"]
        final_grade = _cell_float(final_period["ws"], final_row, layout["period_grade_col"])
        remarks = _cell_text(final_period["ws"], final_row, layout["remarks_col"])

        label = compute_label(final_grade, remarks)
        if label is None:
            skipped.append(SkippedRow(file_name, final_row, "No readable Period Grade or Remarks on the Final-quarter sheet."))
            continue

        masked_id = mask_identifier(name)

        items = []
        for period in periods:
            row = period["rows_by_name"].get(name)
            if row is None:
                continue
            for category, parsed_items in period["components"]:
                for item_col, parsed in parsed_items:
                    earned = _cell_float(period["ws"], row, item_col)
                    items.append((category, parsed.term, earned, parsed.max_score))

        for checkpoint in (Checkpoint.PRELIM, Checkpoint.MIDTERM):
            features = compute_checkpoint_features(items, checkpoint)
            if features is None:
                continue
            rows.append(
                {
                    "masked_id": masked_id,
                    "semester_label": semester_label,
                    "subject_code": subject_code,
                    "checkpoint": checkpoint,
                    "features_json": {k: (str(v) if v is not None else None) for k, v in features.items()},
                    "label": label,
                }
            )

    return rows, skipped


def build_gradebook_import_preview(files, semester_label_fn=None):
    """Same shape as historical_import.build_import_preview -- the view
    layer and commit_import need zero changes regardless of which parser
    produced this."""
    preview = HistoricalImportPreview()
    for file_name, uploaded_file in files:
        stem = file_name.rsplit(".", 1)[0]
        semester_label, subject_code = (semester_label_fn(stem) if semester_label_fn else (stem, stem))
        try:
            rows, skipped = parse_gradebook_file(file_name, uploaded_file, semester_label, subject_code)
        except ValueError as exc:
            preview.skipped.append(SkippedRow(file_name, 0, str(exc)))
            continue
        preview.file_names.append(file_name)
        preview.records.extend(rows)
        preview.skipped.extend(skipped)

    preview.row_count = len(preview.records)
    preview.positive_count = sum(r["label"] for r in preview.records)
    return preview
