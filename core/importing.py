"""Shared .xlsx/.csv parsing for every "upload a spreadsheet, preview, then
confirm" importer in the app (class list, bulk students, bulk instructors).
Each importer defines its own `build_preview`/`commit_import` on top of
`parse_spreadsheet_file` — the file-reading and header-matching logic is
identical across all of them, so it lives here once."""

import csv
import io

import openpyxl


class SpreadsheetImportError(Exception):
    pass


def _read_xlsx_rows(file_obj):
    workbook = openpyxl.load_workbook(file_obj, data_only=True)
    sheet = workbook.active
    return list(sheet.iter_rows(values_only=True))


def _read_csv_rows(file_obj):
    text = file_obj.read().decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text)))


def _normalize_header(cell):
    return str(cell or "").strip().lower()


def parse_spreadsheet_file(uploaded_file, required_headers, optional_headers=()):
    """Reads an uploaded .xlsx/.csv file and matches its header row against
    the given column names (case-insensitive). Returns (header_index_map,
    data_rows); raises SpreadsheetImportError on anything that stops the
    import before a single row is evaluated (wrong extension, empty file,
    missing required column)."""
    name = uploaded_file.name.lower()
    if name.endswith(".xlsx"):
        rows = _read_xlsx_rows(uploaded_file)
    elif name.endswith(".csv"):
        rows = _read_csv_rows(uploaded_file)
    else:
        raise SpreadsheetImportError("Only .xlsx or .csv files are supported.")

    if not rows:
        raise SpreadsheetImportError("The file is empty.")

    header = [_normalize_header(c) for c in rows[0]]
    index = {}
    for wanted in list(required_headers) + list(optional_headers):
        if wanted in header:
            index[wanted] = header.index(wanted)

    missing = [h for h in required_headers if h not in index]
    if missing:
        expected = ", ".join(h.title() for h in list(required_headers) + list(optional_headers))
        raise SpreadsheetImportError(
            f"Missing required column(s): {', '.join(h.title() for h in missing)}. Expected a header row with: {expected}."
        )

    return index, rows[1:]


def get_cell(row, index, key):
    idx = index.get(key)
    if idx is None or idx >= len(row):
        return ""
    return str(row[idx] or "").strip()
