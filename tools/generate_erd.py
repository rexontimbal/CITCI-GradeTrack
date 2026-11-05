#!/usr/bin/env python
"""Generates docs/ERD.md (a Mermaid erDiagram) and docs/DATA_DICTIONARY.md
(a Markdown table: App, Model, Field, Type, Null?, Description) straight
from the Django models — so they can never drift from the actual
migrations. Also writes a .docx twin of the data dictionary
(docs/DATA_DICTIONARY.docx) via python-docx, for pasting into the paper.

Usage:
    python tools/generate_erd.py

No database connection is used — this only introspects model metadata
(`Model._meta`), so it's safe to run against any environment/settings
module with the code checked out.
"""

import os
import sys

import django

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

from django.apps import apps  # noqa: E402
from django.db import models as djmodels  # noqa: E402

APP_LABELS = ["accounts", "academics", "grading", "approvals", "forecasting", "reports", "dashboard"]

TYPE_LABELS = {
    "AutoField": "bigint",
    "BigAutoField": "bigint",
    "CharField": "varchar",
    "TextField": "text",
    "BooleanField": "boolean",
    "DateField": "date",
    "DateTimeField": "timestamptz",
    "DecimalField": "decimal",
    "IntegerField": "int",
    "PositiveIntegerField": "int (unsigned)",
    "PositiveSmallIntegerField": "smallint (unsigned)",
    "JSONField": "jsonb",
    "ImageField": "varchar (path)",
    "EmailField": "varchar",
}


def type_label(field):
    internal = field.get_internal_type()
    return TYPE_LABELS.get(internal, internal.lower())


def collect_models():
    """Returns (tables, relations). tables[model_name] = {"app", "fields":
    [(name, type, nullable, description, key)]} — key is "PK"/"FK"/"".
    relations = [(from_model, to_model, kind, field_name)] — kind is "fk"
    or "m2m"."""
    tables = {}
    relations = []
    for label in APP_LABELS:
        for model in apps.get_app_config(label).get_models():
            name = model.__name__
            fields = []
            for f in model._meta.get_fields():
                if isinstance(f, djmodels.ManyToManyField):
                    relations.append((name, f.related_model.__name__, "m2m", f.name))
                    fields.append((f.name, "bigint", False, f"many-to-many -> {f.related_model.__name__}", ""))
                    continue
                if f.is_relation and f.concrete:
                    relations.append((name, f.related_model.__name__, "fk", f.name))
                    on_delete = getattr(f.remote_field, "on_delete", None)
                    on_delete_name = getattr(on_delete, "__name__", str(on_delete))
                    fields.append(
                        (
                            f"{f.name}_id",
                            "bigint",
                            f.null,
                            f"-> {f.related_model.__name__} (on_delete={on_delete_name})",
                            "FK",
                        )
                    )
                    continue
                if not getattr(f, "concrete", False) or f.is_relation:
                    continue  # reverse accessors / M2M reverse — covered from the other side
                description = getattr(f, "help_text", "") or ""
                if getattr(f, "choices", None):
                    description = (description + " " if description else "") + f"choices: {[c[0] for c in f.choices]}"
                key = "PK" if f.primary_key else ""
                fields.append((f.name, type_label(f), f.null, description, key))
            tables[name] = {"app": label, "fields": fields}
    return tables, relations


def sanitize_mermaid_id(name):
    return name


def write_erd_md(tables, relations, path):
    lines = ["```mermaid", "erDiagram"]
    seen_relation_lines = set()
    for from_model, to_model, kind, field_name in relations:
        # Skip relations into Django/axes internals (Group, Permission,
        # Session, ...) that aren't one of this project's own models — they
        # clutter the diagram with boxes that have no field list.
        if to_model not in tables or from_model not in tables:
            continue
        if kind == "fk":
            line = f'    {to_model} ||--o{{ {from_model} : "{field_name}"'
        else:
            line = f'    {from_model} }}o--o{{ {to_model} : "{field_name}"'
        if line not in seen_relation_lines:
            seen_relation_lines.add(line)
            lines.append(line)

    for model_name, data in tables.items():
        lines.append(f"    {model_name} {{")
        for field_name, ftype, _nullable, _desc, key in data["fields"]:
            safe_type = ftype.replace(" ", "_").replace("(", "").replace(")", "")
            suffix = f" {key}" if key else ""
            lines.append(f"        {safe_type} {field_name}{suffix}")
        lines.append("    }")
    lines.append("```")

    content = (
        "# CITCI GradeTrack — Entity Relationship Diagram\n\n"
        "Generated from the Django models (`tools/generate_erd.py`) — never hand-edited, so it can "
        "never drift from the actual migrations. Regenerate with `python tools/generate_erd.py` "
        "after any model change.\n\n" + "\n".join(lines) + "\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def write_data_dictionary_md(tables, path):
    lines = [
        "# CITCI GradeTrack — Data Dictionary",
        "",
        "Generated from the Django models (`tools/generate_erd.py`). A `.docx` twin lives alongside "
        "this file for pasting into the paper.",
        "",
        "| App | Model | Field | Type | Null? | Description |",
        "|---|---|---|---|---|---|",
    ]
    for model_name, data in tables.items():
        for field_name, ftype, nullable, description, key in data["fields"]:
            type_display = f"{ftype} ({key})" if key else ftype
            lines.append(
                f"| {data['app']} | {model_name} | {field_name} | {type_display} | "
                f"{'yes' if nullable else 'no'} | {description} |"
            )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def write_data_dictionary_docx(tables, path):
    from docx import Document
    from docx.shared import Pt

    document = Document()
    document.add_heading("CITCI GradeTrack — Data Dictionary", level=1)
    document.add_paragraph("Generated from the Django models (tools/generate_erd.py).")

    for model_name, data in tables.items():
        document.add_heading(f"{data['app']}.{model_name}", level=2)
        table = document.add_table(rows=1, cols=4)
        table.style = "Light Grid Accent 1"
        header = table.rows[0].cells
        for cell, text in zip(header, ["Field", "Type", "Null?", "Description"]):
            cell.text = text
            for run in cell.paragraphs[0].runs:
                run.font.bold = True
                run.font.size = Pt(10)
        for field_name, ftype, nullable, description, key in data["fields"]:
            row = table.add_row().cells
            row[0].text = field_name
            row[1].text = f"{ftype} ({key})" if key else ftype
            row[2].text = "yes" if nullable else "no"
            row[3].text = description
            for cell in row:
                for run in cell.paragraphs[0].runs:
                    run.font.size = Pt(9)

    document.save(path)


def main():
    docs_dir = os.path.join(PROJECT_ROOT, "docs")
    os.makedirs(docs_dir, exist_ok=True)

    tables, relations = collect_models()

    erd_path = os.path.join(docs_dir, "ERD.md")
    write_erd_md(tables, relations, erd_path)
    print(f"Wrote {erd_path} ({len(tables)} tables, {len(relations)} relationships)")

    dict_md_path = os.path.join(docs_dir, "DATA_DICTIONARY.md")
    write_data_dictionary_md(tables, dict_md_path)
    print(f"Wrote {dict_md_path}")

    dict_docx_path = os.path.join(docs_dir, "DATA_DICTIONARY.docx")
    try:
        write_data_dictionary_docx(tables, dict_docx_path)
        print(f"Wrote {dict_docx_path}")
    except ImportError:
        print("python-docx not installed — skipped DATA_DICTIONARY.docx (pip install -r requirements-dev.txt)")


if __name__ == "__main__":
    main()
