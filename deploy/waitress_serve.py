"""Entry point for running CITCI GradeTrack under Waitress on Windows,
wrapped by an NSSM service (no Gunicorn — it doesn't run on Windows). See
docs/DEPLOYMENT.md "Windows Server / PC" for the full NSSM setup.

Usage (also what the NSSM service's "Application" + "Arguments" point at):
    venv\\Scripts\\python.exe deploy\\waitress_serve.py
"""

import os
import sys

# NSSM invokes this as `venv\Scripts\python.exe deploy\waitress_serve.py`,
# which puts deploy/ (not the project root) at sys.path[0] — add the
# project root explicitly so `import config` resolves regardless of the
# working directory NSSM starts the service in.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

from waitress import serve

from config.wsgi import application

if __name__ == "__main__":
    host = os.environ.get("WAITRESS_HOST", "0.0.0.0")
    port = int(os.environ.get("WAITRESS_PORT", "8000"))
    threads = int(os.environ.get("WAITRESS_THREADS", "4"))
    serve(application, host=host, port=port, threads=threads)
