#!/usr/bin/env python
"""Phase 8 part B — axe-core accessibility audit via Playwright, run
against a LOCALLY RUNNING server with demo data seeded
(`seed_demo_users` + `seed_citci_academics`, which chains the grading/
student-portal/forecasting demo seeders).

Logs in as each of the four demo accounts (admin/program_head/instructor/
student, password Demo@1234) and visits every page from that role's
sidebar menu (accounts/menu.py) plus a few admin CRUD pages with their
"Add" modal opened, injects the vendored axe-core
(tools/axe/axe.min.js — `npm pack axe-core` then unpacked, not served to
the app, dev-tooling only), and runs axe.run() on each.

Usage:
    python manage.py runserver 127.0.0.1:8000 --noreload &
    python tools/accessibility_audit.py --base-url http://127.0.0.1:8000

Prints a summary grouped by impact (critical/serious/moderate/minor) and
writes the full JSON to --out (default tools/axe/results.json).
"""

import argparse
import json
import os
import sys

from playwright.sync_api import sync_playwright

AXE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "axe", "axe.min.js")

DEMO_PASSWORD = "Demo@1234"

# (role, username, [(label, path), ...]) — the pages a real session of
# that role can reach, drawn from accounts/menu.py plus a couple of
# object-detail pages that need a known id (seed_citci_academics' first
# class/section, which is pk=1 in a freshly-seeded dev database).
PAGES = {
    "admin": [
        ("Dashboard", "/dashboard/"),
        ("Academic Years & Semesters", "/academics/terms/"),
        ("Programs", "/academics/programs/"),
        ("Majors", "/academics/majors/"),
        ("Sections", "/academics/sections/"),
        ("Subjects", "/academics/subjects/"),
        ("Classes", "/academics/classes/"),
        ("Class Lists", "/academics/class-lists/"),
        ("Teaching Loads", "/academics/teaching-loads/"),
        ("Users", "/accounts/users/"),
        ("Grading Templates", "/grading/templates/"),
        ("Grade Sheets", "/approvals/admin/sheets/"),
        ("Forecast Model", "/forecasting/model/"),
        ("Historical Data", "/forecasting/historical/"),
        ("Reports", "/reports/"),
        ("Settings", "/reports/settings/"),
        ("Audit Log", "/accounts/audit-log/"),
        ("Profile", "/accounts/profile/"),
    ],
    "program_head": [
        ("Dashboard", "/dashboard/"),
        ("Classes", "/academics/program-head/classes/"),
        ("Teaching Loads", "/academics/teaching-loads/"),
        ("Grade Approvals", "/approvals/"),
        ("At-Risk Students", "/forecasting/at-risk/"),
        ("Reports", "/reports/"),
    ],
    "instructor": [
        ("Dashboard", "/dashboard/"),
        ("My Classes", "/academics/my-classes/"),
        ("Submitted Grades", "/approvals/submitted/"),
        ("At-Risk Students", "/forecasting/at-risk/"),
        ("Reports", "/reports/"),
    ],
    "student": [
        ("Dashboard", "/dashboard/"),
        ("My Grades", "/grading/my-grades/"),
        ("My Progress", "/grading/my-progress/"),
        ("Notifications", "/dashboard/notifications/"),
    ],
}

# Admin pages with an "Add" modal worth opening (button text, page path).
ADMIN_MODALS = [
    ("/academics/programs/", "Add Program"),
    ("/accounts/users/", "Add User"),
]


def login(page, base_url, username, password):
    page.goto(f"{base_url}/accounts/login/")
    page.fill('input[name="username"]', username)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"]')
    page.wait_for_load_state("load")


def run_axe(page):
    with open(AXE_PATH, encoding="utf-8") as f:
        axe_source = f.read()
    page.evaluate(axe_source)
    return page.evaluate(
        """() => axe.run(document, {
            resultTypes: ['violations'],
        })"""
    )


