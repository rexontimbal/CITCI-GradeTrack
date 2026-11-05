# Defense Demo Script

A 10–15 minute live-demo walkthrough for the final defense, plus a pre-defense reset checklist.
Each step names the account, the page, the click, and the talking point — not a transcript, a
prompt sheet.

## Before you walk in — reset checklist

1. `git status` — confirm no uncommitted experiments are sitting in the working tree that could
   make the demo behave unexpectedly.
2. Confirm `DJANGO_SETTINGS_MODULE` / `.env` point at the **real CITCI demo database**, not a
   `seed_load_test` database (that data is clearly prefixed `LOAD*`/`load_*` and would look wrong
   on screen — if in doubt, check the active semester isn't a `LOAD` one).
3. `python manage.py seed_demo_users && python manage.py seed_citci_academics` — idempotent, safe
   to re-run; this also chains `seed_grading_demo`, `seed_student_portal_demo`, and
   `seed_forecasting_demo` so every page below has real content.
4. Confirm the four demo accounts exist and their password is `Demo@1234`: `admin`,
   `program_head`, `instructor`, `student`.
5. `python manage.py runserver` and load `/accounts/login/` once yourself — confirms static files
   are collected/served and the Tailwind build is current.
6. Close any other browser tabs pointed at a stale session; log out of all four accounts first so
   each login below is a clean one (demonstrates the forced-password-change/privacy-consent gate
   actually working, if that's worth a 10-second aside).
7. Have `grading-system.xlsx` (CITCI's real class record) open in a second window, ready to point
   at the Dela Cruz row if someone asks "how do you know the math is right" — `grading/tests.py::
   DelaCruzFinalGradeTests` is the test that verifies it.

## The walkthrough (~12 minutes of clicking, budget extra for Q&A)

### 1. Admin — the foundation (≈2 min)

- Log in as `admin`. **Dashboard**: point out the real counts (active students/instructors/
  classes/programs) — "this isn't placeholder data, it's live from the database."
- **Academic Setup → Classes**: show one class, point at the instructor column — "Unassigned" is a
  valid state here; the system never breaks on it.
- **Academic Setup → Teaching Loads**: "this is new — Program Heads assign who teaches each class
  in their program; Admin can still override it, but it's logged as an override, not a silent
  change." Click into a class's roster page to show the "Assignment history" panel if one exists.
- **Grading Templates**: show the CITCI Default template, the locked Examination row (40%, grayed
  out) vs. the unlocked ones — "the school fixes the exam weight; everything else is the
  instructor's call for their own class."

### 2. Instructor — where the data originates (≈3 min)

- Log in as `instructor`. **My Classes → Encode Grades** on the class with the most students.
- **Setup tab**: show the Grading Components panel, the live weight-total bar.
- **Class Record tab**: click a score cell, change it, tab to the next one — "autosaves on blur, no
  save button, keyboard navigation end to end." Point at the Forecast column badge on one row —
  "this recomputes synchronously after that save, in under 10ms measured — not a batch job."
- **Submit Grades**: open the pre-submit review modal, point at the missing-score/INC summary and
  the certify checkbox, then cancel (don't actually submit mid-demo unless you want to show the
  Program Head side receiving it live).
- **At-Risk Students**: click into one student's forecast drawer — the contributions chart, the
  plain-language reasons, the intervention log.

### 3. Program Head — the approval + teaching-load layer (≈2 min)

- Log in as `program_head`. **Grade Approvals**: show the status tabs and the Submitted count
  badge; open a submitted sheet's review page — the frozen snapshot table, the class distribution
  chart, Approve/Return.
- **Classes → Teaching Loads**: per-instructor totals (classes, units, students), the unassigned-
  classes list if any — "this is the real workload picture for the whole program, not something
  anyone has to tally by hand."
- **Dashboard**: point at the "Unassigned Classes" stat card — click through to the filtered list.

### 4. Student — what it all adds up to (≈2 min)

- Log in as `student`. **Dashboard**: point at the stat cards (GWA with the Official/Partial
  tooltip, Warnings), a subject card showing a running (unofficial) grade with its amber chip.
- **My Grades**: switch semesters, point at the Official vs. Partial GWA note, download the Report
  of Grades PDF — open it, point at the Registrar/Dean signature block.
- **Subject detail**: the component breakdown chart + running-grade-progression line chart.
- **Academic Forecast card** (if `show_forecasts_to_students` is on): read the supportive wording
  aloud — "never a number, never the words 'at risk' — this is deliberate, see CLAUDE.md section 7."
- **My Progress**: the GWA-history line chart across semesters.

### 5. Close — forecasting under the hood (≈2 min, optional if time is short)

- Back to `admin` → **Forecast Model**: the metrics table (accuracy/precision/recall/F1/ROC-AUC
  with bootstrap CIs), the 5-fold CV row, the threshold trade-off table, the coefficients/odds-
  ratios table. Point at the "Trained on SYNTHETIC data" banner if the active model is synthetic —
  "the model shown here for the demo is synthetic by design; the one defended in Chapter 4 is
  trained on real, masked CITCI historical data — see docs/CHANGES_FROM_PROPOSAL.md item 10."
- **Historical Data**: show the import batch list, the masked-identifier note — "names are never
  stored, SHA-256 salted hash only."

## If something breaks mid-demo

- A blank/error page: open a second tab to `/healthz` — if that's green, the problem is specific to
  the page, not the database/server; fall back to narrating the relevant test file instead
  (`grading/tests.py`, `forecasting/tests.py`) and move on.
- Wrong data on screen (e.g. a previous presenter's edits): don't fix it live — note it and
  continue; re-run the reset checklist before the next group's slot, not mid-presentation.
- A forecast looks "wrong": remember the demo model may be SYNTHETIC — that's expected and
  disclosed, not a bug.

## Anticipated questions and where the answer lives

- *"Why Django instead of the proposed Laravel/PHP?"* → `docs/CHANGES_FROM_PROPOSAL.md` item 1.
- *"Where's the separate FastAPI prediction service from the proposal?"* → item 2 — in-process by
  design, no network hop to fail.
- *"Why no assignment submission / quizzes?"* → item 3 — out of scope, this is a grading system.
- *"Who approves grades before students see them?"* → item 5 — the Program Head workflow, not in
  the original proposal.
- *"How do you know the grade computation is correct?"* → `grading/tests.py::
  DelaCruzFinalGradeTests`, hand-verified against `grading-system.xlsx` row 11.
- *"Is this model's accuracy real or synthetic?"* → check the banner on the Model Performance page;
  `docs/CHANGES_FROM_PROPOSAL.md` item 10 explains the governance rule.
- *"How fast is it really, not just in theory?"* → `docs/PERFORMANCE.md` — every page under 2s
  including a worst-case 450-student class; `CLAUDE.md`'s query-count pass notes for the specific
  before/after numbers.
