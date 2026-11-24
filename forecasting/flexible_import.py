"""Flexible historical-data import -- accepts an arbitrary CSV/Excel export,
unlike historical_import.py's rigid single known layout (CITCI's raw
template or this system's own Class Record export). Used only as a
fallback when a file doesn't match that known shape (see
historical_import.looks_like_known_template and views.py's dispatch) --
the rigid parser is untouched.

Never silently guesses a column's meaning and commits on it: suggest_columns
only ever produces a *suggestion*, pre-filled into a dropdown on the
mapping-confirm screen; validate_mapping blocks the whole commit if
anything is left ambiguous (no Final Grade column, a score column with no
term, and so on). This mirrors reports/excel_import.py's established
suggest-then-confirm pattern rather than inventing a new one.

Every mapped score column must carry an EXPLICIT term chosen by the admin
-- unlike historical_import.py's rigid scanner, this module never guesses
a term from column position (no "quarter the columns" fallback here). The
leakage guard itself still lives in one place,
historical_import.compute_checkpoint_features, which both this module and
the rigid scanner feed into.
"""

import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal

import pandas as pd

from grading.models import ASSESSMENT_TERM_ORDER, AssessmentTerm, ComponentCategory

from .historical_import import SkippedRow, compute_checkpoint_features, compute_label, mask_identifier
from .ml.features import FEATURE_NAMES
from .models import Checkpoint, HistoricalRecord

MAX_ROWS_PER_FILE = 2000

# Matches HistoricalRecord's own field limits -- read off the model so this
# never silently drifts out of sync with a future migration. A value this
# long (a whole file name instead of a short code) almost always means no
# Semester/Subject column was mapped and no fallback text was typed in;
# truncating here turns what would otherwise be a 500 at commit time
# (StringDataRightTruncation) into a usable, if imperfect, label instead.
_SEMESTER_LABEL_MAX_LENGTH = HistoricalRecord._meta.get_field("semester_label").max_length
_SUBJECT_CODE_MAX_LENGTH = HistoricalRecord._meta.get_field("subject_code").max_length


class ColumnRole:
    IGNORE = "IGNORE"
    ID = "ID"
    NAME = "NAME"
    SEMESTER_LABEL = "SEMESTER_LABEL"
    SUBJECT_CODE = "SUBJECT_CODE"
    SCORE = "SCORE"
    RUNNING_GRADE = "RUNNING_GRADE"
    FINAL_GRADE = "FINAL_GRADE"
    REMARKS = "REMARKS"

    CHOICES = [
        (IGNORE, "Ignore this column"),
        (ID, "Student ID"),
        (NAME, "Student name"),
        (SEMESTER_LABEL, "Semester label"),
        (SUBJECT_CODE, "Subject code"),
        (SCORE, "Score (pick a category and term below)"),
        (RUNNING_GRADE, "Periodic running grade, 1.00 to 5.00 (pick a term below)"),
        (FINAL_GRADE, "Final grade (used as the at-risk label)"),
        (REMARKS, "Remarks (Passed/Failed/INC/Dropped)"),
    ]


SCORE_KIND_RAW = "RAW"
SCORE_KIND_PERCENT = "PERCENT"
SCORE_KIND_CHOICES = [
    (SCORE_KIND_RAW, "Raw score (enter a max score)"),
    (SCORE_KIND_PERCENT, "Already a percentage, 0 to 100"),
]

_REMARKS_TOKENS = {"PASSED", "FAILED", "INC", "DROPPED", "DRP"}


def _normalize(text):
    return re.sub(r"\s+", " ", str(text).strip().lower())


