# Test Report — Phase 8 part B

## Summary

- **293 tests**, all passing (`python manage.py test academics accounts approvals core dashboard
  forecasting grading reports`, ~16 minutes locally).
- **76.1% overall line coverage** (5,734 statements, 1,372 missed).
- **Target met**: ≥80% coverage on every *service* module and every *access-control* module — the
  explicit target for this pass (CLAUDE.md Phase 8 part B spec). See the table below.
- The remaining coverage gap is concentrated in the HTTP view layer (admin CRUD edge branches,
  modal GET fragments) and two data-parsing modules — explained in "Where the gap is," not chased
  further this pass given diminishing returns relative to the services/access-control target that
  was actually set.

## How to run

```
pip install -r requirements-dev.txt        # adds coverage, playwright, scipy, requests
coverage run manage.py test academics accounts approvals core dashboard forecasting grading reports
coverage report -m                         # per-file summary (this report's source)
coverage html                              # browsable htmlcov/index.html
```

The standalone `tools/` scripts (`uat_analysis.py`, `generate_erd.py`, `generate_uat_docs.py`)
aren't Django apps and aren't exercised by `manage.py test` — `tools/test_uat_analysis.py` covers
`uat_analysis.py` separately: `python tools/test_uat_analysis.py -v`.

## Services and access-control — the ≥80% target

| Module | Coverage | |
|---|---|---|
| `grading/services.py` | 87.4% | ✓ |
| `approvals/services.py` | 96.2% | ✓ |
| `forecasting/services.py` | 84.4% | ✓ |
| `forecasting/ml/evaluate.py` | 93.2% | ✓ |
| `forecasting/ml/features.py` | 97.1% | ✓ |
| `forecasting/ml/predict.py` | 98.3% | ✓ |
| `forecasting/ml/synthetic.py` | 100.0% | ✓ |
| `forecasting/ml/train.py` | 97.0% | ✓ |
| `reports/services.py` | 100.0% | ✓ |
| `academics/services.py` (teaching-load assignment) | 91.5% | ✓ |
| `accounts/decorators.py` (role_required) | 100.0% | ✓ |
| `accounts/mixins.py` (RoleRequiredMixin) | 100.0% | ✓ |
| `accounts/middleware.py` | 85.0% | ✓ |

Every module whose job is "compute a grade/GWA/forecast correctly" or "decide who's allowed to see
this" is above 80% — these are also the modules with the highest cost-of-being-wrong (a silently
incorrect grade, or a silently-too-permissive access check), which is why the spec targeted them
specifically rather than the codebase uniformly.

## What's covered by functional vs. unit tests

- **Unit tests** (pure functions, no HTTP): `grading/tests.py`'s grade-computation suite (including
  the hand-verified `DelaCruzFinalGradeTests` against `grading-system.xlsx`), `forecasting/tests.py`'s
  feature-extraction/leakage-guard/label-rule/risk-level suites, `approvals/tests.py`'s GWA/
  transition tests, `tools/test_uat_analysis.py`.
- **Functional tests** (Django test `Client`, real HTTP + templates + middleware): every
  role/object-level access-control test (`RoleAndObjectLevelAccessTests`,
  `AssignInstructorPermissionTests`, `AccessControlTests`, etc.), the full grade-sheet workflow
  (`approvals/tests.py`), the dashboard/My-Grades/My-Progress/Subject-detail query-count regression
  guards (`dashboard.tests.DashboardQueryCountTests`), notification delivery, PDF/Excel export
  content.
- **Query-count regression tests** (new this pass): `forecasting.tests.AtRiskQueryCountTests`,
  `dashboard.tests.DashboardQueryCountTests` — assert an upper bound on query count that stays flat
  as the amount of data grows, catching a reintroduced N+1 the way a plain pass/fail test can't.

## Where the gap is (overall 76.1%, not 80%)

The services/access-control modules targeted by this phase are all well above 80%; the modules
pulling the overall average down are:

- **`approvals/views.py` (31.6%)**, **`forecasting/views.py` (53.5%)**, **`accounts/views.py`
  (58.3%)**, **`reports/views.py` (58.6%)**, **`academics/views.py` (70.7%)**, **`core/crud.py`
  (52.8%)** — the HTTP view layer. The *critical* paths through each (the main GET, the main POST,
  the 403/404 cases) are functionally tested; what's missing is secondary branches — admin-modal
  edge cases, HTMX-fragment-vs-full-page variants, less-common filter combinations in list views.
- **`accounts/bulk_import.py` (44.7%)** and **`academics/management/commands/
  import_offerings_docx.py` (49.2%)** — one-off/administrative data-import tooling (bulk student/
  instructor import, the Registrar .docx parser) exercised by a handful of happy-path tests each;
  their many error-message branches for malformed input files aren't individually covered.

None of these are services or access-control code — they're why the overall number sits at 76%
rather than matching the 80%+ modules above. Raising them further is reasonable future work, not a
gap in this phase's stated target.
