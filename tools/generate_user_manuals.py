#!/usr/bin/env python
"""Phase 8 part B — captures real screenshots from seeded demo data
(Playwright) and assembles a step-by-step user manual per role as a
print-ready .docx (python-docx). Run against a LOCALLY RUNNING server
with demo data seeded (`seed_demo_users` + `seed_citci_academics`).

Usage:
    python manage.py runserver 127.0.0.1:8000 --noreload &
    python tools/generate_user_manuals.py --base-url http://127.0.0.1:8000 --role admin
    python tools/generate_user_manuals.py --base-url http://127.0.0.1:8000 --role program_head
    python tools/generate_user_manuals.py --base-url http://127.0.0.1:8000 --role instructor
    python tools/generate_user_manuals.py --base-url http://127.0.0.1:8000 --role student

(One role per invocation — see tools/accessibility_audit.py's docstring
on why; the same Chromium-process-per-role workaround is used here.)

Writes docs/manuals/screenshots/<role>/*.png and docs/manuals/
<Role>_Manual.docx. A PDF twin can be produced by opening the .docx in
Word/LibreOffice and exporting — no PDF conversion is attempted here (no
headless Word/LibreOffice available in this environment; see the
"Reproducing" note in the manual itself).
"""

import argparse
import os
import sys

from playwright.sync_api import sync_playwright

DEMO_PASSWORD = "Demo@1234"

# A class/roster-entry known to exist in a freshly-seeded dev database
# (seed_citci_academics -> seed_grading_demo / seed_student_portal_demo).
# Override with --class-id/--roster-entry-id if your seed produced
# different ids.
DEFAULT_CLASS_ID = 20
DEFAULT_ROSTER_ENTRY_ID = 1

# (role, username, manual title, [(step title, instruction, path), ...])
MANUALS = {
    "admin": (
        "admin",
        "Admin Manual",
        [
            (
                "1. Logging in",
                "Go to the login page and sign in with your admin username and password. "
                "First-time accounts are forced to change their password and accept the Data "
                "Privacy notice before reaching any other page.",
                "/accounts/login/",
            ),
            (
                "2. Dashboard",
                "After logging in, the Dashboard shows live counts of active students, "
                "instructors, classes, and programs — not placeholder data.",
                "/dashboard/",
            ),
            (
                "3. Managing users",
                "Users -> tabs for Admins/Program Heads/Instructors/Students, with search and "
                "filters. Use 'Add' to create an account, or the bulk import for students/"
                "instructors from a spreadsheet.",
                "/accounts/users/",
            ),
            (
                "4. Managing classes",
                "Academic Setup -> Classes lists every class offering for the active semester, "
                "with filters by program/semester/instructor.",
                "/academics/classes/",
            ),
            (
                "5. Teaching Loads",
                "Academic Setup -> Teaching Loads shows per-instructor totals (classes, units, "
                "students) for the active semester, plus any unassigned classes. Admin can "
                "override an instructor assignment from the Classes page, logged as an override.",
                "/academics/teaching-loads/",
            ),
            (
                "6. Grading templates",
                "Management -> Grading Templates: the CITCI Default template and its components, "
                "including the school-locked Examination weight.",
                "/grading/templates/",
            ),
            (
                "7. Grade Sheets oversight",
                "Management -> Grade Sheets: every grade sheet in the active semester with a "
                "submission/approval/release progress summary, and a 'Lock Term' action.",
                "/approvals/admin/sheets/",
            ),
            (
                "8. Forecast Model",
                "Management -> Forecast Model: metrics (accuracy/precision/recall/F1/ROC-AUC), "
                "the threshold trade-off table, and version history with an Activate action.",
                "/forecasting/model/",
            ),
            (
                "9. Reports",
                "Reports: system-wide submission status, class performance, and failing/INC "
                "lists, each exportable to Excel.",
                "/reports/",
            ),
        ],
    ),
    "program_head": (
        "program_head",
        "Program Head Manual",
        [
            ("1. Logging in", "Sign in with your Program Head account.", "/accounts/login/"),
            (
                "2. Dashboard",
                "The dashboard shows at-risk student counts and an 'Unassigned Classes' card for "
                "your program(s), linking straight to the filtered list.",
                "/dashboard/",
            ),
            (
                "3. Assigning teaching loads",
                "Classes shows every class under your program(s). Use 'Assign/Change Instructor' "
                "per class, the 'Unassigned only' filter, and the bulk-assign action for several "
                "classes at once.",
                "/academics/program-head/classes/",
            ),
            (
                "4. Teaching Loads summary",
                "Per-instructor totals (classes, units, students) for your program(s), plus any "
                "classes still unassigned.",
                "/academics/teaching-loads/",
            ),
            (
                "5. Grade Approvals",
                "Review a submitted grade sheet's frozen snapshot, class distribution chart, and "
                "transition timeline, then Approve, Return (with remarks), or Release.",
                "/approvals/",
            ),
            (
                "6. At-Risk Students",
                "Summary cards (at risk/watch/classes affected/interventions), a by-class "
                "breakdown, and the same student-level detail instructors see.",
                "/forecasting/at-risk/",
            ),
        ],
    ),
    "instructor": (
        "instructor",
        "Instructor Manual",
        [
            ("1. Logging in", "Sign in with your instructor account.", "/accounts/login/"),
            (
                "2. My Classes",
                "Every class assigned to you for the active semester. Click 'Encode Grades' to "
                "open a class's grading page.",
                "/academics/my-classes/",
            ),
            (
                "3. Setup tab — grading components",
                "Add/rename/reweight your own (unlocked) grading components; the school-locked "
                "Examination weight is shown read-only.",
                f"/grading/classes/{{class_id}}/",
            ),
            (
                "4. Submitted Grades",
                "Your own grade sheets across the active semester, filterable by status.",
                "/approvals/submitted/",
            ),
            (
                "5. At-Risk Students",
                "Students flagged at-risk or watch across your classes, with plain-language "
                "reasons and an intervention log.",
                "/forecasting/at-risk/",
            ),
            ("6. Reports", "Per-class PDF/Excel grade-sheet exports.", "/reports/"),
        ],
    ),
    "student": (
        "student",
        "Student Manual",
        [
            ("1. Logging in", "Sign in with your student number/username and password.", "/accounts/login/"),
            (
                "2. Dashboard",
                "Your subjects this term, Official/Partial GWA, and a supportive forecast card "
                "(never a number, never the words 'at risk') when enabled.",
                "/dashboard/",
            ),
            (
                "3. My Grades",
                "A semester selector, your grades per subject, and total units + GWA — official "
                "once released, clearly marked 'Unofficial' before that.",
                "/grading/my-grades/",
            ),
            (
                "4. Subject detail",
                "Component breakdown, item list by grading period, and progression charts for one "
                "subject.",
                "/grading/my-grades/{roster_entry_id}/",
            ),
            (
                "5. My Progress",
                "A GWA-history line chart across every semester, plus the current semester's "
                "subjects by grade.",
                "/grading/my-progress/",
            ),
        ],
    ),
}


