#!/usr/bin/env python
"""Phase 8 part B — timed HTTP requests against a RUNNING CITCI GradeTrack
server, logged in as each role, plus a concurrency run. Pure `requests` +
`threading` — no Django import, no direct DB access, because this measures
what a real browser would experience (full HTTP + middleware + template
render), not what the ORM alone costs.

Usage (server must already be running, e.g. `python manage.py runserver`,
against a database seeded by `python manage.py seed_load_test`):

    python tools/perf_check.py --base-url http://127.0.0.1:8000 --auto
    python tools/perf_check.py --base-url http://127.0.0.1:8000 \\
        --class-id 42 --roster-entry-id 7 --item-id 3 --out docs/PERFORMANCE.md

`--auto` scrapes the admin Classes list once (logged in as the admin
account) to find the biggest current-semester class and one of its roster
entries/items — best-effort HTML parsing, not a stable API; pass the ids
explicitly if it doesn't find what you expect. Without `--auto` and without
explicit ids, the score-save and Class-Record-of-a-specific-class timings
are skipped (reported as "skipped — no class/item id") rather than guessed.

Prints a results table and a concurrency summary to stdout; pass --out to
also write a Markdown table (the shape docs/PERFORMANCE.md pastes in).
"""

import argparse
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

DEFAULT_ACCOUNTS = {
    "admin": "load_admin",
    "program_head": "load_head_1",
    "instructor": "load_instructor_1",
    "student": "load_student_0001",
}
DEFAULT_PASSWORD = "LoadTest@1234"


def login(base_url, username, password, timeout=15):
    session = requests.Session()
    login_url = f"{base_url}/accounts/login/"
    get_resp = session.get(login_url, timeout=timeout)
    get_resp.raise_for_status()
    match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', get_resp.text)
    if not match:
        raise RuntimeError(f"Could not find CSRF token on {login_url} — is the server running?")
    token = match.group(1)

    post_resp = session.post(
        login_url,
        data={"username": username, "password": password, "csrfmiddlewaretoken": token},
        headers={"Referer": login_url},
        timeout=timeout,
        allow_redirects=True,
    )
    if "/accounts/login/" in post_resp.url and post_resp.status_code == 200:
        raise RuntimeError(f"Login failed for {username!r} — check credentials or that seed_load_test has run.")
    return session


def csrf_token_from(session, base_url, page_path):
    resp = session.get(f"{base_url}{page_path}")
    match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', resp.text)
    return match.group(1) if match else None


def time_request(session, method, url, timeout=20, **kwargs):
    start = time.perf_counter()
    try:
        resp = session.request(method, url, timeout=timeout, **kwargs)
        elapsed = time.perf_counter() - start
        return elapsed, resp.status_code
    except requests.RequestException as exc:
        elapsed = time.perf_counter() - start
        return elapsed, f"error: {exc}"


def percentile(values, pct):
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * pct
    f, c = int(k), min(int(k) + 1, len(values) - 1)
    if f == c:
        return values[f]
    return values[f] + (k - f) * (values[c] - values[f])


def summarize(label, timings_and_statuses):
    timings = [t for t, _ in timings_and_statuses]
    statuses = [s for _, s in timings_and_statuses]
    bad = [s for s in statuses if not (isinstance(s, int) and 200 <= s < 400)]
    return {
        "label": label,
        "n": len(timings),
        "p50": statistics.median(timings) if timings else None,
        "p95": percentile(timings, 0.95),
        "max": max(timings) if timings else None,
        "errors": len(bad),
    }


def discover_targets(admin_session, base_url, academic_year_hint, instructor_session=None):
    """Best-effort: scrape the admin Classes list for the biggest
    current-semester class (highest "Students" column value whose
    Semester column mentions academic_year_hint), then its first roster
    entry + assessment item via the class grading page's Class Record
    tab. The grading page is fetched with `instructor_session` (falling
    back to `admin_session`) because the admin's own view of it is
    read-only (no hx-post cell markup) — an admin viewing someone else's
    class never gets edit controls. Returns a dict possibly missing keys
    if parsing fails."""
    targets = {}
    resp = admin_session.get(f"{base_url}/academics/classes/")
    rows = re.findall(r"<tr class=\"hover:bg-gray-50\">(.*?)</tr>", resp.text, re.DOTALL)
    best_pk, best_count = None, -1
    for row in rows:
        if academic_year_hint and academic_year_hint not in row:
            continue
        grading_href = re.search(r'href="/grading/classes/(\d+)/"', row)
        if not grading_href:
            continue
        cells = re.findall(r'class="px-4 py-3 text-gray-700">([^<]*)</td>', row)
        digit_cells = [c.strip() for c in cells if c.strip().isdigit()]
        count = int(digit_cells[-1]) if digit_cells else -1
        if count > best_count:
            best_count, best_pk = count, int(grading_href.group(1))

    if best_pk is None:
        return targets
    targets["class_id"] = best_pk

    grading_resp = (instructor_session or admin_session).get(f"{base_url}/grading/classes/{best_pk}/")
    cell_match = re.search(r'hx-post="[^"]*/grading/cells/(\d+)/(\d+)/save/"', grading_resp.text)
    if cell_match:
        targets["roster_entry_id"] = int(cell_match.group(1))
        targets["item_id"] = int(cell_match.group(2))
    return targets


