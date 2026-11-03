# CITCI GradeTrack

Grading Management System with Academic Performance Forecasting — College Department, Candelaria
Institute of Technology of Cabadbaran, Inc. (CITCI).

Built in phases; see `CLAUDE.md` (project root — see the housekeeping note at its top for the
phase-numbering mapping) for the full build specification.
**Phase 1** covered authentication, role-based access control, and the navigation shell.
**Phase 2 / 2.1** added the academic structure: academic years/semesters, programs, majors,
sections, subjects, classes (which can serve several sections at once), student profiles, and
class lists. **Phase 2.2** added full user management: the admin Users page (replacing the
read-only Students list), bulk import of students/instructors, login lockout (django-axes) and
sliding session expiry, and a reusable searchable-select widget. **Phase 3 / "Phase 4" in the
original spec doc** added the grading engine: grading templates, a class's frozen grading-scheme
snapshot, assessment items, the spreadsheet-style score-encoding grid (Setup / Class Record /
Summary tabs), and the CITCI-verified grade computation service. **Phase 4 part 1** (this state of
the repo) adds the grade-sheet workflow: submit → approve/return → release → lock, frozen-at-
submission grade snapshots, in-app notifications, and a GWA service — see "Grade sheet workflow"
below. **Phase 4 part 2** adds reports & exports: admin-editable Institution Settings, the Grade
Sheet PDF, the formula-driven Class Record Excel export/import, and the role-aware Reports page
(Grade Submission Status, Class Performance Summary, Students with Failing/INC Grades, Program
Grade Report PDF) — see "Reports & exports" below (a same-day follow-up pass fixed a provisional-
remarks bug in grade sheet snapshots, made PDF images resolve without a network round trip, and let
the Excel import create a new assessment item for an unmatched column instead of only reporting
it). **Phase 5** (this state of the repo) adds the student portal: dashboard, My Grades, Subject
detail, My Progress, and a Report of Grades PDF — see "Student portal" below. Forecasting is still
a role-gated "Coming soon" placeholder.

**CITCI GradeTrack does not handle student enrollment** — that's the Registrar's own process. It
only stores each class's official student list ("class list" — see `academics.ClassRosterEntry`),
built by hand or imported from a Registrar .xlsx/.csv export, so instructors have someone to grade.

## Requirements

- Python 3.12+
- PostgreSQL 14+ running locally (or reachable over the network)
- Windows: no extra system packages needed — `django-tailwind-cli` downloads its own Tailwind CLI
  binary on first use, and HTMX/Alpine.js are already vendored under `static/vendor/`.

## Setup (Windows)

```powershell
# 1. Create and activate a virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create the PostgreSQL database and a role for the app (run once, via psql or pgAdmin)
#    adjust the password to match what you put in .env below
psql -U postgres -c "CREATE ROLE citci_user LOGIN PASSWORD 'citci_pass';"
psql -U postgres -c "CREATE DATABASE citci_gradetrack OWNER citci_user;"

# 4. Copy the environment template and fill in real values
copy .env.example .env
#    - SECRET_KEY: generate one, e.g.
#      python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
#    - DATABASE_URL: postgres://citci_user:citci_pass@127.0.0.1:5432/citci_gradetrack

# 5. Run migrations
python manage.py migrate

# 6. Seed demo accounts (one per role), real CITCI A.Y. 2026-2027 academic data, and demo
#    grading data (default template + assessment items/scores for 2 classes) — the last step
#    runs automatically at the end of seed_citci_academics, no need to call it separately
python manage.py seed_demo_users
python manage.py seed_citci_academics

# 7. Build Tailwind CSS (downloads the Tailwind CLI binary the first time)
python manage.py tailwind build
#    while developing, use the watcher instead, in its own terminal:
#    python manage.py tailwind watch

# 8. Run the dev server
python manage.py runserver
```

Visit http://127.0.0.1:8000/accounts/login/.

## Demo accounts

All demo accounts share the password `Demo@1234` and must change it (then accept the Data Privacy
notice) on first login — that's expected, not a bug.

| Username | Role |
|---|---|
| `admin` | Admin (also a Django superuser — `/admin/` works) |
| `program_head` | Program Head |
| `instructor` | Instructor |
| `student` | Student |

