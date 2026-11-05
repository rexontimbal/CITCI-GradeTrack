#!/usr/bin/env python
"""Generates the machine-readable UAT questionnaire files referenced by
docs/UAT_QUESTIONNAIRE.md: a print-ready .docx and a Google-Forms-friendly
.csv per respondent version, under docs/uat/. The item bank is defined
once here so it can never drift from the three exports.

Usage:
    python tools/generate_uat_docs.py
"""

import csv
import os

CHAR_NAMES = {
    "FS": "Functional Suitability",
    "PE": "Performance Efficiency",
    "COMP": "Compatibility",
    "US": "Usability",
    "REL": "Reliability",
    "SEC": "Security",
    "MAIN": "Maintainability",
    "PORT": "Portability",
}

STUDENTS = {
    "FS": [
        "I can find my grades, GWA, and progress on the system without confusion.",
        "The grades and GWA I see match what I expect from my actual scores.",
        "The system clearly tells me whether a grade is official (released) or still unofficial (running).",
        'The forecast message I see (e.g. "needs your attention" / "on track") is helpful without being confusing or alarming.',
    ],
    "PE": [
        "Pages (dashboard, My Grades, Subject detail, My Progress) load quickly.",
        "The system responds quickly when I switch semesters or open a subject's detail page.",
        "I did not experience noticeable slowdowns or freezing while using the system.",
    ],
    "US": [
        "The system is easy to navigate without needing help.",
        "Menu items and page titles are clear and make sense to me.",
        "The system works well on my phone/tablet, not just a desktop computer.",
        "Charts and progress visuals are easy to understand.",
    ],
    "REL": [
        "The system is available whenever I need to check my grades.",
        "I have not encountered error pages or broken pages while using the system.",
        "My data (grades, progress) is consistent every time I log in — nothing seems to randomly change or disappear.",
    ],
    "SEC": [
        "I feel confident that only I can see my own grades.",
        "The login process (password, lockout after failed attempts) feels secure.",
        "I was asked to agree to a Data Privacy notice before using the system.",
    ],
}

STAFF = {
    "FS": [
        "The system lets me complete my actual tasks (encoding scores / approving grade sheets / "
        "managing accounts and academic setup) without needing a workaround.",
        "Computed grades (component grades, final grades, GWA) match what I expect from the formulas.",
        "The grade sheet submit/approve/release workflow matches how our department actually works.",
        "The at-risk/forecast information is specific enough to act on (which students, which class, why).",
    ],
    "PE": [
        "Pages I use often (Class Record, dashboards, Approvals, Reports, Teaching Loads) load quickly, "
        "even for a large class.",
        "Saving a score or submitting a grade sheet responds quickly, without a noticeable delay.",
        "Generating a PDF or Excel report does not take an unreasonable amount of time.",
    ],
    "US": [
        "The system is easy to learn without extensive training.",
        "The Class Record grid (encoding scores) is easy to use, including keyboard navigation.",
        "It's clear what to do next at each step of the grade-sheet workflow (draft, submit, return, "
        "approve, release).",
        "Error messages (e.g. a blocked instructor change, a missing score) clearly explain what's "
        "wrong and what to do about it.",
    ],
    "REL": [
        "The system is available when I need it, including during peak periods (e.g. grading deadlines).",
        "I have not lost work (unsaved scores, an in-progress form) due to a system error.",
        "Once grades are released or locked, they stay consistent — I trust the official record.",
    ],
    "SEC": [
        "I can only see and act on classes/students that are actually assigned to me or my program.",
        "Sensitive actions (grade correction, instructor override, account changes) are logged in a "
        "way I trust.",
        "The account lockout/password-change requirements feel appropriately secure, not excessive.",
    ],
}