def _suggest_role(header_text):
    """Keyword-based guess at a column's role, checked in a fixed priority
    order so e.g. "Final Grade" (the label column) is never mistaken for a
    "Final Exam" score column (an EXAM-category score). Returns
    (role, category_or_None) -- never raises, falls back to IGNORE."""
    text = _normalize(header_text)

    if "remarks" in text or text == "status" or "status" in text:
        return ColumnRole.REMARKS, None
    if re.search(r"\bid\b", text) or "id number" in text or "id no" in text or "student id" in text or "lrn" in text or "learner reference" in text:
        return ColumnRole.ID, None
    if "name" in text:
        return ColumnRole.NAME, None
    if "grade" in text or re.search(r"\bfg\b", text):
        if "semifinal" in text or "semi-final" in text or "semi final" in text:
            return ColumnRole.RUNNING_GRADE, None
        if "midterm" in text or "mid-term" in text or "mid term" in text:
            return ColumnRole.RUNNING_GRADE, None
        if "prelim" in text:
            return ColumnRole.RUNNING_GRADE, None
        # Bare "grade" or "final grade" with no other period keyword --
        # treated as the overall/final grade column, the label source.
        return ColumnRole.FINAL_GRADE, None
    if "attendance" in text:
        return ColumnRole.SCORE, ComponentCategory.ATTENDANCE
    if "quiz" in text:
        return ColumnRole.SCORE, ComponentCategory.QUIZ
    if "recitation" in text or "participation" in text:
        return ColumnRole.SCORE, ComponentCategory.RECITATION
    if "project" in text or "performance task" in text or "activity" in text or "output" in text:
        return ColumnRole.SCORE, ComponentCategory.PROJECT
    if "exam" in text or "test" in text:
        return ColumnRole.SCORE, ComponentCategory.EXAM
    if "semester" in text or "school year" in text or "academic year" in text:
        return ColumnRole.SEMESTER_LABEL, None
    if "subject" in text or "course code" in text:
        return ColumnRole.SUBJECT_CODE, None
    return ColumnRole.IGNORE, None


def _detect_term(header_text):
    """A term is only ever suggested from the header TEXT itself (e.g. it
    literally says "Midterm Exam") -- never guessed from column position,
    unlike historical_import.py's rigid-path quarter-split fallback."""
    text = _normalize(header_text)
    if "semifinal" in text or "semi-final" in text or "semi final" in text:
        return AssessmentTerm.SEMIFINAL
    if "midterm" in text or "mid-term" in text or "mid term" in text:
        return AssessmentTerm.MIDTERM
    if "prelim" in text:
        return AssessmentTerm.PRELIM
    if "final" in text:
        return AssessmentTerm.FINAL
    return None


def _value_range_hint(values):
    """Sniffs up to the given sample values for a human-readable hint,
    shown next to the suggested-role dropdown so an admin can sanity-check
    it visually. Only drives a role suggestion (in suggest_columns) when
    the keyword match found nothing -- never overrides a keyword match."""
    if not values:
        return None, None
    numeric = []
    for v in values:
        try:
            numeric.append(float(v))
        except (TypeError, ValueError):
            pass
    if len(numeric) >= max(1, int(len(values) * 0.8)):
        lo, hi = min(numeric), max(numeric)
        has_decimal = any(n != int(n) for n in numeric)
        if hi <= 5.5 and has_decimal:
            return "grade", f"Looks like a CITCI grade ({lo:.2f} to {hi:.2f})"
        if 0 <= lo and hi <= 100:
            return "percent", f"Looks like a percentage or raw score ({lo:.0f} to {hi:.0f})"
        return "numeric", f"Numeric values ({lo:.2f} to {hi:.2f})"
    upper_values = {str(v).strip().upper() for v in values}
    if upper_values and upper_values <= _REMARKS_TOKENS:
        return "remarks", "Looks like remarks/status text"
    return None, None


@dataclass
class ColumnCandidate:
    index: int
    header_text: str
    suggested_role: str = ColumnRole.IGNORE
    suggested_category: str | None = None
    suggested_term: str | None = None
    suggested_kind: str | None = None
    sample_values: list = field(default_factory=list)
    value_range_hint: str | None = None

    def to_dict(self):
        return asdict(self)