def login(page, base_url, username, password):
    page.goto(f"{base_url}/accounts/login/")
    page.fill('input[name="username"]', username)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"]')
    page.wait_for_load_state("load")


def capture_role(p, base_url, role, class_id, roster_entry_id, out_dir):
    username, title, steps = MANUALS[role]
    screenshots_dir = os.path.join(out_dir, "screenshots", role)
    os.makedirs(screenshots_dir, exist_ok=True)

    browser = p.chromium.launch(
        args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-gpu", "--disable-setuid-sandbox", "--no-zygote", "--no-first-run"]
    )
    page = browser.new_page(viewport={"width": 1366, "height": 900})
    login(page, base_url, username, DEMO_PASSWORD)

    captured = []
    for step_title, instruction, path_template in steps:
        path = path_template.format(class_id=class_id, roster_entry_id=roster_entry_id)
        print(f"Capturing [{role}] {step_title} ({path}) ...")
        try:
            page.goto(f"{base_url}{path}", wait_until="load", timeout=15000)
            page.wait_for_timeout(400)
            filename = f"{len(captured) + 1:02d}.png"
            screenshot_path = os.path.join(screenshots_dir, filename)
            page.screenshot(path=screenshot_path, full_page=True)
            captured.append((step_title, instruction, screenshot_path))
        except Exception as exc:
            print(f"  skipped (error: {exc})")
    browser.close()
    return title, captured


def write_manual_docx(title, steps, out_path):
    from docx import Document
    from docx.shared import Inches, Pt

    document = Document()
    document.add_heading(f"CITCI GradeTrack — {title}", level=1)
    document.add_paragraph(
        "Screenshots captured automatically from seeded demo data (tools/generate_user_manuals.py). "
        "Account names and sample data shown are demo content, not real CITCI records."
    )

    for step_title, instruction, screenshot_path in steps:
        document.add_heading(step_title, level=2)
        p = document.add_paragraph(instruction)
        p.paragraph_format.space_after = Pt(6)
        if os.path.exists(screenshot_path):
            document.add_picture(screenshot_path, width=Inches(6.0))

    document.save(out_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--role", choices=list(MANUALS) + ["all"], default="all")
    parser.add_argument("--class-id", type=int, default=DEFAULT_CLASS_ID)
    parser.add_argument("--roster-entry-id", type=int, default=DEFAULT_ROSTER_ENTRY_ID)
    parser.add_argument("--out-dir", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "manuals"))
    args = parser.parse_args()

    roles = list(MANUALS) if args.role == "all" else [args.role]
    os.makedirs(args.out_dir, exist_ok=True)

    with sync_playwright() as p:
        for role in roles:
            title, captured = capture_role(p, args.base_url, role, args.class_id, args.roster_entry_id, args.out_dir)
            steps = [(t, i, s) for t, i, s in captured]
            docx_path = os.path.join(args.out_dir, f"{title.replace(' ', '_')}.docx")
            write_manual_docx(title, steps, docx_path)
            print(f"Wrote {docx_path} ({len(steps)} steps)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