Re-running `python manage.py seed_demo_users` resets all four accounts (password, forced-password-
change flag, and privacy consent) back to a fresh first-login state. If a demo account gets locked
out during testing (5 failed logins — see Login security below), clear it with
`python manage.py axes_reset`.

`python manage.py seed_citci_academics` loads real CITCI offerings from
`docs/source/citci_offerings_2026_2027.json` — A.Y. 2026–2027 with an active 1st Sem, programs
BSED (majors English & Social Studies) and TCP, sections BSED-ENG/SS 1–4 + TCP, ~84 subjects, ~96
classes (several shared across sections/majors — e.g. a Gen Ed subject taught once for two
majors), one INSTRUCTOR account per real instructor (username from surname, e.g. `garibay`,
password `Demo@1234`, no forced password change — the demo `instructor` login is repurposed to
be "Mr. Honrejas" so it shows real classes), and ~10 demo students per section (password
`Demo@1234`, no forced password change) all on their sections' class lists. The existing `student`
account is linked to BSED-ENG 1 and `program_head` heads both BSED and TCP.

`seed_citci_academics` is idempotent — re-running it is safe and produces the exact same counts of
users/programs/sections/subjects/classes/roster entries/grading data (`_seed_instructors` matches
an existing instructor by `last_name` before generating a new username, so it no longer creates
`garibay2`-style duplicates on a second run).

`python manage.py seed_grading_demo` (also runs automatically at the end of `seed_citci_academics`)
seeds the "CITCI Default" grading template (Attendance 5% / Quizzes 30% / Recitation 15% /
Project 10% / Examination 40%, matching `grading-system.xlsx`) and, for the first three classes it
finds with both an instructor and an active roster, realistic assessment items + scores (a few
deliberately low-scoring students so FAILED/at-risk cases exist) — then pushes those three classes'
grade sheets to three different workflow states so the Program Head queue and Admin Grade Sheets
page aren't empty: the 1st class stays DRAFT with its Final Exam left deliberately unencoded (so
its Class Record tab visibly demonstrates the running-grade re-normalization rule), the 2nd goes
all the way to RELEASED, and the 3rd (if a third demo class exists) stops at SUBMITTED. Both
transitions use the real `approvals.services` functions (not a shortcut), so notifications and a
timeline get created too — idempotent either way (re-running never re-submits an already-submitted
sheet).

That JSON is generated from the Registrar's .docx via
`python manage.py import_offerings_docx docs/source/all_subject_per_major.docx` (needs
`requirements-dev.txt`: `pip install -r requirements-dev.txt`) — re-run it only if CITCI sends an
updated offerings sheet. It also writes `docs/source/DATA_ISSUES.md`, listing instructor-name
pairs that look like they might be the same person misspelled/mistitled (e.g. "Mr. Garibay" vs
"Ms. Garibay") — these are **never auto-merged**, confirm with CITCI first.

## Login security

