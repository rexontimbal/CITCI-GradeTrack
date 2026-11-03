"""Historical class-record import — parses past CITCI class records
(`.xlsx`) in either the raw CITCI template shape (`grading-system.xlsx`'s
layout) or this system's own Class Record export (`reports/excel.py`),
computes PRELIM/MIDTERM features the same way `forecasting.ml.features`
would for live data (but directly from the parsed sheet, since historical
rows have no AssessmentItem/Score DB rows), masks identities, and returns
a preview ready for `commit_import`. CLAUDE.md section 7.

Column mapping: component headers (ATTENDANCE/QUIZZES/RECITATION/PROJECT/
EXAMINATION) map to grading.ComponentCategory via case-insensitive name
matching. The Examination block's own four sub-columns are literally
labeled P/M/S/F and map directly to Prelim/Midterm/Semi-final/Final.
**Every other component's items carry no recorded term in an old sheet —
assumed to run in chronological column order, split into quarters
(1st quarter of columns -> Prelim, 2nd -> Midterm, ...).** This is a
disclosed limitation, not a verified term (see HistoricalImportBatch.
term_assignment_note and CLAUDE.md section 7).

Identities are masked immediately during parsing — nothing past this
module ever sees a real name or ID number. The preview returned here (and
everything stashed in the session between preview and confirm) already
only carries `masked_id`.
"""

import hashlib
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from django.conf import settings
from openpyxl import load_workbook

from grading.models import ASSESSMENT_TERM_ORDER, AssessmentTerm, ComponentCategory

from .models import Checkpoint

_WEIGHT_SUFFIX = re.compile(r"\s*\(\d+%\)\s*$")

_CATEGORY_NAME_MAP = {
    "ATTENDANCE": ComponentCategory.ATTENDANCE,
    "QUIZZES": ComponentCategory.QUIZ,
    "QUIZ": ComponentCategory.QUIZ,
    "RECITATION": ComponentCategory.RECITATION,
    "PROJECT": ComponentCategory.PROJECT,
    "EXAMINATION": ComponentCategory.EXAM,
    "EXAM": ComponentCategory.EXAM,
}

_EXAM_SUBLABEL_TERM = {"P": AssessmentTerm.PRELIM, "M": AssessmentTerm.MIDTERM, "S": AssessmentTerm.SEMIFINAL, "F": AssessmentTerm.FINAL}

_CATEGORY_TO_FEATURE = {
    ComponentCategory.QUIZ: "quiz_pct",
    ComponentCategory.RECITATION: "recitation_pct",
    ComponentCategory.PROJECT: "project_pct",
    ComponentCategory.OTHER: "project_pct",
    ComponentCategory.ATTENDANCE: "attendance_pct",
    ComponentCategory.EXAM: "exam_pct",
}

_SUB_HEADER_SKIP = {"", "TOTAL", "GRADE", "WEIGHTED", "(NO ITEMS)"}

# Default CITCI component weights (grading-system.xlsx) — used to compute
# the checkpoint running_grade feature when a sheet's own weight row can't
# be read reliably; re-normalized across whichever categories have items.
_DEFAULT_WEIGHTS = {
    ComponentCategory.ATTENDANCE: 5,
    ComponentCategory.QUIZ: 30,
    ComponentCategory.RECITATION: 15,
    ComponentCategory.PROJECT: 10,
    ComponentCategory.OTHER: 10,
    ComponentCategory.EXAM: 40,
}


def mask_identifier(raw_identifier):
    """SHA-256(app secret salt + identifier) — the only function allowed
    to see a real name/ID number in this whole pipeline. The same
    identifier always hashes to the same masked_id (deterministic, no
    per-call randomness), so repeat appearances of the same student across
    checkpoints/files collapse to one masked_id."""
    salted = f"{settings.SECRET_KEY}:{raw_identifier.strip().upper()}"
    return hashlib.sha256(salted.encode("utf-8")).hexdigest()


