# Accessibility Audit — Phase 8 part B

## Method

`tools/accessibility_audit.py` (Playwright, vendored `axe-core` 4.14.0 — `npm pack axe-core`,
unpacked into `tools/axe/axe.min.js`, dev-tooling only, never served to the app) logs in as each of
the four demo accounts and runs `axe.run()` on every page in that role's sidebar menu
(`accounts/menu.py`), plus two admin "Add" modals opened interactively: **35 page/modal visits
total** — 18 admin pages, 6 program-head pages, 5 instructor pages, 4 student pages, 2 modals.

```
python manage.py seed_demo_users && python manage.py seed_citci_academics
python manage.py runserver 127.0.0.1:8000 --noreload
python tools/accessibility_audit.py --base-url http://127.0.0.1:8000 --role admin --append
python tools/accessibility_audit.py --base-url http://127.0.0.1:8000 --role program_head --append
python tools/accessibility_audit.py --base-url http://127.0.0.1:8000 --role instructor --append
python tools/accessibility_audit.py --base-url http://127.0.0.1:8000 --role student --append
python tools/accessibility_audit.py --base-url http://127.0.0.1:8000 --role admin_modals --append
```

(One `--role` per invocation, each appending to the same `--out` file — Chromium in this sandboxed
environment doesn't reliably survive more than one role's worth of logins/navigations in a single
process; see "Environment note" below.)

**Important precondition**: the demo accounts must have `must_change_password=False` and
`privacy_consent_at` set, or every page visited is actually the forced-onboarding gate, not the
real page — the script's login step doesn't click through that gate. `seed_demo_users`
intentionally leaves new/reset accounts gated (by design, for human testers); if you're driving the
four long-lived demo accounts with this script, clear the gate once first:

```python
from django.utils import timezone
from accounts.models import User
User.objects.filter(username__in=["admin", "program_head", "instructor", "student"]).update(
    must_change_password=False, privacy_consent_at=timezone.now()
)
```

## Result

**0 critical, 0 serious, 0 moderate, 0 minor violations** across all 35 page/modal visits, after
the fixes below. Full machine-readable output: `tools/axe/results.json` (currently an empty list).

## Findings and fixes

### 1. Color contrast (serious) — `text-gray-400`/`text-gray-500` on white

The dominant finding, appearing dozens of times across nearly every page: Tailwind's
`text-gray-400` (`#9ca3af`, ~2.7:1 on white) and `text-gray-500` (`#6b7280`, ~4.0:1) both fall under
WCAG 2 AA's 4.5:1 minimum for normal-size text. These were used throughout as the "muted secondary
text" color — page subtitles, stat-card captions, table timestamps, filter labels.

**Fixed**: a project-wide `text-gray-400` / `text-gray-500` → `text-gray-600` (`#4b5563`, ~7.2:1,
comfortably passes AA) across all 80+ templates using it (`sed` across `templates/**/*.html`) — a
single mechanical, low-risk substitution since both were already used purely as "muted text," never
as a deliberate brand color. One additional instance used `text-amber-600` (~3.0:1) for a "(partial)"
GWA badge (`grading/my_progress.html`) — bumped to `text-amber-800` (~6.5:1).

### 2. Unlabeled filter `<select>` elements (moderate, ~17 instances)

Every list page's quick-filter dropdowns (program/semester/instructor/status/etc.) had no
`<label>` or `aria-label` — a screen-reader user hears only "combo box," not what it filters.

**Fixed**: added `aria-label` to every filter `<select>` across admin/program-head/instructor
pages (Programs, Majors, Sections, Subjects, Classes, Teaching Loads, Users, Grade Sheets, Forecast
Model, Audit Log, At-Risk Students x2, Submitted Grades, My Grades), derived from each select's own
placeholder option text (e.g. "All programs" → `aria-label="All programs"`) via a small Python
patch script, plus a few manual fixes for selects with no placeholder option (checkpoint/source on
the Forecast Model training form).

### 3. Unassociated `<label>` elements and unlabeled checkboxes (serious/moderate)