- **Account lockout** (django-axes): 5 failed logins locks that *username* (not IP — a shared
  campus IP shouldn't lock other students out) for 15 minutes. Locked-out users see a friendly
  message (`templates/accounts/locked_out.html`); an admin can clear it early from the user's row
  on the Users page ("Unlock" action) or via `python manage.py axes_reset`.
- **Session expiry:** 30 minutes of inactivity (sliding — any request pushes it back) and on
  browser close. See the `AXES_*`/`SESSION_*` settings in `config/settings.py`.

## Bulk import (admin)

"Import Students" and "Import Instructors" (Users page) both accept `.xlsx`/`.csv`, share one
upload → preview → confirm flow (same shape as the Phase 2.1 class-list importer, built on the
same file parser — `core/importing.py`), and match existing accounts by ID number/employee ID
instead of creating duplicates. Download the column template from the import modal before
building a sheet by hand. After confirming an import, download the `.xlsx` of temporary passwords
for newly-created accounts immediately — it's generated in memory from that request only and is
never stored or shown again.

## Grading rules

Verified against `grading-system.xlsx` (CITCI's actual class record) to full Decimal precision —
see `grading/tests.py::DelaCruzFinalGradeTests` for the hand-checked example (row 11, Dela Cruz,
Juan B. → final grade 1.7743118580765638..., displayed 1.77, PASSED).

- **Components/weights** (seeded as the default `GradingTemplate`, "CITCI Default"): Attendance 5%,
  Quizzes 30%, Recitation 15%, Project 10%, Examination 40% — **confirmed CITCI practice:
  Examination's weight is fixed by the school (`is_locked=True`); every other component, including
  whether it exists at all, its name, and its weight, is each instructor's call for their own
  class.** The Setup tab's "Grading Components" panel lets an instructor add/rename/reweight/delete
  their own (unlocked) components (whole-number weights only); a locked one is shown read-only with
  a lock icon. Locked + unlocked weights must total exactly 100% to save. Every add/edit/delete is
  logged (`grading.SchemeComponentChangeLog`) and viewable in a "Change history" panel. A component
  also carries a `category` (Attendance/Quiz/Recitation/Project/Exam/Other) independent of its
  display name — forecasting (later phase) will key off category, not name, since instructors can
  rename components however they like.
- **Component grade** = 5 − 4 × (Σ scores ÷ Σ max scores) for that component's assessment items.
  1.00 is the best possible grade, 5.00 the worst.
- **Final grade** = Σ (component grade × weight). **Passing** = final grade ≤ 3.00.
- **Running grade** (shown mid-term): only components with at least one score encoded *anywhere in
  the class* count, with the remaining weights re-normalized to 100% — a component nobody has
  started yet is excluded rather than dragging the running grade toward 5.00.
- **Final grade**: always every component and every item; any still-blank cell counts as 0.
- All of the above is Decimal arithmetic end to end (never float) — see `grading/services.py`.
  Display rounding (`settings.GRADE_DISPLAY_DECIMALS`, default 2) only affects what's shown; the
  stored/computed value keeps full precision.
- A class never references a `GradingTemplate` directly — the first time anyone opens its grading
  page, `ClassGradingScheme.get_or_create_default` snapshots the template's components onto a
  per-class `ClassGradingScheme`, so editing the template later never changes a class already using
  it. Admin can re-apply a different template to a class only while it has zero scores encoded.

## Grade sheet workflow

`draft → submitted → approved → released → locked`, plus `returned` (Program Head sends it back
with remarks → instructor edits → resubmits). See `approvals/services.py` for the state machine —
every transition is an explicit, role-checked function (never a bare `sheet.status = ...` in a
view) and is logged to `approvals.GradeSheetTransition`.

- **One `approvals.GradeSheet` per (class, period).** `period` is always `FINAL` today;
  `MIDTERM` is a reserved, unused choice.
- **Submit** snapshots every student's computed grade into `approvals.GradeSheetEntry` — approved/
  released grades always read from that snapshot, never recomputed live. Blocked if any active,
  non-INC student has a missing score; the instructor sees a pre-submit review (counts, average,
  the specific missing cells) and must check "I certify these grades are final and correct."
  Re-submitting after a return replaces the whole snapshot.
- **The instructor can only edit scores/items/components while DRAFT or RETURNED** —
  server-enforced via `grading.views._can_edit`, which now also checks
  `approvals.services.is_class_editable`, so every grading mutation route is locked at once. The
  class grading page shows a status badge, a context-appropriate "Submit"/"Resubmit" button, and a
  banner explaining why it's read-only (or the Program Head's return remarks, if returned).
- **Approve/Return** (Program Head of the class's program — any of them, for a class shared across
  programs) · **Release** (Program Head or Admin, only from Approved; "Release all approved" does a
  whole program/semester at once) · **Lock term** (Admin only, locks every Released sheet in the
  active semester) · **Grade correction** (Admin only, Released/Locked sheets, required reason,
  logged to `approvals.GradeCorrection` + the sheet's timeline).
- **Notifications** (`dashboard.Notification`) fire on submit/return/approve/release/correction.
  The topbar bell polls `dashboard:bell` every 60s; its open/closed state lives on `base.html`'s
  body-level Alpine data (not inside the polled fragment) so an open dropdown doesn't snap shut on
  the next poll. Clicking a notification is a plain link to `dashboard:mark_read` (marks it read,
  then redirects to its `link`) rather than an `hx-post` — htmx intercepts clicks on any element
  carrying its own attributes, which would have eaten the navigation.
- **GWA** (`approvals.services.compute_gwa`): Σ(final grade × units) ÷ Σ units over a student's
  Released/Locked entries in a semester, excluding Dropped and INC; `is_complete` is False if any
  non-dropped class in that semester isn't released yet or carries an INC. No UI yet beyond what the
  Program Head/Admin review pages show — full display is the student portal phase.

## Reports & exports

- **Institution Settings** (admin → System → Settings, `reports.InstitutionSettings`, a singleton
  always at `pk=1`): school name/sub-line/address/department, logo (falls back to
  `static/img/citci-seal-256.png`), and the Dean/Academic Head names+titles shown on every PDF's
  signature block — nothing report-related is hardcoded in a template.
- **PDF engine: xhtml2pdf, not WeasyPrint.** WeasyPrint needs the GTK3/Pango/Cairo native
  libraries, which aren't `pip install`-able and weren't present on the Windows dev machine
  (`import weasyprint` raised `OSError: cannot load library 'libgobject-2.0-0'`); xhtml2pdf is
  pure-Python (over reportlab) and needs no system packages on Windows **or** Ubuntu, at the cost
  of weaker CSS support (no `transform`/`rotate` — see the watermark note below). If a future
  deployment target has GTK3 available and wants WeasyPrint's better CSS support instead, that's a
  separate decision — don't swap engines without re-checking this tradeoff.
  - **Windows:** `pip install xhtml2pdf` — no extra system packages.
  - **Ubuntu:** `pip install xhtml2pdf` — no extra system packages either. (If you ever do switch
    to WeasyPrint, Ubuntu needs `sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libgdk-pixbuf2.0-0`
    first — Windows has no equivalent one-liner, which is the whole reason xhtml2pdf was chosen.)
  - The diagonal "UNOFFICIAL — status" watermark on a not-yet-released Grade Sheet PDF is a
    Pillow-rendered rotated PNG embedded as a base64 `data:` URI (`reports/pdf.py:watermark_data_uri`)
    rather than CSS, because xhtml2pdf silently drops `transform`/`rotate` properties.
- **Grade Sheet PDF** (`reports:grade_sheet_pdf`): institution header, "REPORT OF GRADES" title,
  subject/section/schedule/instructor meta, a No./ID/Name/Final Grade/Remarks table sorted by last
  name, pass/fail/INC/dropped counts, and a signature block (Submitted by/Checked by/Noted by) with
  each step's date pulled from the `GradeSheet` timeline. Always renders from the
  `approvals.GradeSheetEntry` snapshot, never live computation; shows the watermark above whenever
  the sheet isn't Released/Locked yet. Images (the logo) never depend on a network round trip —
  `reports/pdf.py:link_callback` resolves a `STATIC_URL`/`MEDIA_URL` `<img>` src straight to a
  filesystem path (rejecting anything outside those roots), so a PDF renders correctly from
  `manage.py shell` or a test with no server running, not just from a live request.
- **Class Record Excel export** (`reports:class_record_excel`, `reports/excel.py`): mirrors
  `grading-system.xlsx`'s layout (institution header rows, per-component item/TOTAL/GRADE/WEIGHTED
  columns, FINAL GRADE, REMARKS) but with one deliberate addition — an **ID Number column** (the
  real CITCI sheet has none) so a re-imported export matches students reliably instead of by name
  alone. Every total/grade/weighted/final cell is a **real Excel formula** (`=SUM(...)`,
  `=IF($col$10=0,5,5-4*(total/max))`, `=grade*weight`, `=SUM(weighted...)`) — not a pre-computed
  value — so Excel recalculates them live if a faculty member edits a cell by hand. Freeze panes
  sit at the first score column/first data row; print setup is landscape, fit-to-width.
  `?blank=1` exports the same layout with no scores filled in — the "download blank class record"
  import template.
- **Class Record Excel import** (`reports/excel_import.py`, Class Record tab, DRAFT/RETURNED only):
  upload either the system's own export or CITCI's template shape — both are recognized by scanning
  for the merged "ID Number"/"Name of Students" header row, two rows above the max-score row.
  Students match by ID Number first, then by normalized "Last, First M." name; items match by
  (component name, item title). Preview shows new/changed scores (old → new), unmatched students,
  and invalid values (non-numeric, non-whole-number, or over max) — nothing is guessed. An
  unmatched item column is offered as a "create as new item" row instead (checkbox, a component
  dropdown pre-selected by name match — locked components like Examination included, since only a
  new *component* needs school sign-off, not a new item on an existing one — a required term
  dropdown, and a max score pre-filled from the sheet's max-score row); an invalid max score blocks
  the whole confirm, never a partial commit.
- **Reports page** (`reports:index`, role-aware): instructors see links to their own classes' Grade
  Sheet PDF / Class Record Excel; Program Heads (their programs only) and Admin (all programs) get
  semester-scoped Grade Submission Status, Class Performance Summary, and Students with
  Failing/INC Grades (Excel-exportable), plus a per-program Program Grade Report PDF.

## Student portal

A student only ever sees their own data — every view filters by `student=request.user` (or a
roster entry already scoped that way), and a mismatched id 404s rather than 403s.

- **OFFICIAL vs UNOFFICIAL, never mixed up.** OFFICIAL = an `approvals.GradeSheetEntry` snapshot
  from a RELEASED/LOCKED sheet (`grading.services.released_entry_for`); UNOFFICIAL = the live
  running grade (`grading.services.compute_student(...).running_grade`) while a class is still in
  progress, always shown with an amber "Unofficial — running grade, may still change" chip. An
  admin-only toggle (System → Settings → "Show running (unofficial) scores to students", default
  on) can turn UNOFFICIAL display off entirely — anything not yet released then shows only "Grades
  not yet released".
- **Dashboard** (`dashboard:home`): greeting + program/major/year/section, stat cards (Enrolled
  Subjects; Official GWA, with a "Partial GWA: x.xx (n of m subjects released)" note when not
  everything's released yet; Subjects Released n/m; Warnings = in-progress subjects with a running
  grade > 3.00), mobile-first subject cards with a status chip and an items-encoded progress bar, an
  "Academic Forecast — Coming soon" placeholder card, and the latest 5 notifications.
- **My Grades** (`grading:my_grades`): a semester selector (every semester with class-list entries),
  cards on mobile / a table from `sm:` up, a footer with total units and Official/Partial GWA, and
  "Download Report of Grades (PDF)".
- **Subject detail** (`grading:subject_detail`, one page per roster entry): component breakdown
  (the official snapshot once released, otherwise live), an item list grouped by grading period
  (always the live `AssessmentItem`/`Score` data — informational, and in practice frozen once a
  class is submitted since editing locks then), a ≥5-active-students-only class average per
  component (aggregate only — never another student's own data), and two Chart.js charts: component
  score % (bar) and running-grade progression by term (line, `grading.services.running_grade_progression`).
- **My Progress** (`grading:my_progress`): a GWA-history line chart (inverted y-axis — 1.00 is
  best, labeled) + table (semester/units/GWA/passed/failed/INC), and a current-semester horizontal
  bar chart of every subject's grade colored by status with a dashed 3.00 passing line (a small
  inline Chart.js plugin, not an external annotation library).
- **Report of Grades PDF** (`reports:student_grade_report_pdf`, reuses `reports/pdf.py`):
  RELEASED/LOCKED entries only for the chosen semester, a "Partial — n of m subjects released" note
  when incomplete, and signed by the Registrar (new `InstitutionSettings.registrar_name/
  registrar_title`) and Dean. The view takes only a semester id — never a student id — so there is
  no ownership check to get wrong; it can only ever render the logged-in student's own data.
- **Notifications** gained a "Mark all as read" button on the full list page
  (`dashboard:notifications_mark_all_read`); releasing a grade sheet or correcting a grade now also
  notifies every affected student, not just the instructor.
- **Demo data:** `python manage.py seed_student_portal_demo` (auto-run at the end of
  `seed_citci_academics`) makes the demo `student` account show every state — released, "submitted"
  (shown as in progress), in-progress-with-partial-scores, no-scores-yet, and a running grade > 3.00
  — plus a past semester (A.Y. 2025–2026, 2nd Sem, released + locked) so GWA history has 2+ points.
  Idempotent; safe to re-run.

## Running tests

```powershell
python manage.py test
```

## Where things live

- **Brand colors / theme:** `.django_tailwind_cli/source.css` (Tailwind `@theme` tokens, generated
  from the CITCI logo's measured navy/gold — see that file's header comment for the source values
  and the WCAG contrast notes).
- **Sidebar menu per role:** `accounts/menu.py`.
- **Role-based access control:** `accounts/decorators.py` (`role_required`) and
  `accounts/mixins.py` (`RoleRequiredMixin`).
- **Forced password-change / privacy-consent gate:** `accounts/middleware.py`.
- **Generic list/create/update/delete scaffolding** (shared by every admin academic-setup page —
  Academic Years, Semesters, Programs, Sections, Subjects, Classes): `core/crud.py`. Pages built on
  it (`academics/views.py`) swap a fragment into the shared modal (markup lives in `base.html`,
  generic fragments in `templates/partials/_entity_form_modal.html` and
  `_confirm_delete_modal.html`) via HTMX, and refresh their table via an `HX-Trigger` response
  header.
- **HTMX + Django CSRF:** `static/js/htmx-csrf.js` attaches the CSRF cookie to every HTMX request
  header — required for any bare `hx-post`/`hx-delete` button that isn't inside a `<form>`.
- **Class list import** (.xlsx/.csv, admin for any class, instructor for their own):
  `academics/roster_import.py` (parse + preview + commit) and the views/templates prefixed
  `class_list_import_*`. Matches students by `id_number`; creates a new STUDENT account if none exists.
- **Shared spreadsheet import parser** (students, instructors, class lists all use it):
  `core/importing.py` — pure `.xlsx`/`.csv` header-matching + row access, no domain logic.
- **User management** (admin Users page, bulk import, password reset/lockout): `accounts/views.py`
  (`UserListView`, `user_form`, `user_reset_password`, `user_toggle_active`, `user_unlock`,
  `import_*`), business logic for bulk import in `accounts/bulk_import.py`. An admin can't
  deactivate their own account or the last active admin (`user_toggle_active`); a new or
  password-reset account always comes back with `must_change_password=True`.
- **Reusable searchable-select widget** (HTMX live search + Alpine.js keyboard nav, used for the
  instructor picker on Classes, the class picker on Class Lists, and the student picker in "Add
  students"): `core/widgets.py` (`SearchableSelectWidget`) +
  `static/js/searchable-select.js`. Point it at any view that renders
  `partials/_searchable_select_options.html` (see `academics.views.instructor_search`/
  `class_search` for the pattern).
- **Registrar .docx → seed data pipeline:** `academics/management/commands/import_offerings_docx.py`
  parses `docs/source/all_subject_per_major.docx` into `docs/source/citci_offerings_2026_2027.json`
  (+ `docs/source/DATA_ISSUES.md`); `seed_citci_academics` loads that JSON into the database.
- **Grading engine** (templates, per-class scheme snapshot, assessment items, scores, computation):
  `grading/models.py`, `grading/services.py` (pure functions — `compute_student`, `compute_class`,
  `save_score`, `validate_component_weights`; no view/HTTP concerns), `grading/views.py` +
  `grading/urls.py` for the admin Grading Templates pages and the instructor Class Grading page
  (Setup / Class Record / Summary tabs, all three rendered server-side and switched client-side via
  Alpine `x-show` — no separate page load per tab). The score-encoding grid autosaves one cell at a
  time via `hx-trigger="blur changed"` (see `templates/grading/_grid_row.html`); keyboard
  Up/Down/Left/Right/Enter navigation between cells is `static/js/grading-grid.js` (plain DOM focus
  moves between inputs via server-rendered `data-up`/`data-down`/`data-left`/`data-right` ids — no
  grid-position math in JS). Chart.js (vendored, `static/vendor/chartjs/`) draws the Summary tab's
  grade-distribution bar chart. The Setup tab's "Grading Components" panel
  (`templates/grading/_components_panel.html`, `static/js/grading-components.js`,
  `grading:class_components_save`) is a single Django formset (`SchemeComponentFormSet`) submitted
  atomically — add/rename/reweight/delete rows together, server-validated that locked + unlocked
  weights total exactly 100%; `static/js/grading-components.js` only handles the live total bar and
  cloning/removing rows client-side (same "clone the empty_form, bump TOTAL_FORMS" trick any Django
  formset JS uses), never the actual validation.
- **Grade sheet workflow** (state machine, snapshot, notifications, GWA): `approvals/models.py`
  (`GradeSheet`, `GradeSheetEntry`, `GradeSheetTransition`, `GradeCorrection`), `approvals/services.py`
  (pure functions — `submit_grade_sheet`, `approve_grade_sheet`, `return_grade_sheet`,
  `release_grade_sheet`, `lock_term`, `correct_grade`, `compute_gwa`, `is_class_editable`; no view/
  HTTP concerns), `approvals/views.py` + `approvals/urls.py` for the instructor submit-review modal
  and Submitted Grades list, the Program Head approvals queue + review page, and the Admin Grade
  Sheets page. `dashboard.Notification` + `dashboard/services.py` (`notify`/`notify_many`) is the
  in-app notification system; the topbar bell is `templates/partials/_notification_bell.html`,
  HTMX-polled from `base.html` every 60s. `grading.views._can_edit` and
  `accounts.context_processors.sidebar` (for the Grade Approvals sidebar badge) both import
  `approvals` lazily (function-local) to avoid a module-load-time import cycle — see CLAUDE.md
  section 11 for why.
- **Reports & exports** (Institution Settings, Grade Sheet PDF, Class Record Excel export/import,
  the role-aware Reports page): `reports/models.py` (`InstitutionSettings` singleton), `reports/pdf.py`
  (xhtml2pdf rendering + the Pillow watermark), `reports/excel.py` (openpyxl, formula-driven),
  `reports/excel_import.py` (preview/commit, mirrors `academics/roster_import.py`'s pattern),
  `reports/services.py` (pure report-query functions, role-scoped `programs` queryset passed in by
  the caller), `reports/views.py` + `reports/urls.py`. PDF/Excel print templates live under
  `templates/reports/pdf/` and `templates/reports/`.
- **Student portal** (dashboard, My Grades, Subject detail, My Progress, Report of Grades PDF):
  `grading/services.py` (`released_entry_for`, `subject_status_chip`,
  `show_unofficial_scores_to_students`, `running_grade_progression`, `class_average_per_component` —
  shared by both the student views and `dashboard._student_dashboard`), `grading/views.py`
  (`my_grades`, `subject_detail`, `my_progress`), `dashboard/views.py` (`_student_dashboard`),
  `reports/views.py` (`student_grade_report_pdf`). Templates: `templates/dashboard/
  student_dashboard.html`, `templates/grading/my_grades.html`/`subject_detail.html`/
  `my_progress.html`, `templates/reports/pdf/student_report.html`.
  `grading/management/commands/seed_student_portal_demo.py` fills in the demo states
  `seed_grading_demo` doesn't reliably cover (SUBMITTED, a running-grade warning, a released+locked
  past semester) — auto-run at the end of `seed_citci_academics`.
- **Templates:** `templates/` (shared layout + partials in `templates/partials/`, app templates
  under `templates/<app>/`).
- **Static files:** `static/` — `static/vendor/` holds the locally-vendored HTMX and Alpine.js
  builds (no CDN), `static/img/citci-logo.png` is the official logo, `static/css/tailwind.css` is
  the compiled stylesheet (build artifact — not committed, run `tailwind build`/`tailwind watch`
  to produce it).

## Tech stack

Django 5.2, PostgreSQL (via psycopg 3), Django Templates + HTMX + Alpine.js, Tailwind CSS via the
standalone CLI (`django-tailwind-cli`, no Node.js required), Chart.js (vendored, grade-distribution
chart only), Pillow, openpyxl (class list / bulk-import templates, class record exports/imports,
report exports), xhtml2pdf (Grade Sheet / Program Grade Report PDFs — see "Reports & exports"
above for why xhtml2pdf over WeasyPrint), django-axes (login lockout). `requirements-dev.txt` adds
python-docx, needed only to regenerate the seed data JSON from a Registrar .docx. See `CLAUDE.md`
for the full rationale and later-phase plans (grading engine, ML forecasting service, etc.).

### Gotcha: custom form widget templates (`FORM_RENDERER`)

`core.widgets.SearchableSelectWidget` renders via a custom template under `templates/partials/`.
Django's *default* form renderer uses its own template `Engine` that only does APP_DIRS lookup
across each installed app's own `templates/` folder — it ignores `TEMPLATES[0]['DIRS']`, so it
can't find a widget template that lives in the project-root `templates/` directory. Fixed in
`config/settings.py` by setting `FORM_RENDERER = "django.forms.renderers.TemplatesSetting"`, which
makes form widgets render through the same configured `django` template engine as regular views.
That change has its own side effect: Django's *own* built-in widget templates (e.g.
`django/forms/widgets/password.html`) are normally found via a special-cased APP_DIRS lookup that
works even without `django.forms` in `INSTALLED_APPS` — but once you switch engines, that
special-casing no longer applies, so `"django.forms"` must be added to `INSTALLED_APPS` too (ahead
of other apps) or every built-in widget breaks with `TemplateDoesNotExist`.
