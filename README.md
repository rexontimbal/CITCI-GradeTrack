# CITCI GradeTrack

Grading Management System with Academic Performance Forecasting — College Department, Candelaria
Institute of Technology of Cabadbaran, Inc. (CITCI).

Built in phases; see `CLAUDE.md` (project root, one level up) for the full build specification.
**Phase 1** covered authentication, role-based access control, and the navigation shell.
**Phase 2 / 2.1** added the academic structure: academic years/semesters, programs, majors,
sections, subjects, classes (which can serve several sections at once), student profiles, and
class lists. **Phase 3** (this state of the repo) adds full user management: the admin Users page
(replacing the read-only Students list), bulk import of students/instructors, login lockout
(django-axes) and sliding session expiry, and a reusable searchable-select widget. Grading,
approvals, and forecasting are still role-gated "Coming soon" placeholders.

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

# 6. Seed demo accounts (one per role) and real CITCI A.Y. 2026-2027 academic data
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

> **Known issue:** `seed_citci_academics` is *not* actually idempotent — its instructor-username
> slugifier only checks usernames already taken at the start of that run, so re-running the
> command creates a fresh set of suffixed duplicate accounts (`garibay2`, `garibay3`, ...) instead
> of reusing the ones from the previous run. Only re-run it against a database you're prepared to
> clean up afterwards (delete the `INSTRUCTOR` accounts with zero `ClassOffering`s pointing at
> them), or fix `_seed_instructors` to match by `last_name` before creating a new user.

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
- **Templates:** `templates/` (shared layout + partials in `templates/partials/`, app templates
  under `templates/<app>/`).
- **Static files:** `static/` — `static/vendor/` holds the locally-vendored HTMX and Alpine.js
  builds (no CDN), `static/img/citci-logo.png` is the official logo, `static/css/tailwind.css` is
  the compiled stylesheet (build artifact — not committed, run `tailwind build`/`tailwind watch`
  to produce it).

## Tech stack

Django 5.2, PostgreSQL (via psycopg 3), Django Templates + HTMX + Alpine.js, Tailwind CSS via the
standalone CLI (`django-tailwind-cli`, no Node.js required), Pillow, openpyxl (class list /
bulk-import templates and exports), django-axes (login lockout). `requirements-dev.txt` adds
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
