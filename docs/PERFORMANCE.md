# Performance — Phase 8 part B

Non-functional requirement (CLAUDE.md section 9): response time < 2 s for normal pages, with
seeded data in the 50–500 user range.

## Environment

- Windows 11, Python 3.12.10, Django 5.2.18, PostgreSQL 14, local machine (not a shared/CI runner).
- Server: `python manage.py runserver 127.0.0.1:8000 --noreload` — Django's single-process
  development server, **not** the production target (Gunicorn/Waitress with multiple workers —
  see `docs/DEPLOYMENT.md`). This matters for the concurrency numbers below.
- Database: seeded by `python manage.py seed_load_test` — 1 admin, 2 program heads, 15
  instructors, 450 students, the current semester + 2 past semesters, realistic scores, a
  submit/approve/release workflow on the past semesters, and computed forecasts
  (`run_forecasts`). All accounts/codes are prefixed `load_`/`LOAD*` — never the real CITCI data
  (see the command's docstring for why, and `docs/DEPLOYMENT.md`-adjacent caution about running it
  only on a dedicated dev/load-test database).
- `DEBUG_TOOLBAR` was left unset (off) — see the Phase 8 part B dated note in `CLAUDE.md`; the
  toolbar's own per-request panels would otherwise inflate every number below.

## Method

`tools/perf_check.py --base-url http://127.0.0.1:8000 --auto --repeats 10 --concurrency 50 100`:
logs in as each role over real HTTP (not the Django test client), times 10 requests per key page
(p50/p95/max), auto-discovers the load test's deliberately-oversized class (one class spanning
every section in the semester, 450 students) for the "largest class" and "score save" timings, then
runs two concurrency bursts — 50 and 100 simulated users, each logging in once and hitting their
own role's dashboard 3 times, via a `ThreadPoolExecutor`.

## Results — single-user timing

| Page | n | p50 (ms) | p95 (ms) | max (ms) | errors |
|---|---|---|---|---|---|
| Admin dashboard | 10 | 236.4 | 356.7 | 376.7 | 0 |
| Program Head dashboard | 10 | 201.0 | 308.7 | 317.2 | 0 |
| Approvals queue | 10 | 90.3 | 91.9 | 92.2 | 0 |
| Reports index | 10 | 81.0 | 145.8 | 187.4 | 0 |
| At-Risk Students (program head) | 10 | 354.6 | 383.4 | 391.7 | 0 |
| Instructor dashboard | 10 | 65.2 | 125.0 | 159.1 | 0 |
| Reports index (instructor) | 10 | 89.9 | 99.2 | 99.7 | 0 |
| At-Risk Students (instructor) | 10 | 278.0 | 333.4 | 335.6 | 0 |
| Student dashboard | 10 | 250.6 | 372.7 | 377.5 | 0 |
| My Grades | 10 | 111.4 | 115.7 | 117.2 | 0 |
| Class Record (largest class, 450 students) | 10 | 1077.4 | 1148.8 | 1149.2 | 0 |
| Score cell save (on the 450-student class) | 10 | 496.3 | 591.1 | 638.2 | 0 |

**Every page is under the 2 s requirement**, including the deliberately worst-case 450-student
class. Most pages are well under 400 ms even on real HTTP (vs. the much lower pure-query-time
numbers in `CLAUDE.md`'s "Query-count pass" notes, which exclude network/WSGI/template-render
overhead — these numbers are the more representative end-to-end figure).

## Results — concurrency

| Concurrent users | n (requests) | p50 (ms) | p95 (ms) | max (ms) | errors |
|---|---|---|---|---|---|
| 50 | 150 | 6274.7 | 8473.1 | 9320.0 | 0 |
| 100 | 220 | 6941.5 | 10154.3 | 11400.5 | 40 (18%) |

**Interpretation — this measures the dev server, not the deployed app.** `manage.py runserver` is
single-process/limited-concurrency by design (Django's own docs call it unfit for production); the
errors at 100 concurrent users were connection-level failures (confirmed against the server log —
no application exceptions, no 500s), not a bug in the app. These numbers establish that the
**application logic itself** doesn't fall over under load (0 errors at 50 concurrent users, and the
100-user errors are a transport artifact of the single-threaded dev server, not slow queries) — they
are not a substitute for load-testing the actual Gunicorn/Waitress deployment described in
`docs/DEPLOYMENT.md`, which was out of scope for this pass (no production-equivalent server
available in this environment).

## Known gap found along the way

`grading.views.save_cell` re-renders its one changed row by calling
`_build_class_record_context(class_offering, ...)` — which recomputes **every** roster entry's
grade, not just the one being saved — to find the single row it needs. For the load test's
450-student class this is the most expensive single operation measured (496–638 ms per cell save,
and most of `Class Record`'s own 1.08–1.15 s is the same whole-class computation). It's well within
the 2 s budget even at this size, so not fixed in this pass, but is the clearest next target if a
future class ever approaches this size — `_build_class_record_context` would need a per-row mode
instead of computing the whole class to extract one row.

## Reproducing this report

```
python manage.py seed_load_test          # dedicated dev/load-test database only
python manage.py run_forecasts
python manage.py runserver 127.0.0.1:8000 --noreload
python tools/perf_check.py --base-url http://127.0.0.1:8000 --auto --repeats 10 \
    --concurrency 50 100 --out docs/PERFORMANCE_raw.md
```
