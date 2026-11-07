"""Production settings. DJANGO_SETTINGS_MODULE=config.settings.prod — set
this in the actual process environment (systemd unit / NSSM service env),
not just .env, since it has to be known before Django even loads a settings
module to read .env from. See docs/DEPLOYMENT.md.
"""

from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import BASE_DIR, MIDDLEWARE, env

DEBUG = False

# --- SECRET_KEY -------------------------------------------------------
# Must come from the environment (.env or a real env var) in production.
# Refuses to start on an empty value or the well-known insecure dev
# fallback — a SECRET_KEY leak/reuse undermines sessions, CSRF tokens, and
# password-reset tokens, so this is deliberately a hard failure, not a
# warning.
_INSECURE_DEFAULTS = {"", "django-insecure-dev-only-change-me", "django-insecure-change-me-in-.env"}
if SECRET_KEY in _INSECURE_DEFAULTS:
    raise ImproperlyConfigured(
        "SECRET_KEY is missing or using an insecure default. Set a real SECRET_KEY "
        "in the production environment before starting the server — generate one with "
        "`python -c \"from django.core.management.utils import get_random_secret_key as g; print(g())\"`."
    )

# --- Hosts --------------------------------------------------------------
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "ALLOWED_HOSTS is empty. Set it in the production environment, e.g. "
        "ALLOWED_HOSTS=gradetrack.citci.local,192.168.1.50"
    )

# --- HTTPS / transport security ------------------------------------------
# CITCI may run this on a plain-HTTP LAN at first (no public internet
# exposure, no cert yet) and switch to HTTPS later with a self-signed or
# internal-CA certificate — ENABLE_HTTPS is the single flag that decides
# whether Django assumes a TLS-terminating front end is in front of it.
# Leave it off for plain-HTTP LAN deployments; flipping it on without an
# actual HTTPS front end would make the site unreachable (redirect loop).
ENABLE_HTTPS = env.bool("ENABLE_HTTPS", default=False)

# --- Django Admin path ---------------------------------------------------
# Superuser-only (config/admin.py); moved off the default /admin/ path in
# production so it isn't the first thing a port-scan finds. Dev/base keep
# the default "admin/" (config/urls.py falls back to it if unset).
ADMIN_URL = env("DJANGO_ADMIN_URL", default="admin/")

SESSION_COOKIE_SECURE = ENABLE_HTTPS
CSRF_COOKIE_SECURE = ENABLE_HTTPS
SECURE_SSL_REDIRECT = ENABLE_HTTPS

if ENABLE_HTTPS:
    # 1 year, as recommended before submitting to HSTS preload lists — safe
    # to leave un-preloaded (CITCI's LAN hostname will never be in the
    # public preload list) but the long max-age still protects repeat
    # visitors against downgrade attacks.
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    # Nginx terminates TLS and forwards plain HTTP to Gunicorn — this header
    # is how Django knows the original request was HTTPS (see deploy/nginx
    # site config: proxy_set_header X-Forwarded-Proto $scheme).
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
else:
    SECURE_HSTS_SECONDS = 0
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False

# --- WhiteNoise (optional static-file fallback — see "Deployment: Windows"
# in README/docs/DEPLOYMENT.md; Nginx deployments don't need this, Django
# never serves static files in that setup) ---------------------------------
USE_WHITENOISE = env.bool("USE_WHITENOISE", default=False)
if USE_WHITENOISE:
    MIDDLEWARE = [
        MIDDLEWARE[0],
        "whitenoise.middleware.WhiteNoiseMiddleware",
        *MIDDLEWARE[1:],
    ]
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }

# --- Logging --------------------------------------------------------------
# Rotating file logs — app.log for everything INFO+, error.log for
# WARNING+ only, so an admin tailing error.log isn't drowned in routine
# request noise. No personal data (names, ID numbers, scores) is ever
# passed to a logger call anywhere in the codebase — reviewed Phase 8 part
# A; the only app-level logger (forecasting.services) logs roster_entry
# primary keys only.
LOG_DIR = Path(env("LOG_DIR", default=str(BASE_DIR / "logs")))
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
        "app_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "app.log",
            "maxBytes": 10 * 1024 * 1024,  # 10 MB
            "backupCount": 10,
            "formatter": "verbose",
            "level": "INFO",
        },
        "error_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "error.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 10,
            "formatter": "verbose",
            "level": "WARNING",
        },
    },
    "root": {"handlers": ["console", "app_file", "error_file"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console", "app_file", "error_file"], "level": "INFO", "propagate": False},
        "django.security": {"handlers": ["console", "error_file"], "level": "WARNING", "propagate": False},
    },
}