IT_EXPERTS = {
    "FS": [
        "The implemented features match the documented requirements/proposal scope.",
        "Core computations (grading formula, GWA, forecasting features/label) are correctly and "
        "verifiably implemented (e.g. the hand-verified test cases in grading/tests.py).",
        "No functionality is missing that a grading-and-forecasting system of this scope should have.",
    ],
    "PE": [
        "Database queries are reasonably optimized (no obvious N+1 patterns) for the heaviest pages.",
        "Response times stay well under 2 seconds under realistic data volume (see docs/PERFORMANCE.md).",
        "Resource usage (DB connections, memory) is reasonable for the deployment target.",
    ],
    "COMP": [
        "The system runs correctly across modern browsers (Chrome, Firefox, Edge).",
        "The system does not conflict with other services on the same deployment (e.g. shares a "
        "Postgres instance safely, doesn't hard-code ports/paths that would collide).",
        "Data interchange (Excel import/export, PDF generation) is correct and round-trips cleanly.",
    ],
    "US": [
        "The UI follows consistent, predictable patterns across pages (shared CRUD, shared modal, "
        "shared table conventions).",
        "Accessibility basics (labels, contrast, keyboard navigation, landmark roles) are present — "
        "see docs/ACCESSIBILITY.md.",
        "The information architecture (sidebar, role-based menus) is logical for each role.",
    ],
    "REL": [
        "The test suite is comprehensive and the measured coverage (see docs/TEST_REPORT.md) is "
        "adequate for the code's risk level.",
        "Error handling is graceful — a failure in one subsystem (e.g. forecasting) does not break "
        "unrelated pages.",
        "The backup/restore tooling (backup_db/restore_db) is correct and usable.",
    ],
    "SEC": [
        "Authentication and session handling (password hashing, lockout, session expiry) follow "
        "reasonable security practice.",
        "Authorization is enforced server-side, not just hidden in the UI (role-based + object-level checks).",
        "Sensitive data (passwords, personal data used in forecasting) is handled appropriately "
        "(masked identifiers, no plaintext secrets in logs).",
        "Production settings (config/settings/prod.py) enforce secure defaults (HTTPS gating, secret "
        "key validation, security headers).",
    ],
    "MAIN": [
        "The codebase is modular (clear app boundaries) with minimal unnecessary coupling.",
        "Business logic lives in testable service functions, not scattered across views/templates.",
        "The code and CLAUDE.md documentation are sufficient for a new developer to understand and "
        "extend the system.",
        "The test suite would catch a regression if a future change broke existing behavior.",
    ],
    "PORT": [
        "The application can be deployed to a different environment (Ubuntu/Gunicorn/Nginx or "
        "Windows/Waitress/NSSM) using the documented steps without code changes.",
        "Configuration (secrets, hosts, feature flags) is externalized via environment variables, "
        "not hard-coded.",
        "The system has no unnecessary dependency on a specific OS or hosting provider.",
    ],
}

VERSIONS = [
    ("UAT_Students", "Students", STUDENTS),
    ("UAT_Staff", "Instructors / Program Heads / Admin", STAFF),
    ("UAT_ITExperts", "IT Experts / Technical Evaluators", IT_EXPERTS),
]


def items_with_codes(char_items):
    """char_items: {char_code: [text, ...]} -> [(item_code, char_code, text), ...]"""
    rows = []
    for char_code, texts in char_items.items():
        for i, text in enumerate(texts, start=1):
            rows.append((f"{char_code}{i}", char_code, text))
    return rows


def write_csv(filename, title, char_items):
    rows = items_with_codes(char_items)
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["item_code", "characteristic", "item_text", "scale"])
        for item_code, char_code, text in rows:
            writer.writerow([item_code, CHAR_NAMES[char_code], text, "1-5 (Strongly Disagree - Strongly Agree)"])


def write_docx(filename, title, char_items):
    from docx import Document
    from docx.shared import Pt

    document = Document()
    document.add_heading(f"CITCI GradeTrack — UAT Questionnaire ({title})", level=1)
    document.add_paragraph(
        "ISO/IEC 25010:2011. Scale: 1 = Strongly Disagree, 2 = Disagree, 3 = Neutral, 4 = Agree, "
        "5 = Strongly Agree. Responses are anonymous — see docs/UAT_QUESTIONNAIRE.md for the full "
        "respondent-info section and informed-consent paragraph."
    )

    for char_code, texts in char_items.items():
        document.add_heading(f"{CHAR_NAMES[char_code]} ({char_code})", level=2)
        table = document.add_table(rows=1, cols=3)
        table.style = "Light Grid Accent 1"
        header = table.rows[0].cells
        for cell, text in zip(header, ["Code", "Item", "1   2   3   4   5"]):
            cell.text = text
            for run in cell.paragraphs[0].runs:
                run.font.bold = True
                run.font.size = Pt(10)
        for i, text in enumerate(texts, start=1):
            row = table.add_row().cells
            row[0].text = f"{char_code}{i}"
            row[1].text = text
            row[2].text = "☐   ☐   ☐   ☐   ☐"
            for cell in row:
                for run in cell.paragraphs[0].runs:
                    run.font.size = Pt(10)

    document.save(filename)


def main():
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "uat")
    os.makedirs(out_dir, exist_ok=True)

    for slug, title, char_items in VERSIONS:
        csv_path = os.path.join(out_dir, f"{slug}.csv")
        write_csv(csv_path, title, char_items)
        print(f"Wrote {csv_path}")

        docx_path = os.path.join(out_dir, f"{slug}.docx")
        try:
            write_docx(docx_path, title, char_items)
            print(f"Wrote {docx_path}")
        except ImportError:
            print(f"python-docx not installed — skipped {docx_path}")


if __name__ == "__main__":
    main()
