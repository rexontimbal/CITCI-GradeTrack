# System Architecture

The current design (CLAUDE.md Tech Stack) — Django monolith, PostgreSQL, forecasting running
**in-process** (no separate FastAPI "ml-service", superseded before anything was built; see
`docs/CHANGES_FROM_PROPOSAL.md`). No task queue — predictions are cheap enough to run
synchronously after a score save, plus a schedulable `run_forecasts` management command.

```mermaid
graph TB
    subgraph Client["Client (browser)"]
        Browser["Django templates + HTMX + Alpine.js<br/>Tailwind CSS, Chart.js<br/>(all vendored locally, no CDN)"]
    end

    subgraph Server["Application server (Gunicorn / Waitress)"]
        Django["Django 5.2<br/>config/settings/{base,dev,prod}.py"]
        subgraph Apps["Django apps (one process, one deploy)"]
            accounts["accounts<br/>auth, RBAC, audit log"]
            academics["academics<br/>programs, sections, classes,<br/>class lists, teaching loads"]
            grading["grading<br/>templates, scoring,<br/>grade computation"]
            approvals["approvals<br/>submit/approve/release<br/>workflow, GWA"]
            forecasting["forecasting<br/>feature extraction, scikit-learn<br/>model, predictions — in-process"]
            reports["reports<br/>PDF (xhtml2pdf)/Excel (openpyxl)<br/>exports, Institution Settings"]
            dashboard["dashboard<br/>per-role dashboards,<br/>notifications"]
            core["core<br/>shared CRUD, health check,<br/>backup/restore"]
        end
        Middleware["Middleware: axes lockout,<br/>session expiry, force-password-change/<br/>privacy-consent gates"]
    end

    subgraph Data["Data"]
        Postgres[("PostgreSQL")]
        ModelFiles["joblib model files<br/>(MEDIA_ROOT/models/)"]
        Media[("MEDIA_ROOT<br/>logos, uploads")]
    end

    subgraph Scheduled["Scheduled (cron / Windows Task Scheduler)"]
        RunForecasts["run_forecasts<br/>management command"]
        BackupDb["backup_db<br/>management command"]
    end

    Browser <--> Django
    Django --> Middleware
    Middleware --> Apps
    accounts -.-> academics
    academics -.-> grading
    grading -.-> approvals
    approvals -.-> forecasting
    forecasting -.-> reports
    Apps <--> Postgres
    forecasting <--> ModelFiles
    reports <--> Media
    RunForecasts --> Postgres
    RunForecasts --> ModelFiles
    BackupDb --> Postgres
    BackupDb --> Media
```

**Why no separate ML service:** at CITCI's data scale, a same-process `forecasting/ml/` package
does the same job as the originally-proposed FastAPI service with no deployment/availability story
to build — Django can't "lose connectivity" to code running in its own process. See
`docs/CHANGES_FROM_PROPOSAL.md` for the full list of deviations from the approved proposal.
