"""Local development settings. DJANGO_SETTINGS_MODULE=config.settings.dev
(the default — see manage.py/wsgi.py/asgi.py)."""

from .base import *  # noqa: F401,F403
from .base import BASE_DIR, INSTALLED_APPS, MIDDLEWARE, env

DEBUG = True

# A long random SECRET_KEY still belongs in .env even for dev (django-axes/
# sessions behave oddly if it keeps changing across restarts), but dev never
# refuses to start without one — this fallback is clearly insecure by name
# so nobody mistakes it for something safe to reuse in prod.
if not SECRET_KEY:
    SECRET_KEY = "django-insecure-dev-only-change-me"

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# Plain (non-hashed) static filenames — collectstatic isn't run in dev;
# {% tailwind_css %} appends its own ?v=<mtime> cache-buster instead.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# django-debug-toolbar — dev only (requirements-dev.txt), and now opt-in
# (DEBUG_TOOLBAR=1) rather than always-on: its per-request SQL/template
# panels add real overhead to every page load, which skews the query-count/
# latency numbers in docs/PERFORMANCE.md if left on by habit. Guarded with a
# try/except so `manage.py` still works in a fresh dev checkout before
# `pip install -r requirements-dev.txt` has been run.
if env.bool("DEBUG_TOOLBAR", default=False):
    try:
        import debug_toolbar  # noqa: F401
    except ImportError:
        pass
    else:
        INSTALLED_APPS = [*INSTALLED_APPS, "debug_toolbar"]
        MIDDLEWARE = ["debug_toolbar.middleware.DebugToolbarMiddleware", *MIDDLEWARE]
        INTERNAL_IPS = ["127.0.0.1"]

# Console-only logging in dev — rotating file handlers are a prod concern
# (see prod.py).
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
