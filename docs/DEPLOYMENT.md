# Deploying CITCI GradeTrack

Two supported targets:

- **Primary: Ubuntu Server 22.04/24.04 LTS** — Gunicorn (systemd service) behind Nginx
  (static/media, gzip, upload size limit), PostgreSQL, optional HTTPS with a self-signed or
  internal-CA certificate.
- **Alternative: Windows Server/PC** — Waitress (an NSSM service) serving directly, with
  WhiteNoise handling static files since there's no Nginx in front.

Both targets run the same `config.settings.prod` settings module (`config/settings/prod.py`) —
see its docstring and `CLAUDE.md` section on Phase 8 for what it enforces (no insecure
`SECRET_KEY`, `ALLOWED_HOSTS` required, HTTPS-dependent cookie/HSTS settings gated by one
`ENABLE_HTTPS` flag).

---

## 1. Ubuntu Server (Gunicorn + Nginx) — recommended

### 1.1 First-time setup

```bash
# System packages
sudo apt update
sudo apt install -y python3.12 python3.12-venv postgresql nginx

# A dedicated, unprivileged service user + install directory
sudo useradd --system --home /opt/citci-gradetrack --shell /usr/sbin/nologin citci
sudo mkdir -p /opt/citci-gradetrack
sudo chown citci:citci /opt/citci-gradetrack

# Clone the repo as that user (or deploy a release tarball the same way)
sudo -u citci git clone <your-repo-url> /opt/citci-gradetrack
cd /opt/citci-gradetrack

# Virtualenv + production dependencies
sudo -u citci python3.12 -m venv venv
sudo -u citci venv/bin/pip install -r requirements-prod.txt

# PostgreSQL database + role
sudo -u postgres psql -c "CREATE ROLE citci_user LOGIN PASSWORD 'change-me';"
sudo -u postgres psql -c "CREATE DATABASE citci_gradetrack OWNER citci_user;"

# Environment
sudo -u citci cp deploy/.env.prod.example .env
sudo -u citci nano .env
#   - SECRET_KEY: generate with
#       venv/bin/python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
#   - ALLOWED_HOSTS / CSRF_TRUSTED_ORIGINS: your LAN hostname or IP (see section 4 below)
#   - DATABASE_URL: postgres://citci_user:change-me@127.0.0.1:5432/citci_gradetrack
#   - ENABLE_HTTPS=False to start (plain LAN HTTP) — see section 5 to turn it on later
#   - USE_WHITENOISE=False (Nginx serves static/ directly on this target)

# Migrate, build CSS, collect static, create the first admin — NO demo data
sudo -u citci env DJANGO_SETTINGS_MODULE=config.settings.prod venv/bin/python manage.py migrate
sudo -u citci env DJANGO_SETTINGS_MODULE=config.settings.prod venv/bin/python manage.py tailwind build
sudo -u citci env DJANGO_SETTINGS_MODULE=config.settings.prod venv/bin/python manage.py collectstatic --noinput
sudo -u citci env DJANGO_SETTINGS_MODULE=config.settings.prod venv/bin/python manage.py setup_production

# systemd service
sudo mkdir -p /opt/citci-gradetrack/logs
sudo cp deploy/gunicorn.service /etc/systemd/system/citci-gradetrack.service
sudo systemctl daemon-reload
sudo systemctl enable --now citci-gradetrack

# Nginx site
sudo cp deploy/nginx.conf /etc/nginx/sites-available/citci-gradetrack
sudo ln -s /etc/nginx/sites-available/citci-gradetrack /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Visit `http://<your-hostname-or-ip>/`.

### 1.2 Updating

```bash
sudo -u citci deploy/scripts/deploy.sh
```

This backs up the database first (`backup_db`), pulls, reinstalls dependencies, migrates,
rebuilds CSS, re-collects static files, runs `check --deploy` (informational), and restarts the
service. The final `sudo systemctl restart` step needs the `citci` user to have passwordless sudo
for that one command (`sudo visudo -f /etc/sudoers.d/citci-gradetrack` →
`citci ALL=(ALL) NOPASSWD: /bin/systemctl restart citci-gradetrack`), or have an admin run that
last step by hand.

---

## 2. Windows Server/PC (Waitress + NSSM)

No Nginx on this target — Waitress serves the app directly, and WhiteNoise serves static files
from inside Django (no separate web server needed at all, which is the point of this target: a
simple single-process Windows deployment).

### 2.1 First-time setup