def audit_page(page, base_url, label, path, findings):
    url = f"{base_url}{path}"
    try:
        page.goto(url, wait_until="load", timeout=15000)
    except Exception as exc:
        findings.append({"page": label, "path": path, "error": str(exc)})
        return
    result = run_axe(page)
    for violation in result.get("violations", []):
        findings.append(
            {
                "page": label,
                "path": path,
                "rule": violation["id"],
                "impact": violation["impact"],
                "description": violation["description"],
                "help": violation["help"],
                "help_url": violation["helpUrl"],
                "nodes": len(violation["nodes"]),
                "targets": [n["target"] for n in violation["nodes"][:3]],
            }
        )


ROLES = ["admin", "program_head", "instructor", "student", "admin_modals"]

# Chromium is flaky in this sandboxed environment — a browser process
# doesn't reliably survive more than one role's worth of logins/
# navigations, so this script audits one role per invocation (--role) and
# appends to --out, rather than looping over every role in one process.
LAUNCH_ARGS = ["--disable-dev-shm-usage", "--no-sandbox", "--disable-gpu", "--disable-setuid-sandbox", "--no-zygote", "--no-first-run", "--disable-extensions", "--disable-background-timer-throttling"]


def audit_role(p, base_url, role):
    findings = []
    browser = p.chromium.launch(args=LAUNCH_ARGS)
    page = browser.new_page()
    if role == "admin_modals":
        login(page, base_url, "admin", DEMO_PASSWORD)
        for path, button_text in ADMIN_MODALS:
            print(f"Auditing [admin modal] {button_text} on {path} ...")
            try:
                page.goto(f"{base_url}{path}", wait_until="load", timeout=15000)
                page.get_by_role("button", name=button_text).click(timeout=10000)
                page.wait_for_timeout(800)
                result = run_axe(page)
                for violation in result.get("violations", []):
                    findings.append(
                        {
                            "page": f"admin modal: {button_text}",
                            "path": path,
                            "rule": violation["id"],
                            "impact": violation["impact"],
                            "description": violation["description"],
                            "help": violation["help"],
                            "help_url": violation["helpUrl"],
                            "nodes": len(violation["nodes"]),
                            "targets": [n["target"] for n in violation["nodes"][:3]],
                        }
                    )
            except Exception as exc:
                findings.append({"page": f"admin modal: {button_text}", "path": path, "error": str(exc)})
    else:
        login(page, base_url, role, DEMO_PASSWORD)
        for label, path in PAGES[role]:
            print(f"Auditing [{role}] {label} ({path}) ...")
            audit_page(page, base_url, f"{role}: {label}", path, findings)
    browser.close()
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "axe", "results.json"))
    parser.add_argument(
        "--role",
        choices=ROLES + ["all"],
        default="all",
        help="Audit just one role per invocation (recommended — see this script's docstring on "
        "Chromium stability). 'all' attempts every role in one process, which may crash partway.",
    )
    parser.add_argument("--append", action="store_true", help="Append to --out instead of overwriting it.")
    args = parser.parse_args()

    if not os.path.exists(AXE_PATH):
        print(f"axe-core not found at {AXE_PATH} — see this script's docstring.", file=sys.stderr)
        return 1

    roles_to_run = ROLES if args.role == "all" else [args.role]

    all_findings = []
    if args.append and os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as f:
            all_findings = json.load(f)

    with sync_playwright() as p:
        for role in roles_to_run:
            all_findings.extend(audit_role(p, args.base_url, role))

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(all_findings, f, indent=2)
    print(f"\nWrote {args.out}")

    by_impact = {"critical": [], "serious": [], "moderate": [], "minor": [], "error": []}
    for finding in all_findings:
        if "error" in finding:
            by_impact["error"].append(finding)
        else:
            by_impact.setdefault(finding["impact"] or "moderate", []).append(finding)

    print("\n=== Summary ===")
    for impact in ("critical", "serious", "moderate", "minor", "error"):
        items = by_impact[impact]
        print(f"{impact}: {len(items)}")
        for item in items:
            if impact == "error":
                print(f"  - {item['page']} ({item['path']}): {item['error']}")
            else:
                print(f"  - [{item['page']}] {item['rule']}: {item['help']} ({item['nodes']} node(s))")

    return 0


if __name__ == "__main__":
    sys.exit(main())