KEY_PAGES = {
    "admin": [("Admin dashboard", "GET", "/dashboard/")],
    "program_head": [
        ("Program Head dashboard", "GET", "/dashboard/"),
        ("Approvals queue", "GET", "/approvals/"),
        ("Reports index", "GET", "/reports/"),
        ("At-Risk Students (program head)", "GET", "/forecasting/at-risk/"),
    ],
    "instructor": [
        ("Instructor dashboard", "GET", "/dashboard/"),
        ("Reports index", "GET", "/reports/"),
        ("At-Risk Students (instructor)", "GET", "/forecasting/at-risk/"),
    ],
    "student": [
        ("Student dashboard", "GET", "/dashboard/"),
        ("My Grades", "GET", "/grading/my-grades/"),
    ],
}


def run_role_pages(session, base_url, role, repeats):
    results = {}
    for label, method, path in KEY_PAGES.get(role, []):
        timings = [time_request(session, method, f"{base_url}{path}") for _ in range(repeats)]
        results[label] = summarize(label, timings)
    return results


def run_class_record_and_save(sessions, base_url, class_id, roster_entry_id, item_id, repeats):
    results = {}
    if class_id is None:
        results["Class Record (largest class)"] = {"label": "Class Record (largest class)", "skipped": "no class id"}
    else:
        # Admin can view any class's grading page read-only — avoids having
        # to know which instructor the discovered "largest class" belongs to.
        timings = [
            time_request(sessions["admin"], "GET", f"{base_url}/grading/classes/{class_id}/") for _ in range(repeats)
        ]
        results["Class Record (largest class)"] = summarize("Class Record (largest class)", timings)

    if roster_entry_id is None or item_id is None:
        results["Score cell save"] = {"label": "Score cell save", "skipped": "no roster_entry/item id"}
    else:
        save_url = f"{base_url}/grading/classes/{class_id}/"
        token = csrf_token_from(sessions["instructor"], base_url, f"/grading/classes/{class_id}/")
        cell_url = f"{base_url}/grading/cells/{roster_entry_id}/{item_id}/save/"
        timings = []
        for i in range(repeats):
            timings.append(
                time_request(
                    sessions["instructor"],
                    "POST",
                    cell_url,
                    data={"value": str(5 + (i % 3)), "csrfmiddlewaretoken": token},
                    headers={"Referer": save_url, "X-Requested-With": "XMLHttpRequest"},
                )
            )
        results["Score cell save"] = summarize("Score cell save", timings)
    return results


def print_table(rows):
    print(f"{'Page':<40} {'n':>4} {'p50 (ms)':>10} {'p95 (ms)':>10} {'max (ms)':>10} {'errors':>7}")
    print("-" * 85)
    for row in rows:
        if "skipped" in row:
            print(f"{row['label']:<40} {'skipped (' + row['skipped'] + ')':>45}")
            continue
        print(
            f"{row['label']:<40} {row['n']:>4} "
            f"{row['p50'] * 1000:>10.1f} {row['p95'] * 1000:>10.1f} {row['max'] * 1000:>10.1f} {row['errors']:>7}"
        )


def write_markdown(path, rows, concurrency_rows):
    with open(path, "w", encoding="utf-8") as f:
        f.write("| Page | n | p50 (ms) | p95 (ms) | max (ms) | errors |\n")
        f.write("|---|---|---|---|---|---|\n")
        for row in rows:
            if "skipped" in row:
                f.write(f"| {row['label']} | skipped ({row['skipped']}) | | | | |\n")
                continue
            f.write(
                f"| {row['label']} | {row['n']} | {row['p50'] * 1000:.1f} | "
                f"{row['p95'] * 1000:.1f} | {row['max'] * 1000:.1f} | {row['errors']} |\n"
            )
        f.write("\n### Concurrency run\n\n")
        f.write("| Concurrent users | n | p50 (ms) | p95 (ms) | max (ms) | errors |\n")
        f.write("|---|---|---|---|---|---|\n")
        for row in concurrency_rows:
            f.write(
                f"| {row['label']} | {row['n']} | {row['p50'] * 1000:.1f} | "
                f"{row['p95'] * 1000:.1f} | {row['max'] * 1000:.1f} | {row['errors']} |\n"
            )