```powershell
# Python 3.12+ already installed, then:
git clone <your-repo-url> C:\citci-gradetrack
cd C:\citci-gradetrack

python -m venv venv
venv\Scripts\pip install -r requirements-prod.txt

# PostgreSQL: install from postgresql.org, create the role/database via pgAdmin or psql
# (same CREATE ROLE / CREATE DATABASE statements as section 1.1)

copy deploy\.env.prod.example .env
notepad .env
#   - SECRET_KEY, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, DATABASE_URL — same as section 1.1
#   - ENABLE_HTTPS=False to start
#   - USE_WHITENOISE=True — this target has no Nginx, Django must serve static/ itself

$env:DJANGO_SETTINGS_MODULE = "config.settings.prod"
venv\Scripts\python manage.py migrate
venv\Scripts\python manage.py tailwind build
venv\Scripts\python manage.py collectstatic --noinput
venv\Scripts\python manage.py setup_production
```

### 2.2 Install as an NSSM service

[Download NSSM](https://nssm.cc/download), then:

```powershell
nssm install CITCIGradeTrack
```

In the GUI (or via `nssm set` commands):

- **Application path**: `C:\citci-gradetrack\venv\Scripts\python.exe`
- **Arguments**: `deploy\waitress_serve.py`
- **Startup directory**: `C:\citci-gradetrack`
- **Environment** (Details tab, one `NAME=value` per line, or `nssm set CITCIGradeTrack AppEnvironmentExtra`):
  ```
  DJANGO_SETTINGS_MODULE=config.settings.prod
  WAITRESS_PORT=8000
  ```
  (`.env` still supplies `SECRET_KEY`/`ALLOWED_HOSTS`/`DATABASE_URL`/etc. — those don't need to be
  set as service environment variables too, since `config/settings/base.py` reads `.env` directly.)
- **I/O tab**: redirect stdout/stderr to e.g. `C:\citci-gradetrack\logs\service-stdout.log` /
  `service-stderr.log`, for anything printed before Django's own rotating `logs/app.log` takes
  over.

```powershell
nssm start CITCIGradeTrack
```

Visit `http://<server-ip>:8000/`. Put IIS or another reverse proxy in front on port 80/443 if you
want a plain URL without the port — out of scope here since CITCI's primary target is Ubuntu/Nginx.

### 2.3 Updating

```powershell
nssm stop CITCIGradeTrack
venv\Scripts\python manage.py backup_db
git pull
venv\Scripts\pip install -r requirements-prod.txt
$env:DJANGO_SETTINGS_MODULE = "config.settings.prod"
venv\Scripts\python manage.py migrate
venv\Scripts\python manage.py tailwind build
venv\Scripts\python manage.py collectstatic --noinput
nssm start CITCIGradeTrack
```

---

## 3. Backups

`python manage.py backup_db` (`core/management/commands/backup_db.py`): runs `pg_dump -Fc` to
`BACKUP_DIR` (default `./backups`, override via `.env`) with a timestamped filename, plus a
timestamped copy of `MEDIA_ROOT` (uploaded logos, etc.), then deletes anything beyond the last
`BACKUP_KEEP` (default 30) of each. Needs `pg_dump` on PATH, or set `PG_DUMP_PATH` in `.env`/the
environment if it isn't (e.g. a specific PostgreSQL version's `bin/` directory on Windows).

`python manage.py restore_db <path-to-.dump> --yes-i-am-sure` (`restore_db.py`): runs
`pg_restore --clean --if-exists` against that file. **Destructive** — overwrites the current
database — the `--yes-i-am-sure` flag is required, there is no prompt. Restoring a media/ copy (if
the backup included one) is a manual step (copy the `media_<timestamp>/` folder's contents back
into `MEDIA_ROOT`) — the command only touches the database.

### Scheduling

**Linux (cron)** — daily at 2 AM, as the service user:

```
0 2 * * * cd /opt/citci-gradetrack && DJANGO_SETTINGS_MODULE=config.settings.prod venv/bin/python manage.py backup_db >> logs/backup.log 2>&1
```

(`sudo -u citci crontab -e`)

**Windows (Task Scheduler)**:

```powershell
$action = New-ScheduledTaskAction -Execute "C:\citci-gradetrack\venv\Scripts\python.exe" `
    -Argument "manage.py backup_db" -WorkingDirectory "C:\citci-gradetrack"
$trigger = New-ScheduledTaskTrigger -Daily -At 2am
Register-ScheduledTask -TaskName "CITCI GradeTrack Backup" -Action $action -Trigger $trigger `
    -RunLevel Highest
```

Set `DJANGO_SETTINGS_MODULE` via the scheduled task's "Add arguments"/environment, or wrap the
command in a small `.bat` that sets it before calling `manage.py`.

---

## 4. Giving the server a fixed LAN hostname/IP

CITCI's deployment is a local-network install, not public internet — pick one:

- **Static IP, no DNS**: assign the server a static IP via its NIC settings or a DHCP reservation
  on the router, and use that IP directly in `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS` and in Nginx's
  `server_name`. Simplest, works immediately, but users type an IP address.