def read_table(file_name, uploaded_file):
    """Reads an arbitrary CSV or Excel file into a pandas DataFrame, row 1
    as the header -- no scanning for where the real header starts (that is
    what the instructions screen asks the admin to ensure beforehand).
    Everything is read as plain strings so numeric parsing stays explicit
    later, never silently coerced by pandas' own type inference. Raises
    ValueError for a file this can't make sense of at all."""
    lower = file_name.lower()
    try:
        if lower.endswith(".csv"):
            df = pd.read_csv(uploaded_file, header=0, dtype=str, keep_default_na=False)
        else:
            df = pd.read_excel(uploaded_file, header=0, engine="openpyxl", dtype=str)
    except Exception as exc:
        raise ValueError(f"Could not read {file_name} as a table: {exc}") from exc
    df = df.fillna("")
    if df.shape[1] == 0:
        raise ValueError(f"{file_name} has no columns to read.")
    if len(df) > MAX_ROWS_PER_FILE:
        raise ValueError(f"{file_name} has {len(df)} rows. Please split it into files of {MAX_ROWS_PER_FILE} rows or fewer.")
    return df


def suggest_columns(df):
    """Pure function, no DB/session writes -- one ColumnCandidate per
    DataFrame column, each a suggestion only.

    A SCORE/Running-Grade column always gets a *suggested* term and kind,
    never left blank: if the header itself doesn't name a period (e.g.
    plain "Quiz Avg", not "Prelim Quiz"), it defaults to Prelim rather
    than forcing the admin to pick one for every such column -- the
    common case (one column per category) then needs no editing at all.
    Kind defaults to "already a percentage" when the sampled values sit
    in 0-100, else "raw score" (which still needs a max score typed in,
    since there's no way to guess one). Every suggestion stays visible
    and editable on the confirm screen -- nothing here is final until the
    admin reviews it."""
    candidates = []
    for i, col in enumerate(df.columns):
        header_text = str(col).strip()
        non_blank = [str(v) for v in df[col].tolist() if str(v).strip() != ""]
        sample = non_blank[:30]
        role, category = _suggest_role(header_text)
        hint_key, hint_label = _value_range_hint(sample)
        if role == ColumnRole.IGNORE:
            if hint_key == "grade":
                role = ColumnRole.FINAL_GRADE
            elif hint_key == "remarks":
                role = ColumnRole.REMARKS

        term = None
        kind = None
        if role in (ColumnRole.SCORE, ColumnRole.RUNNING_GRADE):
            term = _detect_term(header_text) or AssessmentTerm.PRELIM
        if role == ColumnRole.SCORE:
            kind = SCORE_KIND_PERCENT if hint_key == "percent" else SCORE_KIND_RAW

        candidates.append(
            ColumnCandidate(
                index=i,
                header_text=header_text,
                suggested_role=role,
                suggested_category=category,
                suggested_term=term,
                suggested_kind=kind,
                sample_values=sample[:5],
                value_range_hint=hint_label,
            )
        )
    return candidates


def build_file_payload(file_name, df, candidates, semester_fallback, subject_fallback):
    """JSON-safe dict stashed in the session between the upload step and
    the mapping-confirm step -- enough to reconstruct the table without
    re-uploading the file. Sessions are DB-backed in this project (no
    SESSION_ENGINE override), so this comfortably fits CITCI's realistic
    class sizes; read_table's MAX_ROWS_PER_FILE cap keeps it that way."""
    return {
        "file_name": file_name,
        "header": [str(c) for c in df.columns],
        "rows": df.astype(str).values.tolist(),
        "columns": [c.to_dict() for c in candidates],
        "semester_fallback": semester_fallback,
        "subject_fallback": subject_fallback,
    }


@dataclass
class ColumnMapping:
    index: int
    role: str
    category: str | None = None
    term: str | None = None
    kind: str | None = None
    max_score: float | None = None


