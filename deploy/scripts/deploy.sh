#!/usr/bin/env bash
# Deploy/update script for the Ubuntu + Gunicorn + Nginx target.
# Run as the service user (e.g. `sudo -u citci deploy/scripts/deploy.sh`)
# from the project root (/opt/citci-gradetrack by default). See
# docs/DEPLOYMENT.md for first-time setup — this script assumes the venv,
# .env, PostgreSQL database, and systemd/Nginx units already exist.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

echo "==> Backing up the database before touching anything"
venv/bin/python manage.py backup_db

echo "==> Pulling latest code"
git pull

echo "==> Installing/updating dependencies"
venv/bin/pip install -r requirements-prod.txt

echo "==> Running migrations"
DJANGO_SETTINGS_MODULE=config.settings.prod venv/bin/python manage.py migrate --noinput

echo "==> Collecting static files"
DJANGO_SETTINGS_MODULE=config.settings.prod venv/bin/python manage.py collectstatic --noinput

echo "==> Building Tailwind CSS"
DJANGO_SETTINGS_MODULE=config.settings.prod venv/bin/python manage.py tailwind build

echo "==> Deploy checklist (informational — review before restarting if anything looks wrong)"
DJANGO_SETTINGS_MODULE=config.settings.prod venv/bin/python manage.py check --deploy || true

echo "==> Restarting the service"
sudo systemctl restart citci-gradetrack

echo "==> Done. Tail logs/app.log or 'journalctl -u citci-gradetrack -f' to confirm it came back up."