- **A LAN hostname** (what the examples above use, `gradetrack.citci.local`): either add a DNS A
  record on CITCI's router/DNS server pointing that name at the server's static IP, or (for a very
  small network) add a line to each client machine's hosts file
  (`C:\Windows\System32\drivers\etc\hosts` / `/etc/hosts`): `192.168.1.50 gradetrack.citci.local`.
  Update `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS` and Nginx's `server_name` to match whichever name
  you choose, and restart the service + reload Nginx after changing `.env`.

---

## 5. Turning on HTTPS

Off by default (`ENABLE_HTTPS=False`) since CITCI may start on plain LAN HTTP with no certificate.
To turn it on once a certificate exists:

1. Get a certificate — a self-signed one works for an internal LAN (browsers will warn once,
   "Advanced → Proceed" or install the cert as trusted on lab machines), or use CITCI's own
   internal CA if one exists:
   ```bash
   openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
       -keyout /etc/ssl/citci-gradetrack/privkey.pem \
       -out /etc/ssl/citci-gradetrack/fullchain.pem \
       -subj "/CN=gradetrack.citci.local"
   ```
2. Uncomment the HTTPS `server` block in `deploy/nginx.conf` (or the IIS/reverse-proxy equivalent
   on Windows), pointing at that cert, and either remove the plain-HTTP block or have it redirect
   to HTTPS instead of serving directly.
3. Set `ENABLE_HTTPS=True` in `.env` and restart the service — this turns on
   `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE`/`SECURE_SSL_REDIRECT`/HSTS all together (see
   `config/settings/prod.py`).
4. Reload Nginx (`sudo nginx -t && sudo systemctl reload nginx`) and confirm `https://` loads
   before relying on it — `SECURE_SSL_REDIRECT` will otherwise redirect plain HTTP requests into a
   dead end if the TLS front end isn't actually there yet.

**Do not set `ENABLE_HTTPS=True` without an actual TLS-terminating front end already in place** —
the site becomes unreachable (redirect loop) until one exists.

---

## 6. Where things live

- **Logs**: `logs/app.log` (INFO+) and `logs/error.log` (WARNING+), rotating at 10MB × 10 files
  (`config/settings/prod.py`'s `LOGGING`). Override the directory with `LOG_DIR` in `.env`.
  Gunicorn's own access/error logs are separate (`logs/gunicorn-access.log` /
  `gunicorn-error.log`, set in `deploy/gunicorn.service`); on the Waitress/NSSM target, NSSM's I/O
  tab controls where stdout/stderr land before Django's own logging takes over.
- **Backups**: `BACKUP_DIR` in `.env`, default `./backups/`.
- **Static files**: `staticfiles/` (collectstatic's output — content-hashed filenames via
  `ManifestStaticFilesStorage`/WhiteNoise's manifest variant, so a stale browser cache is never a
  problem after a deploy). Never edit files there directly — they're regenerated by
  `collectstatic` every deploy.
- **Media** (uploaded logos, etc.): `MEDIA_ROOT` (`media/` by default).

## 7. Rotating SECRET_KEY

Changing `SECRET_KEY` invalidates every existing session (forces re-login) and any outstanding
password-reset tokens — plan for that, don't do it at random. To rotate:

```bash
venv/bin/python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
```

Put the new value in `.env`, restart the service. There's no in-place "dual key" support in this
project — a rotation is a hard cutover.

## 8. Post-install checklist

- [ ] `manage.py check --deploy` run under `config.settings.prod` with the real `.env` and no
      unexpected warnings (see `config.settings.prod`'s docstring for the intentional ones —
      HSTS/SSL-redirect/secure-cookie warnings are expected and correct while `ENABLE_HTTPS=False`
      for a plain-LAN-HTTP deployment).
- [ ] `/healthz` returns `{"status": "ok", "db": true}`.
- [ ] Logged in as the `setup_production`-created admin, forced password change works, Data
      Privacy consent page works.
- [ ] Institution Settings (System → Settings) filled in with CITCI's real school header, Dean/
      Academic Head/Registrar names, and the Data Privacy Notice text/DPO contact reviewed (it
      ships with placeholder-but-functional default text — see `reports.InstitutionSettings`).
- [ ] A real admin account exists beyond the one `setup_production` created, if more than one
      admin should have access (Users page → Add User).
- [ ] `backup_db` scheduled (section 3) and a test run confirmed to produce a `.dump` file in
      `BACKUP_DIR`.
- [ ] No demo data present — `setup_production` never creates any, and the `seed_*` commands all
      refuse to run under the production settings module without `--force-demo` (confirm nobody ran
      one with that flag by mistake — check the Users page for `student001`-style demo accounts).
- [ ] 404/500/403 pages render with the CITCI brand look (visit a bad URL, e.g.
      `/this-page-does-not-exist/`).
- [ ] Static files load with hashed filenames (view source on any page, static URLs should look
      like `tailwind.<hash>.css`, not just `tailwind.css`) — confirms `collectstatic` actually ran.