def parse_mapping_from_post(files_payload, post_data):
    """Rebuilds {file_index: {col_index: ColumnMapping}} from the
    mapping-confirm form's POST data. Field naming mirrors
    reports/excel_import.py's "newitem-{col}-..." convention:
    col-{fi}-{ci}-role / -category / -term / -kind / -max_score."""
    mapping = {}
    for fi, file_payload in enumerate(files_payload):
        file_mapping = {}
        for ci in range(len(file_payload["header"])):
            prefix = f"col-{fi}-{ci}-"
            role = post_data.get(prefix + "role", ColumnRole.IGNORE)
            if role == ColumnRole.IGNORE or not role:
                continue
            category = post_data.get(prefix + "category") or None
            term = post_data.get(prefix + "term") or None
            kind = post_data.get(prefix + "kind") or None
            max_score_raw = post_data.get(prefix + "max_score") or None
            max_score = None
            if max_score_raw:
                try:
                    max_score = float(max_score_raw)
                except ValueError:
                    max_score = None  # caught as invalid by validate_mapping
            file_mapping[ci] = ColumnMapping(index=ci, role=role, category=category, term=term, kind=kind, max_score=max_score)
        mapping[fi] = file_mapping
    return mapping


def validate_mapping(files_payload, mapping):
    """Returns a list of (file_name, message) errors. Non-empty errors
    must block the whole batch's commit -- never a partial one, matching
    reports/excel_import.py's validate_new_item_decisions contract."""
    errors = []
    for fi, file_payload in enumerate(files_payload):
        file_name = file_payload["file_name"]
        header = file_payload["header"]
        file_mapping = mapping.get(fi, {})
        roles = [cm.role for cm in file_mapping.values()]

        if ColumnRole.ID not in roles and ColumnRole.NAME not in roles:
            errors.append((file_name, "Pick a column for Student ID or Student Name so students can be identified."))

        final_grade_count = roles.count(ColumnRole.FINAL_GRADE)
        if final_grade_count == 0:
            errors.append((file_name, "Pick exactly one column for Final Grade. It is used as the at-risk label."))
        elif final_grade_count > 1:
            errors.append((file_name, "More than one column is mapped to Final Grade. Pick only one."))

        seen_category_term = set()
        for cm in file_mapping.values():
            col_label = header[cm.index] if cm.index < len(header) else f"column {cm.index + 1}"
            if cm.role == ColumnRole.SCORE:
                if not cm.term:
                    errors.append((file_name, f'"{col_label}" needs a term (Prelim, Midterm, Semi-Final, or Final).'))
                    continue
                if not cm.category:
                    errors.append((file_name, f'"{col_label}" needs a category before it can be used.'))
                    continue
                key = (cm.category, cm.term)
                if key in seen_category_term:
                    errors.append((file_name, f'More than one column is mapped to the same category and term as "{col_label}". Pick only one.'))
                seen_category_term.add(key)
                if cm.kind == SCORE_KIND_RAW:
                    if not cm.max_score or cm.max_score < 1:
                        errors.append((file_name, f'"{col_label}" is a raw score. Enter a max score of at least 1.'))
                elif cm.kind != SCORE_KIND_PERCENT:
                    errors.append((file_name, f'"{col_label}" needs a kind: raw score or already a percentage.'))
            elif cm.role == ColumnRole.RUNNING_GRADE:
                if not cm.term:
                    errors.append((file_name, f'"{col_label}" needs a term (Prelim, Midterm, or Semi-Final) before it can be used.'))

    return errors


def _parse_float(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _direct_running_grade(running_grade_cols, row, checkpoint):
    """A mapped periodic running-grade column (e.g. "Prelim Grade") is a
    direct passthrough for that term's running_grade feature, bypassing
    the weighted-category computation entirely -- it IS the already-
    computed grade for that period. Picks the latest term at or before
    `checkpoint` when more than one such column is mapped."""
    cutoff = ASSESSMENT_TERM_ORDER[checkpoint]
    candidates = []
    for ci, cm in running_grade_cols:
        if not cm.term or ASSESSMENT_TERM_ORDER[cm.term] > cutoff:
            continue
        value = _parse_float(row[ci])
        if value is not None:
            candidates.append((ASSESSMENT_TERM_ORDER[cm.term], value))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0])
    return Decimal(str(candidates[-1][1]))


