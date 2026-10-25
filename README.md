# CITCI GradeTrack

Grading Management System with Academic Performance Forecasting — College Department, Candelaria
Institute of Technology of Cabadbaran, Inc. (CITCI).

Built in phases; see `CLAUDE.md` (project root, one level up) for the full build specification.
**Phase 1** (this state of the repo) covers authentication, role-based access control, and the
navigation shell — every other module is a role-gated "Coming soon" placeholder.

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

# 6. Seed demo accounts (one per role)
python manage.py seed_demo_users

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
change flag, and privacy consent) back to a fresh first-login state.

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
- **Templates:** `templates/` (shared layout + partials in `templates/partials/`, app templates
  under `templates/<app>/`).
- **Static files:** `static/` — `static/vendor/` holds the locally-vendored HTMX and Alpine.js
  builds (no CDN), `static/img/citci-logo.png` is the official logo, `static/css/tailwind.css` is
  the compiled stylesheet (build artifact — not committed, run `tailwind build`/`tailwind watch`
  to produce it).

## Tech stack

Django 5.2, PostgreSQL (via psycopg 3), Django Templates + HTMX + Alpine.js, Tailwind CSS via the
standalone CLI (`django-tailwind-cli`, no Node.js required), Pillow. See `CLAUDE.md` for the full
rationale and later-phase plans (grading engine, ML forecasting service, etc.).