def _quarter_terms(n):
    """Assign n chronologically-ordered items to Prelim/Midterm/Semi-final/
    Final by column position, split into quarters — the disclosed
    assumption for an old sheet's non-exam items (see module docstring)."""
    terms = [AssessmentTerm.PRELIM, AssessmentTerm.MIDTERM, AssessmentTerm.SEMIFINAL, AssessmentTerm.FINAL]
    if n == 0:
        return []
    return [terms[min(3, i * 4 // n)] for i in range(n)]


@dataclass
class ParsedItem:
    term: str
    max_score: float


@dataclass
class SkippedRow:
    file: str
    row: int
    reason: str


@dataclass
class HistoricalImportPreview:
    file_names: list = field(default_factory=list)
    row_count: int = 0
    positive_count: int = 0
    records: list = field(default_factory=list)  # [{masked_id, semester_label, subject_code, checkpoint, features_json, label}, ...]
    skipped: list = field(default_factory=list)  # [SkippedRow, ...]

    def to_session(self):
        return {
            "file_names": self.file_names,
            "row_count": self.row_count,
            "positive_count": self.positive_count,
            "records": self.records,
            "skipped": [asdict(s) for s in self.skipped],
        }


def _find_header_row(ws):
    """Same 3-row header shape as reports/excel_import.py: component names
    (and "No."/"Name of Students" or "ID Number") on the merge's top row,
    item sub-labels one row below, max-score row one below that."""
    for row in ws.iter_rows(min_row=1, max_row=30):
        values = {(cell.value or "").strip().upper() if isinstance(cell.value, str) else cell.value: cell.column for cell in row}
        if "NAME OF STUDENTS" in values or "ID NUMBER" in values:
            name_col = values.get("NAME OF STUDENTS")
            id_col = values.get("ID NUMBER")
            return row[0].row, id_col, name_col
    raise ValueError('Could not find a "Name of Students"/"ID Number" header row in this file.')


def _scan_components(ws, header_row1, header_row2, max_row, first_col, max_col):
    """Returns a list of (category, [ParsedItem-or-None per data cell
    column], first_item_col, last_item_col) — one entry per recognized
    component block. Unrecognized component headers are skipped (neither
    scored nor counted — nothing is guessed)."""
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

        # Walk forward while header_row2 sub-labels belong to this block
        # (stop at the next non-empty header_row1 cell, or TOTAL/GRADE/
        # WEIGHTED tail columns).
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

        if category == ComponentCategory.EXAM:
            terms = [_EXAM_SUBLABEL_TERM.get(label, AssessmentTerm.FINAL) for _, label in item_cols]
        else:
            terms = _quarter_terms(len(item_cols))

        items = []
        for (item_col, _label), term in zip(item_cols, terms):
            max_score = ws.cell(max_row, item_col).value
            try:
                max_score = float(max_score)
            except (TypeError, ValueError):
                continue
            items.append((item_col, ParsedItem(term=term, max_score=max_score)))

        components.append((category, items))
        col = c if c > col else col + 1

    return components


def _find_first_item_col(ws, header_row1, max_col):
    """Scans row `header_row1` for the first cell whose text matches a
    recognized component category — everything before it (from column 2
    on) is the "No."/"ID Number"/"Name of Students" header block, however
    many columns that merge actually spans (which we can't assume from
    where its own text happens to sit — a merged cell's text lives only in
    its top-left column)."""
    for col in range(2, max_col + 1):
        header1 = ws.cell(header_row1, col).value
        if not header1:
            continue
        name = _WEIGHT_SUFFIX.sub("", str(header1)).strip().upper()
        if name in _CATEGORY_NAME_MAP:
            return col
    return max_col + 1


def _find_label_column(ws, header_row1, header_row2, label, max_col):
    for row in (header_row1, header_row2):
        for col in range(1, max_col + 1):
            value = ws.cell(row, col).value
            if value and str(value).strip().upper() == label:
                return col
    return None


def parse_workbook(file_name, uploaded_file, semester_label, subject_code):
    """Returns (rows, skipped) — rows is a list of dicts
    {masked_id, features (raw, pre-imputation, per checkpoint), label}
    ready to fan out into one HistoricalRecord per checkpoint. Raises
    ValueError for a file this parser can't make sense of at all."""
    try:
        wb = load_workbook(uploaded_file, data_only=True)
    except Exception as exc:
        raise ValueError(f"Could not read {file_name} as an Excel workbook: {exc}") from exc
    ws = wb.active

    header_row1, id_col, name_col = _find_header_row(ws)
    header_row2 = header_row1 + 1
    max_row = header_row2 + 1
    first_data_row = max_row + 1
    max_col = ws.max_column

    name_block_start = 2  # column A is always "No."
    first_item_col = _find_first_item_col(ws, header_row1, max_col)
    name_block_end = first_item_col - 1

    components = _scan_components(ws, header_row1, header_row2, max_row, first_item_col, max_col)
    final_grade_col = _find_label_column(ws, header_row1, header_row2, "FINAL GRADE", max_col)
    remarks_col = _find_label_column(ws, header_row1, header_row2, "REMARKS", max_col)

    rows = []
    skipped = []
    row = first_data_row
    while row <= ws.max_row:
        id_value = ws.cell(row, id_col).value if id_col else None
        name_parts = [
            str(ws.cell(row, c).value).strip()
            for c in range(name_block_start, name_block_end + 1)
            if ws.cell(row, c).value not in (None, "")
        ]
        if not id_value and not name_parts:
            row += 1
            continue

        identifier = str(id_value).strip() if id_value else " ".join(name_parts)
        if not identifier:
            row += 1
            continue

        final_grade = ws.cell(row, final_grade_col).value if final_grade_col else None
        remarks = str(ws.cell(row, remarks_col).value or "").strip().upper() if remarks_col else ""

        try:
            final_grade = float(final_grade) if final_grade is not None else None
        except (TypeError, ValueError):
            final_grade = None

        if final_grade is None and remarks not in ("INC", "DROPPED", "DRP"):
            skipped.append(SkippedRow(file_name, row, "No readable FINAL GRADE or remarks — can't determine a label"))
            row += 1
            continue

        if remarks in ("DROPPED", "DRP"):
            label = 1  # DROPPED counts as at-risk, per the target-label rule
        elif remarks == "INC":
            label = 1
        else:
            label = 1 if final_grade > 3.00 else 0

        masked_id = mask_identifier(identifier)

        for checkpoint in (Checkpoint.PRELIM, Checkpoint.MIDTERM):
            features = _checkpoint_features(ws, row, components, checkpoint)
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
        row += 1

    return rows, skipped


def _checkpoint_features(ws, row, components, checkpoint):
    cutoff = ASSESSMENT_TERM_ORDER[checkpoint]
    sums = {}  # feature_name -> [earned, possible]
    for category, items in components:
        feature_name = _CATEGORY_TO_FEATURE.get(category)
        if feature_name is None:
            continue
        for item_col, parsed in items:
            if ASSESSMENT_TERM_ORDER[parsed.term] > cutoff:
                continue
            raw = ws.cell(row, item_col).value
            try:
                earned = float(raw)
            except (TypeError, ValueError):
                continue
            bucket = sums.setdefault(feature_name, [0.0, 0.0])
            bucket[0] += earned
            bucket[1] += parsed.max_score

    if not sums:
        return None

    features = {name: None for name in _CATEGORY_TO_FEATURE.values()}
    for name, (earned, possible) in sums.items():
        features[name] = Decimal(str(round(earned / possible * 100, 4))) if possible else None

    total_in_scope = 0
    total_scored = 0
    weighted_sum = Decimal("0")
    weight_total = Decimal("0")
    for category, items in components:
        in_scope = [p for _, p in items if ASSESSMENT_TERM_ORDER[p.term] <= cutoff]
        if not in_scope:
            continue
        earned = Decimal("0")
        possible = Decimal("0")
        for item_col, parsed in items:
            if ASSESSMENT_TERM_ORDER[parsed.term] > cutoff:
                continue
            total_in_scope += 1
            raw = ws.cell(row, item_col).value
            possible += Decimal(str(parsed.max_score))
            try:
                earned += Decimal(str(float(raw)))
                total_scored += 1
            except (TypeError, ValueError):
                pass
        if possible:
            grade = Decimal("5") - Decimal("4") * (earned / possible)
            weight = Decimal(str(_DEFAULT_WEIGHTS.get(category, 10)))
            weighted_sum += grade * weight
            weight_total += weight

    features["running_grade"] = (weighted_sum / weight_total) if weight_total else None
    features["missing_rate_pct"] = (
        Decimal(str(round((total_in_scope - total_scored) / total_in_scope * 100, 4))) if total_in_scope else None
    )

    if all(v is None for v in features.values()):
        return None
    return features


def build_import_preview(files, semester_label_fn=None):
    """`files` is an iterable of (file_name, uploaded_file) pairs. Returns
    a HistoricalImportPreview. `semester_label_fn` is a test hook; by
    default each file's own name (stem) is used as both the semester label
    and subject code — files are uploaded one-per-class, so the admin
    names the file accordingly (a stated simplification, see CLAUDE.md
    section 7)."""
    preview = HistoricalImportPreview()
    for file_name, uploaded_file in files:
        stem = file_name.rsplit(".", 1)[0]
        semester_label, subject_code = (semester_label_fn(stem) if semester_label_fn else (stem, stem))
        try:
            rows, skipped = parse_workbook(file_name, uploaded_file, semester_label, subject_code)
        except ValueError as exc:
            preview.skipped.append(SkippedRow(file_name, 0, str(exc)))
            continue
        preview.file_names.append(file_name)
        preview.records.extend(rows)
        preview.skipped.extend(skipped)

    preview.row_count = len(preview.records)
    preview.positive_count = sum(r["label"] for r in preview.records)
    return preview


def export_released_data_to_historical(user):
    """Admin action ("Add released semesters to training data") — masks
    every RELEASED/LOCKED GradeSheetEntry's data into HistoricalRecord the
    same way an uploaded file would. Labels come from the snapshot's
    final_grade/remarks (never live compute); features come from live
    AssessmentItem/Score data via forecasting.ml.features.extract_features
    — safe to read directly because editing locks once a sheet leaves
    DRAFT/RETURNED, and every item already carries a real AssessmentTerm
    (no chronological-quarter guessing needed here, unlike an uploaded old
    sheet)."""
    from approvals.models import GradeSheetEntry, GradeSheetStatus

    from .ml.features import extract_features
    from .models import HistoricalImportBatch, HistoricalRecord

    entries = GradeSheetEntry.objects.filter(
        sheet__status__in=[GradeSheetStatus.RELEASED, GradeSheetStatus.LOCKED]
    ).select_related(
        "roster_entry__class_offering__subject", "roster_entry__class_offering__semester", "roster_entry__student"
    )

    records = []
    skipped = []
    for entry in entries:
        roster_entry = entry.roster_entry
        identifier = roster_entry.student.id_number or str(roster_entry.student_id)
        masked_id = mask_identifier(identifier)

        if entry.remarks in ("DROPPED", "INC"):
            label = 1
        elif entry.final_grade is not None:
            label = 1 if entry.final_grade > Decimal("3.00") else 0
        else:
            skipped.append({"file": "live-export", "row": entry.pk, "reason": "No final grade to derive a label from"})
            continue

        for checkpoint in (Checkpoint.PRELIM, Checkpoint.MIDTERM):
            features = extract_features(roster_entry, checkpoint)
            if features is None:
                continue
            records.append(
                HistoricalRecord(
                    masked_id=masked_id,
                    semester_label=str(roster_entry.class_offering.semester),
                    subject_code=roster_entry.class_offering.subject.code,
                    checkpoint=checkpoint,
                    features_json={k: (str(v) if v is not None else None) for k, v in features.items()},
                    label=label,
                )
            )

    batch = HistoricalImportBatch.objects.create(
        uploaded_by=user,
        file_count=0,
        row_count=len(records),
        positive_count=sum(r.label for r in records),
        term_assignment_note="Exported from GradeTrack's own released/locked grade sheets — terms "
        "come from each item's real AssessmentTerm, not the chronological-quarter assumption used "
        "for uploaded sheets.",
        skipped_rows_json=skipped,
    )
    for record in records:
        record.batch = batch
    HistoricalRecord.objects.bulk_create(records)
    return batch


def commit_import(stashed, user):
    from .models import HistoricalImportBatch, HistoricalRecord

    batch = HistoricalImportBatch.objects.create(
        uploaded_by=user,
        file_count=len(stashed["file_names"]),
        row_count=stashed["row_count"],
        positive_count=stashed["positive_count"],
        skipped_rows_json=stashed["skipped"],
    )
    HistoricalRecord.objects.bulk_create(
        [
            HistoricalRecord(
                masked_id=r["masked_id"],
                semester_label=r["semester_label"],
                subject_code=r["subject_code"],
                checkpoint=r["checkpoint"],
                features_json=r["features_json"],
                label=r["label"],
                batch=batch,
            )
            for r in stashed["records"]
        ]
    )
    return batch
