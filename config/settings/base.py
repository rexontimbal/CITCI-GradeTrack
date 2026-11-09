"""
Settings shared by every environment. Never import this module directly —
use `config.settings.dev` or `config.settings.prod` (selected via the
DJANGO_SETTINGS_MODULE environment variable; see README "Deployment").

See https://docs.djangoproject.com/en/5.2/topics/settings/
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
# Read .env from the project root (not committed; see .env.example). Safe to
# call even when the file doesn't exist (e.g. env vars set directly by
# systemd in production) — django-environ just skips it.
environ.Env.read_env(BASE_DIR / ".env")

# Every environment needs a real SECRET_KEY from .env/the process
# environment — dev.py falls back to an insecure default for convenience;
# prod.py refuses to start without one (see prod.py).
SECRET_KEY = env("SECRET_KEY", default="")

# Overridden per-environment: False here is the safe default if a settings
# module is ever imported without going through dev.py/prod.py.
DEBUG = False
ALLOWED_HOSTS = []


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.forms",  # needed so FORM_RENDERER=TemplatesSetting can still find Django's own widget templates
    "django_tailwind_cli",
    "axes",
    # CITCI GradeTrack apps
    "core",
    "accounts",
    "academics",
    "grading",
    "approvals",
    "forecasting",
    "reports",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "accounts.middleware.ForceFirstLoginStepsMiddleware",
    "accounts.middleware.HtmxLoginRedirectMiddleware",
    "axes.middleware.AxesMiddleware",
]

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",  # must be first — enforces the lockout
    "django.contrib.auth.backends.ModelBackend",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "accounts.context_processors.sidebar",
                "academics.context_processors.active_semester",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://citci_user:citci_pass@127.0.0.1:5432/citci_gradetrack",
    )
}


# Custom user model (accounts app) — must be set before the first migration.
AUTH_USER_MODEL = "accounts.User"


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},  # default min_length=8
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Manila"
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Content-hashed filenames (e.g. tailwind.3f2a1b9c.css) in production so a
# rebuilt static file is always a new URL — browsers can't serve a stale
# cached copy. Needs `manage.py collectstatic` to generate the manifest.
# dev.py overrides this to plain StaticFilesStorage since collectstatic
# isn't run in development ({% tailwind_css %} appends its own ?v=<mtime>
# instead — see templates/tailwind_cli/tailwind_css.html).
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"},
}

# Media (uploaded files — bulk import sheets, exports, etc.)
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Form widget templates (e.g. core.widgets.SearchableSelectWidget) live under
# templates/partials/ like everything else — Django's default form renderer
# uses its own template engine that ignores TEMPLATES[0]['DIRS'], so without
# this it can't find them (TemplateDoesNotExist) even though regular views can.
FORM_RENDERER = "django.forms.renderers.TemplatesSetting"


# Styled error pages (accounts/views.py) — see docs/DEPLOYMENT.md and the
# Phase 8 part A build note in CLAUDE.md for why 404/500 render a standalone
# template with no context processors instead of extending base.html.
CSRF_FAILURE_VIEW = "accounts.views.csrf_failure_view"


# Auth redirects
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "accounts:login"


# django-tailwind-cli
# https://django-tailwind-cli.andrich.me/
TAILWIND_CLI_VERSION = "4.1.3"
TAILWIND_CLI_SRC_CSS = BASE_DIR / ".django_tailwind_cli" / "source.css"
TAILWIND_CLI_DIST_CSS = "css/tailwind.css"


# django-axes — lock an account out for 15 minutes after 5 failed logins (RA 10173
# login-security requirement). Locks by the (username, ip_address) combination, not
# username alone — a shared campus/lab IP can't lock out every student on it, but an
# attacker also can't dodge the limit by rotating IPs against one username. Admin can
# clear a lockout from the user's row ("Unlock" action — see accounts.views.user_unlock,
# which resets by username and so clears it across every IP that user tried from).
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 0.25  # hours = 15 minutes
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_COOL_OFF_ON_FAILURE_DURING_LOCKOUT = False
AXES_LOCKOUT_TEMPLATE = "accounts/locked_out.html"


# Grading — raw grades are always computed/stored at full Decimal precision;
# this only controls how many decimal places are shown in the UI (e.g. 1.77).
GRADE_DISPLAY_DECIMALS = 2


# Session: expires after 30 minutes of inactivity (SAVE_EVERY_REQUEST slides the
# expiry forward on each request) and when the browser closes.
SESSION_COOKIE_AGE = 60 * 30
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True


# Backups (Phase 8 part A — see core/management/commands/backup_db.py).
# BACKUP_DIR defaults to a top-level backups/ folder (gitignored); override
# in prod via .env if backups should live elsewhere (e.g. a mounted volume).
BACKUP_DIR = env("BACKUP_DIR", default=str(BASE_DIR / "backups"))
BACKUP_KEEP = env.int("BACKUP_KEEP", default=30)


# Clickjacking protection — Django's default is SAMEORIGIN; CITCI GradeTrack
# never needs to be framed by anything, including itself.
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