Three spots had a visible `<label>` that wasn't actually wired to its input via `for`/`id` (the
Forecast Model threshold field, Audit Log's From/To date fields) — visually a label, but invisible
to a screen reader's form-navigation. The Program Head Classes page's bulk-select checkboxes (the
header "select all" and each row's checkbox) had no accessible name at all.

**Fixed**: added matching `for`/`id` pairs to the three unassociated labels; added `aria-label`
("Select all classes" / "Select {{ class }}") to the bulk-select checkboxes, plus visually-hidden
(`sr-only`) text in the previously-empty select-all column header (which also cleared a separate
`empty-table-header` finding on the same element).

### 4. Notification bell: visible badge number not reflected in the accessible name (serious)

The bell button's `aria-label` ("Notifications (N unread)") didn't satisfy axe's
`label-content-name-mismatch` check even though the text was present in the label string — the rule
wants the element's own **rendered content** (not just an overriding `aria-label`) to account for
what's visually on screen, for voice-control users who see "8" and say "click 8."

**Fixed**: replaced the single `aria-label` with real (but visually `sr-only`) text content
("Notifications (N unread)") as the button's accessible name, and marked the red numeric badge
`aria-hidden="true"` as purely decorative/redundant supplementary information — the screen-reader
text already states the count.

### 5. Icon-only modal close buttons had no accessible name (critical)

Every one of the ~24 shared modal partials' "×" close buttons (`@click="modalOpen = false"`,
icon-only) had no `aria-label` — a screen reader announces an unlabeled button only as "button,"
giving no indication it closes the dialog.

**Fixed**: `aria-label="Close"` added to all of them in one pass (pattern was consistent across
every modal partial).

### 6. Modal dialog not contained by a landmark, and missing an accessible name (serious/moderate)

The shared modal shell (`#modal-content` in `base.html`) sits as a sibling of `<main>` rather than
inside it (for CSS stacking-context reasons — it needs to render above everything regardless of
where in the DOM `<main>`'s content happens to scroll), so axe's "all content must be in a landmark"
check flagged it; and once given `role="dialog"`, a dialog landmark itself needs an accessible name.

**Fixed**: `role="dialog"` + `aria-modal="true"` on `#modal-content` (making it its own landmark,
satisfying the containment check), and `aria-labelledby="modal-title"` pointing at each modal
fragment's own heading — `id="modal-title"` was added to all ~24 modal partials' title `<h3>`
elements so the dialog's accessible name is always the specific modal's own title ("Add Program",
"Assign Instructor — PEd 205", etc.), not a generic "Dialog."

### A debugging note worth recording

Mid-audit, a stale `runserver` process from earlier in the session was still bound to port 8000
underneath a newer one I'd started without noticing the bind failure — so for a while, fixes that
were correctly saved to template files weren't showing up in the live audit at all (the old process
was still serving the pre-fix templates). If a fix doesn't show up in a re-run, verify which PID is
actually listening (`netstat -ano | grep 8000`) rather than trusting the PID a background shell
command reports — they aren't always the same process in every shell environment.

## What wasn't covered

- **Pages requiring specific object state** not reachable from a fresh demo-data seed (e.g. a
  grade-sheet review page mid-approval, the forecast drawer, most modals besides the two tested)
  weren't individually added to the page list — they reuse the same shared
  chrome/CRUD/modal/filter-select templates already covered and fixed above, so the same fixes
  apply, but this wasn't machine-verified for every single one.
- This is an **automated** audit (axe-core catches roughly 30-40% of WCAG issues by its own
  documentation) — it does not replace manual checks like actual screen-reader navigation or
  keyboard-only task completion, neither of which was performed this pass.
- Guest-only pages (login, locked-out) weren't included — they're reached before the four demo
  accounts exist and would need a separate unauthenticated check.

## Environment note (for anyone re-running this)

Running Chromium under Playwright in this particular sandboxed environment was unreliable when
driving more than one role's worth of logins/navigations in a single browser process — it would
crash non-deterministically partway through. The script works around this by auditing **one role
per process** (`--role`, appending to the same output file) rather than looping over every role in
one browser lifetime; on a normal (non-sandboxed) machine, `--role all` in one run should work fine.