def build_flexible_preview(files_payload, mapping):
    """Builds the exact same stashed-preview dict shape
    historical_import.HistoricalImportPreview.to_session() already
    produces (file_names, row_count, positive_count, records, skipped), so
    historical_import_confirm/commit_import need zero changes regardless
    of which path produced it."""
    file_names = []
    records = []
    skipped = []

    for fi, file_payload in enumerate(files_payload):
        file_name = file_payload["file_name"]
        rows = file_payload["rows"]
        file_mapping = mapping.get(fi, {})
        file_names.append(file_name)

        id_col = next((ci for ci, cm in file_mapping.items() if cm.role == ColumnRole.ID), None)
        name_col = next((ci for ci, cm in file_mapping.items() if cm.role == ColumnRole.NAME), None)
        final_grade_col = next((ci for ci, cm in file_mapping.items() if cm.role == ColumnRole.FINAL_GRADE), None)
        remarks_col = next((ci for ci, cm in file_mapping.items() if cm.role == ColumnRole.REMARKS), None)
        semester_col = next((ci for ci, cm in file_mapping.items() if cm.role == ColumnRole.SEMESTER_LABEL), None)
        subject_col = next((ci for ci, cm in file_mapping.items() if cm.role == ColumnRole.SUBJECT_CODE), None)
        score_cols = [(ci, cm) for ci, cm in file_mapping.items() if cm.role == ColumnRole.SCORE]
        running_grade_cols = [(ci, cm) for ci, cm in file_mapping.items() if cm.role == ColumnRole.RUNNING_GRADE]

        semester_fallback = file_payload.get("semester_fallback") or file_name
        subject_fallback = file_payload.get("subject_fallback") or file_name

        for row_index, row in enumerate(rows, start=1):
            id_value = row[id_col].strip() if id_col is not None else ""
            name_value = row[name_col].strip() if name_col is not None else ""
            identifier = id_value or name_value
            if not identifier:
                skipped.append(SkippedRow(file_name, row_index, "No ID or Name value. Can't identify this row."))
                continue

            final_grade = _parse_float(row[final_grade_col]) if final_grade_col is not None else None
            remarks = row[remarks_col].strip().upper() if remarks_col is not None else ""

            label = compute_label(final_grade, remarks)
            if label is None:
                skipped.append(SkippedRow(file_name, row_index, "No readable Final Grade or Remarks. Can't determine a label."))
                continue

            masked_id = mask_identifier(identifier)
            semester_label = ((row[semester_col].strip() if semester_col is not None else "") or semester_fallback)[:_SEMESTER_LABEL_MAX_LENGTH]
            subject_code = ((row[subject_col].strip() if subject_col is not None else "") or subject_fallback)[:_SUBJECT_CODE_MAX_LENGTH]

            items = []
            for ci, cm in score_cols:
                value = _parse_float(row[ci])
                if cm.kind == SCORE_KIND_PERCENT:
                    earned, possible = value, 100.0
                else:
                    earned, possible = value, cm.max_score
                items.append((cm.category, cm.term, earned, possible))

            for checkpoint in (Checkpoint.PRELIM, Checkpoint.MIDTERM):
                features = compute_checkpoint_features(items, checkpoint)
                direct_grade = _direct_running_grade(running_grade_cols, row, checkpoint)
                if features is None and direct_grade is None:
                    continue
                if features is None:
                    features = dict.fromkeys(FEATURE_NAMES)
                if direct_grade is not None:
                    features["running_grade"] = direct_grade
                records.append(
                    {
                        "masked_id": masked_id,
                        "semester_label": semester_label,
                        "subject_code": subject_code,
                        "checkpoint": checkpoint,
                        "features_json": {k: (str(v) if v is not None else None) for k, v in features.items()},
                        "label": label,
                    }
                )

    return {
        "file_names": file_names,
        "row_count": len(records),
        "positive_count": sum(r["label"] for r in records),
        "records": records,
        "skipped": [asdict(s) for s in skipped],
        "flexible": True,
    }