def run_concurrency(base_url, accounts, password, concurrent_users, requests_per_user=3):
    """Each simulated user logs in once, then hits its own dashboard
    `requests_per_user` times — a realistic mixed-role burst, not one
    page hammered in isolation."""
    role_cycle = list(accounts.items())

    def one_user(index):
        role, username = role_cycle[index % len(role_cycle)]
        try:
            session = login(base_url, username, password)
        except Exception as exc:
            return [(0.0, f"login error: {exc}")]
        path = KEY_PAGES.get(role, [("Dashboard", "GET", "/dashboard/")])[0][2]
        return [time_request(session, "GET", f"{base_url}{path}") for _ in range(requests_per_user)]

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrent_users) as pool:
        all_results = list(pool.map(one_user, range(concurrent_users)))
    wall_time = time.perf_counter() - start

    flat = [item for sublist in all_results for item in sublist]
    summary = summarize(f"{concurrent_users} concurrent users", flat)
    summary["wall_time_s"] = wall_time
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--repeats", type=int, default=10, help="Requests per timed page (default 10).")
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--admin-user", default=DEFAULT_ACCOUNTS["admin"])
    parser.add_argument("--program-head-user", default=DEFAULT_ACCOUNTS["program_head"])
    parser.add_argument("--instructor-user", default=DEFAULT_ACCOUNTS["instructor"])
    parser.add_argument("--student-user", default=DEFAULT_ACCOUNTS["student"])
    parser.add_argument("--class-id", type=int, default=None)
    parser.add_argument("--roster-entry-id", type=int, default=None)
    parser.add_argument("--item-id", type=int, default=None)
    parser.add_argument("--auto", action="store_true", help="Best-effort auto-discover class/roster/item ids.")
    parser.add_argument("--academic-year-hint", default="2020", help="Substring to find the current load-test semester row (default matches seed_load_test).")
    parser.add_argument("--concurrency", type=int, nargs="*", default=[50, 100], help="Concurrent-user levels to test (default 50 100).")
    parser.add_argument("--out", default=None, help="Write a Markdown results table to this path.")
    args = parser.parse_args()

    accounts = {
        "admin": args.admin_user,
        "program_head": args.program_head_user,
        "instructor": args.instructor_user,
        "student": args.student_user,
    }

    print(f"Logging in as each role against {args.base_url} ...")
    sessions = {role: login(args.base_url, username, args.password) for role, username in accounts.items()}

    class_id, roster_entry_id, item_id = args.class_id, args.roster_entry_id, args.item_id
    if args.auto and class_id is None:
        print("Auto-discovering the largest current-semester class ...")
        found = discover_targets(sessions["admin"], args.base_url, args.academic_year_hint, instructor_session=sessions["instructor"])
        class_id = found.get("class_id", class_id)
        roster_entry_id = found.get("roster_entry_id", roster_entry_id)
        item_id = found.get("item_id", item_id)
        print(f"  class_id={class_id} roster_entry_id={roster_entry_id} item_id={item_id}")

    rows = []
    for role in ("admin", "program_head", "instructor", "student"):
        print(f"Timing {role} pages ...")
        rows.extend(run_role_pages(sessions[role], args.base_url, role, args.repeats).values())

    print("Timing Class Record + score save ...")
    rows.extend(run_class_record_and_save(sessions, args.base_url, class_id, roster_entry_id, item_id, args.repeats).values())

    print()
    print_table(rows)

    print()
    print("Running concurrency levels:", args.concurrency)
    concurrency_rows = []
    for level in args.concurrency:
        print(f"  {level} concurrent users ...")
        summary = run_concurrency(args.base_url, accounts, args.password, level)
        concurrency_rows.append(summary)
        print(
            f"    n={summary['n']} p50={summary['p50'] * 1000:.1f}ms p95={summary['p95'] * 1000:.1f}ms "
            f"max={summary['max'] * 1000:.1f}ms errors={summary['errors']} wall={summary['wall_time_s']:.1f}s"
        )

    if args.out:
        write_markdown(args.out, rows, concurrency_rows)
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    sys.exit(main())
