# CITCI GradeTrack — Build Specification for Claude Code

> **2026-10-25:** This file previously specified a Laravel/PHP/MySQL build. That has been
> superseded by the Django stack below (confirmed with the user), which is what now actually
> exists in the repository at `CITCI GradeTrack/`. The domain spec (roles, grading rules,
> forecasting design, screens, DB concepts) carries over unchanged — only the tech stack and phase
> framing changed. Phase 1 (auth/RBAC + navigation shell), Phase 2 (academic structure, revised in
> Phase 2.1), and Phase 2.2 (full user management — see below) are built; later phases below are
> the plan, not yet implemented.
>
> **2026-10-26:** This file now lives at the repository root (previously tracked one level up,
> outside the repo it describes). **Phase 4 (Grading) = this phase** — i.e. the work tracked below
> as "Phase 3 — Grading engine" in this file's own numbering (templates, assessment items, score
> encoding, grade computation) is done; see the Phase 3 bullet under "Build Phases" and section 4
> for what was actually built, which also supersedes section 4's old placeholder rules (Midterm/
> Final only, 25/25/10/40 weights) with CITCI's real class record — confirmed against
> `grading-system.xlsx` at the repo root.
>
> **2026-11-03:** Phase 4 part 1 (Grade Sheet Workflow) is done — the submit → approve/return →
> release → lock state machine, frozen-at-submission grade snapshots, in-app notifications, and the
> GWA service; see section 5 (superseding its old "not yet built" framing) and the Phase 4 part 1
> bullet under "Build Phases". **Phase 4 part 2 (Reports & exports) is also done** — Institution
> Settings, the Grade Sheet PDF, the formula-driven Class Record Excel export/import, and the
> role-aware Reports page; see sections 4/6/8 and the Phase 4 part 2 bullet under "Build Phases".
> A same-day follow-up pass fixed a provisional-remarks bug in grade sheet snapshots, made PDF
> images resolve offline (`reports/pdf.py:link_callback`), and added "create as new item" to the
> Excel import — see the "Phase 4 part 2 fixes" bullet under "Build Phases".
>
> **2026-11-03 (later the same day):** **Phase 5 (Student portal) is also done** — student
> dashboard, My Grades, Subject detail, My Progress, and a Report of Grades PDF, all scoped to
> `request.user`'s own data and clearly distinguishing OFFICIAL (released snapshot) from UNOFFICIAL
> (live running grade); see section 8's "Student" entry and the Phase 5 bullet under "Build Phases".
> Forecasting (O4) is still not built — the dashboard's "Academic Forecast" card is a clearly-marked
> placeholder.

**Enrollment is out of scope.** CITCI GradeTrack does not handle student enrollment — that is the
Registrar's own process, outside this system entirely. GradeTrack only stores each class's official
student list (the "class list" / roster), imported or managed by hand, so instructors have someone
to encode grades for. Never use the word "enroll"/"enrollment" in code, UI copy, or model names for
this — the model is `academics.ClassRosterEntry`, not `Enrollment`; menu item and pages say "Class
Lists", not "Enrollment".

You are building **CITCI GradeTrack: A Grading Management System with Academic Performance
Forecasting** for the College Department of Candelaria Institute of Technology in Cabadbaran Inc.
(CITCI), Philippines. This is an undergraduate capstone project, built one phase at a time. When
something is unclear, choose the simplest option that satisfies the objectives below.

**This is a grading management system, NOT a full LMS.** Do not build course-material uploads,
student assignment submission, online quizzes, or login-activity tracking.

---

## 1. Approved Objectives (everything must trace back to these)

| # | Objective | Delivered by |
|---|---|---|
| O1 | Design system architecture, ERD, and mobile-responsive UI | `docs/` diagrams, Tailwind responsive layouts |
| O2 | Instructor module: grade encoding, automated GWA computation, PDF/Excel grade sheets | Grading + Workflow phases |
| O3 | Student module: grade viewing, progress visualization, personalized forecasts | Student portal + Integration phases |
| O4 | Academic performance forecasting using logistic regression | Forecasting service + Integration phases |
| O5 | Testing: ISO/IEC 25010 evaluation + model accuracy, precision, recall, F1 | Testing & evaluation phase |

---

## 2. Tech Stack

**Main app**
- Python 3.12+, Django 5.2 LTS
- PostgreSQL (via psycopg 3); credentials from `.env` (django-environ, `.env.example` committed)
- Auth: Django's built-in auth, custom `User` model (`accounts.User`), self-registration **disabled**
- UI: Django Templates + HTMX + Alpine.js (downloaded, served locally from `static/vendor/` — no
  CDN) + Tailwind CSS via `django-tailwind-cli` (no Node.js build step) + Chart.js (added when
  charts are actually needed, same local-vendoring rule)
- PDF/Excel export: added in the grading-workflow phase (e.g. `weasyprint`/`reportlab` and `openpyxl`)
- Tests: Django's test runner (`manage.py test`), app-per-module test files
- Queue: added when forecasting jobs need one (Django's own management commands + cron, or
  `django-rq`/Celery if warranted — decide when that phase starts)
- Local dev: PostgreSQL running locally; see `README.md` for Windows setup

**Forecasting service** (`/ml-service`, separate folder in the same repo, added in its own phase)
- Python 3.11+, FastAPI, scikit-learn, pandas, numpy, joblib, pydantic, pytest
- Called by Django over HTTP with a shared API key header (`X-API-KEY`, from `.env` on both sides)
- Django must keep working if the ML service is down (show "Forecast unavailable", log the error,
  retry via a scheduled job)

## Brand palette

Extracted from `static/img/citci-logo.png` via a Pillow dominant-color scan:
- `brand-primary` (navy, measured `#283082`) — sidebar background, headers, dark surfaces.
- `brand-accent` (gold, measured `#f0dc1e`) — active menu state, primary buttons, focus rings.
- Full 50–950 Tailwind shade scales for both live as `@theme` tokens in
  `.django_tailwind_cli/source.css` — the single source of truth for the palette. Change the two
  base hexes there (and regenerate the scale) if the logo ever changes.
- White text on `brand-primary-600`/`-700` and dark text on `brand-accent-600` both clear WCAG AA
  (11–15:1 measured) — no adjustment was needed.

---

## 3. User Roles & Accounts

No public registration. Admin creates accounts manually (Users page) or via .xlsx/.csv bulk import
(Phase 2.2 — "Import Students"/"Import Instructors", both built on the shared parser in
`core/importing.py`). All new accounts must change password on first login, then acknowledge the
Data Privacy notice (RA 10173) — both enforced before any other page is reachable. Students log in
with student number or email. 5 failed logins locks that username for 15 minutes (django-axes, by
username not IP); sessions expire after 30 minutes of inactivity or on browser close.

| Role | Can do |
|---|---|
| **admin** (Registrar/System Admin) | Manage users (CRUD, bulk import, activate/deactivate, reset password); manage programs, academic terms, subjects, class offerings (sections); assign instructors; manage class lists (import from the Registrar); configure grading templates and transmutation table; lock/unlock terms; import historical data; train/activate ML model versions and view model metrics; view audit logs; system-wide reports |
| **program_head** | View department dashboard (grade distribution, at-risk counts per class/subject); view at-risk list with contributing factors; approve or return submitted grade sheets; release approved grades; export reports |
| **instructor** | View assigned classes only; adjust grading component weights for own class (within template rules); create assessments; encode scores (inline table + Excel import using downloadable template); see auto-computed grades live; submit grade sheet; export PDF/Excel grade sheet; view class at-risk list with factors; add intervention notes per student |
| **student** | View own class-list subjects, running grades per component, period grades, released final grades; term GWA + cumulative GWA; progress charts; own forecast shown as **"Needs Attention" / "On Track"** (never the words "at-risk") with plain-language contributing factors and generic tips; notifications |

Enforce access with middleware + Django Policies (view-level `role_required`/`RoleRequiredMixin`
today; move to per-object permission checks once there's per-object data to protect). Instructors
must never see classes not assigned to them; students only their own data. Write tests for every
authorization rule — `accounts/tests.py` has the pattern (login, menu visibility, 403s).

---

## 4. Grading Rules (built, Phase 3 — confirmed against CITCI's actual class record)

`grading-system.xlsx` (repo root) is CITCI's official class record — the rules below are verified
against it to full Decimal precision, not a placeholder default. Weights/components are DB-backed
(`grading.GradingTemplate` + `GradingComponent`) so CITCI can change them without code changes; a
class never references the template directly — see the frozen-snapshot note below.

**Grading periods ("terms", `grading.AssessmentTerm`):** Prelim, Midterm, Semi-Final, Final — not
to be confused with `academics.Term` (1st Sem/2nd Sem/Summer). Each `AssessmentItem` is tagged with
one of these four; this is the checkpoint forecasting will key off later.

**Default components (the seeded "CITCI Default" template, weights total 100%):**
- Attendance — 5%
- Quizzes — 30%
- Recitation — 15%
- Project — 10%
- Examination — 40% (its four items are literally named Prelim/Midterm/Semi-Final/Final Exam)

**Instructor-defined components, school-locked Examination weight (confirmed CITCI practice,
built):** Examination's weight is fixed by the school (`GradingComponent.is_locked` /
`SchemeComponent.is_locked` — the "CITCI Default" template locks Examination at 40%); every other
component — including whether it even exists, its name, its category, and its weight — is each
instructor's call for their own class. The Setup tab's "Grading Components" panel lets an
instructor add/rename/reweight/delete their own (unlocked) components; a locked component is
read-only there (lock icon, "Set by the school" tooltip) and `grading/forms.py`'s
`SchemeComponentForm.clean()` rejects any attempt to change one server-side regardless of what the
UI allows, on top of `GradingTemplateForm`/`GradingComponentForm` on the admin side gaining the
same `is_locked` toggle (so an admin, not an instructor, decides what's locked and at what weight;
"Instructor-defined share" = 100 − the template's locked total). Saving the whole components panel
is one atomic formset submission — add/rename/reweight/delete together — validated so **locked +
unlocked weights must total exactly 100** before it's accepted; a component can't be deleted while
any of its items has a score (move or delete those items first — `AssessmentItemForm`'s `component`
field already lets an item be moved to a different component). Every add/edit/delete is logged to
`grading.SchemeComponentChangeLog` (who, when, before → after JSON) and shown in a collapsible
"Change history" panel. Editing is allowed until the class's grades are submitted — the Approvals
phase (not built yet) will add that lock. Grades recompute live off whatever the current weights
are (`compute_student`/`compute_class` read `SchemeComponent` fresh every call — nothing to
invalidate).

**Component categories (built):** every `GradingComponent`/`SchemeComponent` also carries a
`category` — `ATTENDANCE` / `QUIZ` / `RECITATION` / `PROJECT` / `EXAM` / `OTHER`
(`grading.ComponentCategory`) — independent of its free-text `name`, since instructors can rename a
component however they like (e.g. "Participation" is still category `ATTENDANCE`). **Forecasting
(Phase 6/7, not built yet) will key its features off `category`, never off component `name`** — the
name is purely a display label an instructor controls; the category is what makes a renamed/
instructor-invented component still meaningful to the ML feature pipeline.

**Computation** (`grading/services.py` — pure functions, Decimal throughout, never float)
1. Component grade = 5 − 4 × (Σ scores ÷ Σ max scores) for that component's assessment items.
   1.00 is the best possible grade, 5.00 the worst — **not** a 0–100% scale.
2. Final grade = Σ (component grade × weight). **Passing** = final grade ≤ 3.00.
3. **Running grade** (shown mid-term, `StudentGradeResult.running_grade`): only components with at
   least one score encoded *anywhere in the class* count, remaining weights re-normalized to 100%
   — a component nobody has started yet is excluded rather than dragging the grade toward 5.00.
4. **Final grade** (`StudentGradeResult.final_grade`): always every component and every item; any
   still-blank cell counts as 0. `StudentGradeResult.missing_items` lists the blanks for the UI's
   warning banner.
5. Round only for display (`settings.GRADE_DISPLAY_DECIMALS`, default 2 — e.g. 1.77); the
   stored/computed value keeps full Decimal precision throughout.
6. Hand-verified test case: `grading/tests.py::DelaCruzFinalGradeTests` (row 11 of the xlsx — Dela
   Cruz, Juan B. → component grades 1.4000/1.9524/1.7765/1.3657/1.7889 → final grade
   1.7743118580765638... → displayed 1.77 → PASSED).

**No transmutation table** — unlike the original placeholder spec, CITCI's real class record
transmutes nothing; the component-grade formula above already lands directly on the 1.00–5.00
scale. The transmutation-table idea from the superseded spec does not apply here.

Special marks: **INC** (Incomplete, `ClassRosterEntry.is_incomplete` + `incomplete_reason`, set
manually by the instructor per student with a required reason) and **DROPPED** (roster status,
already existed). No **DRP** mark separate from roster status — a dropped student's remarks is
just "DROPPED".

**Frozen snapshot:** a class never references a `GradingTemplate` directly. The first time anyone
opens its grading page, `ClassGradingScheme.get_or_create_default` copies the template's
components onto a per-class `ClassGradingScheme` + `SchemeComponent` rows — editing the template
later never changes a class already using it. Admin can re-apply a different template to a class
only while it has zero scores encoded (`ClassGradingScheme.has_scores`).

GWA (term/cumulative, `is_included_in_gwa`, "Provisional" until released) is **not built yet** —
that's still Phase 4 (Workflow & reports), once grade sheets have a submit/release lifecycle to
hang "Provisional" off of.

**GWA**
- Term GWA = Σ(final grade × units) ÷ Σ(units), for subjects in that term where `is_included_in_gwa = true`
- Exclude INC/DRP from GWA and show a note
- Show **"Provisional"** until all of the student's subjects in that term are released
- Cumulative GWA across all released terms
- Write unit tests with hand-computed examples for every formula above

---

## 5. Grade Sheet Workflow (built, Phase 4 part 1 — see the build-phase note below for part 2)

`draft → submitted → approved → released → locked`, plus `returned` (program head sends back with
remarks → instructor edits → resubmits). One `approvals.GradeSheet` per (`ClassOffering`, period) —
`period` defaults to FINAL today; MIDTERM is a reserved, unused choice (CITCI hasn't confirmed
whether midterm grades get their own submit/approve cycle) so adding it later needs no schema
change, just a UI entry point. Every transition goes through `approvals/services.py` — explicit
allowed-from-status checks (`_require_status`), never a bare `sheet.status = ...` in a view — and is
logged to `approvals.GradeSheetTransition` (shown as a timeline on the review page).

- **Instructor edits only while DRAFT/RETURNED** (or no sheet row exists yet, which is the same as
  DRAFT) — enforced server-side via `approvals.services.is_class_editable`, consulted from
  `grading.views._can_edit` (a function-local import; `approvals` imports `grading.services` at
  module level, so the reverse direction can only be local to avoid an import cycle at app-loading
  time). Every grading mutation route (`save_cell`, `fill_column`, `mark_incomplete`,
  `class_components_save`, assessment-item CRUD) already runs through `_can_edit`, so this one
  change locks all of them at once. The class grading page shows a status badge next to the title,
  a "Submit Grades"/"Resubmit Grades" button when appropriate, and a banner explaining *why* it's
  read-only (e.g. "Submitted on Nov 3 — awaiting Program Head approval") or showing the Program
  Head's return remarks prominently.
- **Submit** (`approvals.services.submit_grade_sheet`) is blocked if any active, non-INC student has
  a missing score (`missing_score_students`) — the instructor sees a pre-submit review modal first
  (counts, class average, the specific missing cells/INC students, a required "I certify these
  grades are final and correct" checkbox). On success it **snapshots** every roster entry's
  `compute_student()` result into `approvals.GradeSheetEntry` (final grade, remarks, INC reason, a
  JSON component breakdown) — approved/released grades always read from this snapshot, **never**
  recomputed live. Re-submitting (after a return) replaces the whole snapshot, not a diff.
- **Approve / Return** — Program Head of the class's program (a class shared across programs via
  its M2M `sections` can be approved/returned by *any* of those programs' heads — see
  `approvals.views._program_head_owns`). Return requires remarks (shown on the instructor's class
  page) and sends the sheet back to RETURNED, editable again.
- **Release** — Program Head or Admin, only from APPROVED. Makes the snapshot official (students
  will see it once the student portal phase exists). "Release all approved" releases every APPROVED
  sheet for the Program Head's program(s) in the active semester in one action.
- **Lock** — Admin only, "Lock term" locks every RELEASED sheet in the active semester at once
  (with a confirmation showing the count). Locked (and released) grades can only change through an
  admin **grade correction** (`approvals.services.correct_grade`, required reason) — logged to
  `approvals.GradeCorrection` and the sheet's timeline; the corrected entry shows a "Corrected" tag.
- **Notifications** (`dashboard.Notification`, `dashboard.services.notify`/`notify_many`) fire on
  submit (→ every owning Program Head), return (→ instructor, includes remarks), approve
  (→ instructor), release (→ instructor — students get theirs once the portal phase exists), and
  correction (→ instructor). Topbar bell: unread badge + dropdown (latest 10, HTMX-polled every
  60s via `dashboard:bell`; `notifOpen` lives on `base.html`'s body-level Alpine state, not inside
  the polled fragment, so an open dropdown survives each poll instead of snapping shut). Clicking a
  notification is a **plain link** (not `hx-*`) to `dashboard:mark_read`, which marks it read then
  redirects to its `link` — htmx intercepts clicks on elements carrying its own attributes, so an
  `hx-post` on the same `<a>` would have eaten the navigation.
- **GWA** (`approvals.services.compute_gwa`) — Σ(final grade × units) ÷ Σ units over a student's
  RELEASED/LOCKED `GradeSheetEntry` rows in a semester, excluding DROPPED and INC; `is_complete` is
  False if any of the student's (non-dropped) classes in that semester isn't released yet or carries
  an INC. Decimal throughout, quantized to 2 places. No UI yet beyond what the review pages show —
  full display is the student portal phase (O3).
- Students still see **running (unofficial) component scores** during the term (student portal
  phase, not built yet), clearly labeled "Unofficial"; official final grades only after `released`.

**Not built this pass (Phase 4 part 2):** PDF/Excel grade-sheet exports.

---

## 6. Database Schema

Use migrations, foreign keys, indexes, and soft deletes where sensible. Minimum tables, one Django
app per group (`accounts`, `academics`, `grading`, `approvals`, `forecasting`, `reports`). `core`
holds only the abstract `TimeStampedModel` (`created_at`/`updated_at`) every model below extends.

**Built (`accounts`, Phase 1):**
- `accounts.User` — username, email, id_number, role enum, is_active, must_change_password,
  privacy_consent_at, middle_name, timestamps

**Built (`academics`, Phase 2 + Phase 2.1 revisions)** — academic FKs use `on_delete=PROTECT`
(friendly error + a "Deactivate instead" escape hatch in the UI where the model has `is_active`),
not cascade-delete. The hierarchy is **Program → Major (optional) → Section**:
- `academics.AcademicYear` — start_year (unique), end_year (derived in `save()`, not form-editable)
- `academics.Semester` — academic_year FK (PROTECT), term enum (FIRST/SECOND/SUMMER, see `Term`),
  start_date, end_date, is_active — `save()` deactivates every other semester in a transaction, so
  exactly one (or zero) is ever active app-wide
- `academics.Program` — code (unique), name, program_head FK User (role=PROGRAM_HEAD, nullable), is_active
- `academics.Major` — program FK (PROTECT), code, name, is_active; unique per (program, code). A
  program may have zero majors (e.g. TCP) — this is why Section/Subject/StudentProfile.major is nullable.
- `academics.Section` — program + major (nullable) + academic_year FK (PROTECT), year_level
  (1–4, nullable — some programs have no year levels), name (blank allowed); unique per (program,
  major, academic_year, year_level, name). `__str__` e.g. "BSED-ENG 1", or just "TCP" with no major/year/name.
- `academics.Subject` — code (unique), title, **units** (single Decimal — not split lec/lab),
  program FK (PROTECT, nullable = shared across programs — most Gen Ed/Prof Ed subjects), major FK
  (PROTECT, nullable — only for major-specific subjects), year_level (nullable), term, is_active
- `academics.StudentProfile` — user OneToOne (role=STUDENT; auto-created by a `post_save` signal in
  `academics/signals.py`), program/major/year_level/section (all nullable until admin assigns them)
- `academics.ClassOffering` ("Class") — subject FK (PROTECT) + **sections** `ManyToManyField`
  (a class can serve several sections at once — e.g. one Gen Ed class shared by two majors — same
  instructor/room/schedule for all of them) + semester FK (PROTECT), instructor FK User
  (role=INSTRUCTOR, nullable), schedule, room, is_active; `roster_count` property. `clean()` can only
  check the sections-vs-semester academic-year match once the instance has a pk (M2M needs one), so
  the real enforcement is in `ClassOfferingForm.clean()` (forms.py), not the model.
- `academics.ClassRosterEntry` — **not enrollment** (see the scope note at the top of this file) —
  student FK User (role=STUDENT) + class_offering FK (both PROTECT), status enum (ACTIVE/DROPPED),
  date_added (auto), date_dropped; unique per (student, class_offering) — dropping sets status +
  date, never deletes the row. Built/managed via `academics/roster_import.py` (the "Import class
  list" .xlsx/.csv flow — matches by `id_number`, creates a new STUDENT user if none exists) and the
  Class Lists page's manual add-entire-section / add-students / mark-dropped / restore actions.

The active semester is available in every template as `active_semester` via
`academics.context_processors.active_semester` (registered in `TEMPLATES.OPTIONS.context_processors`).

Also added this phase: `academics.ClassRosterEntry.is_incomplete` (bool) + `incomplete_reason`
(text) — the INC special mark, set by the instructor per student.

**Built (`grading`, Phase 3)** — names differ from the original placeholder spec below (that spec
assumed a 2-period Midterm/Final design with a separate transmutation table; the real CITCI class
record needed neither — see section 4):
- `grading.GradingTemplate` — name (unique), description, is_default (only one at a time —
  `save()` unsets every other default in a transaction), is_active
- `grading.GradingComponent` — template FK (CASCADE), name, category (`ComponentCategory`:
  ATTENDANCE/QUIZ/RECITATION/PROJECT/EXAM/OTHER), weight (whole-number percent — `PositiveIntegerField`,
  not Decimal), is_locked (school-fixed — e.g. Examination 40% in "CITCI Default"), order; unique
  per (template, name)
- `grading.ClassGradingScheme` — class_offering OneToOne (CASCADE), source_template FK (PROTECT —
  blocks deleting a template still referenced by a class's snapshot). `apply_template()` copies the
  template's current components (incl. category/is_locked) onto fresh `SchemeComponent` rows
  (validates weights total 100% first); `get_or_create_default()` lazily creates one using the
  default/first active template.
- `grading.SchemeComponent` — scheme FK (CASCADE), name, category, weight (whole-number percent),
  is_locked, order — the frozen per-class copy of a `GradingComponent`, **then independently
  instructor-editable for the unlocked ones** (see section 4); `AssessmentItem` points here, never
  at `GradingComponent` directly.
- `grading.SchemeComponentChangeLog` — scheme FK (CASCADE), action (ADDED/EDITED/DELETED),
  component_name (plain text snapshot, survives the component's own deletion), before/after
  (JSONField — `{name, category, weight}` snapshots), changed_by FK User, changed_at — written by
  `grading.views.class_components_save` for every row the instructor adds/edits/deletes; shown in
  the Setup tab's "Change history" panel.
- `grading.AssessmentItem` — class_offering FK (CASCADE) + component FK (PROTECT, blocks deleting a
  component that has items), title, max_score (whole-number — `PositiveIntegerField`, matches
  CITCI's class record), term (`AssessmentTerm`: PRELIM/MIDTERM/SEMIFINAL/FINAL, required — this is
  what forecasting's mid-semester checkpoint will key off), date (nullable), order
- `grading.Score` — roster_entry FK (CASCADE) + item FK (CASCADE), score (whole-number, nullable =
  not yet encoded — `PositiveIntegerField`), updated_by FK User; unique per (roster_entry, item)
- `grading.ScoreChangeLog` — score FK (CASCADE), old_value, new_value (whole-number), changed_by FK
  User, changed_at — written by `grading.services.save_score()` on every value change (not on saves
  that don't actually change the value)

**Built (`approvals`, Phase 4 part 1):**
- `approvals.GradeSheet` — class_offering FK (CASCADE), period (`GradeSheetPeriod`: FINAL/MIDTERM,
  default FINAL — MIDTERM reserved, unused), status (`GradeSheetStatus`:
  DRAFT/SUBMITTED/RETURNED/APPROVED/RELEASED/LOCKED, default DRAFT), submitted/approved/
  released/locked_at + _by (each nullable FK User), return_remarks (most recent, shown on the
  instructor's page while RETURNED); unique per (class_offering, period).
  `get_or_create_draft()` lazily creates the DRAFT row; `is_editable` property is
  `status in (DRAFT, RETURNED)`.
- `approvals.GradeSheetEntry` — sheet FK (CASCADE) + roster_entry FK (PROTECT), final_grade
  (Decimal, nullable), remarks (PASSED/FAILED/INC/DROPPED), inc_reason, components_json (list of
  `{name, category, weight, earned, possible, grade}`, numbers stored as strings since Decimal
  isn't JSON-native) — the frozen-at-submission snapshot; unique per (sheet, roster_entry).
  `is_corrected` property = `self.corrections.exists()`.
- `approvals.GradeSheetTransition` — sheet FK (CASCADE), from_status, to_status, actor FK User,
  remarks, timestamp — the audit trail + review-page timeline. A grade correction also writes one
  of these with `from_status == to_status` (the sheet's own status doesn't change), so it still
  shows up on the timeline.
- `approvals.GradeCorrection` — entry FK (CASCADE), old/new_grade, old/new_remarks, reason
  (required), corrected_by FK User, timestamp.

**Built (`dashboard`, Phase 4 part 1):**
- `dashboard.Notification` — recipient FK User (CASCADE), title, message, link, is_read,
  created_at. Created via `dashboard.services.notify()`/`notify_many()`, never directly.

**Built (`reports`, Phase 4 part 2):**
- `reports.InstitutionSettings` — singleton (`save()` forces `pk=1`, `delete()` is a no-op,
  `get_solo()` is the only way callers should fetch it), school_name/sub_line/address/department,
  logo (ImageField, falls back to `static/img/citci-seal-256.png` when blank), dean_name/
  dean_title/academic_head_name/academic_head_title — every PDF/Excel report header and signature
  block reads from this instead of hardcoding institution info in a template. **Added Phase 5:**
  registrar_name/registrar_title (signs a student's own Report of Grades PDF — the one report the
  Dean doesn't sign) and show_unofficial_scores_to_students (BooleanField, default True — the
  student portal's OFFICIAL-vs-UNOFFICIAL toggle, see section 8).

**Still to add:**
- `grading.GwaRecord` or similar — not needed yet, `approvals.services.compute_gwa()` is cheap
  enough at this data scale and now powers every student-facing GWA display (Phase 5).
- `forecasting.MlModelVersion` (version, trained_at, training_source enum synthetic/historical, n_samples, threshold, accuracy, precision, recall, f1, ci_json, confusion_matrix_json, coefficients_json, is_active)
- `forecasting.Prediction` (roster_entry, ml_model_version, probability, risk_label enum needs_attention/on_track, features_json, contributions_json, created_at)
- `forecasting.Intervention` (roster_entry, instructor, note, created_at)
- `forecasting.HistoricalRecord` (masked_student_key, subject_code, school_year, semester, feature columns, final_outcome) — for model training only, no names
- `accounts.AuditLog` (user, action, auditable model/id, old_values json, new_values json, ip, created_at)

Produce `docs/ERD.md` as a Mermaid `erDiagram` that matches the final migrations exactly, once these exist.

---

## 7. Forecasting Module (Logistic Regression — not yet built)

**Goal:** predict, **mid-semester**, whether a student will fail a subject, so the instructor can
intervene early.

**Target label (y = 1):** final grade 5.00, INC, or DRP. Otherwise 0.

**Features** (grade-based only, all available by midterm, all scaled 0–100) — **keyed off
`grading.ComponentCategory`, never off a component's free-text `name`**, since instructors rename
and reweight their own (unlocked) components per class (section 4) — a feature-extraction query
groups `SchemeComponent`/`Score` by `category` (e.g. sum every `QUIZ`-category component's
earned/possible, regardless of what the instructor called it) so a renamed/instructor-invented
component still feeds the right feature:
1. `midterm_grade_pct`
2. `quiz_avg_pct` (category=QUIZ)
3. `activity_avg_pct` (category=PROJECT, and/or RECITATION/OTHER — finalize the category→feature
   mapping when this phase starts)
4. `attendance_pct` (category=ATTENDANCE)
5. `midterm_exam_pct` (category=EXAM, term=MIDTERM)
6. `missing_rate_pct` (% of assessments with no score so far)

**Pipeline:** `StandardScaler` → `LogisticRegression(class_weight="balanced", max_iter=1000)`,
fitted with maximum likelihood (scikit-learn default solver).

**Threshold:** default 0.5, stored per model version, adjustable by admin. Prioritize recall in the
evaluation write-up.

**Explainability:** for each prediction return per-feature contribution = coefficient × standardized
value, sorted by impact, plus a plain-language message (e.g., "Quiz average is lower than usual for
passing students"). Store in `predictions.contributions_json`.

**Training data**
- `ml-service/scripts/generate_synthetic.py` — realistic synthetic dataset (≈2,000 rows, ~15–25%
  positive class, correlated features, random seed fixed). Used for initial deployment and demo.
- Historical import: admin uploads CSV/Excel of past CITCI records → Django **masks** student
  identifiers (SHA-256 with app-secret salt, names dropped) before saving to `historical_records`.
  Only masked data is ever sent to the ML service.

**Evaluation** (on every training run)
- Stratified 80/20 train-test split, fixed random seed
- Accuracy, precision, recall, F1, confusion matrix, ROC-AUC
- 95% confidence intervals via 1,000 bootstrap resamples of the test set
- Results saved to `ml_model_versions` and shown on an admin "Model Performance" page; exportable as
  PDF for Chapter 4

**ML service endpoints**
- `GET /health`
- `POST /train` — body: training rows + threshold → returns version, metrics, CIs, coefficients
- `POST /predict` — body: list of feature rows → returns probability, label, contributions per row
- `GET /model` — active model info
- Save models with joblib under `ml-service/models/{version}.joblib`

**When predictions run (Django)**
- Queued/scheduled job after an instructor saves scores, debounced per class
- "Recompute forecasts" button for instructors/program heads
- Nightly scheduled job for all active class-list entries in the current term
- Only predict when at least the midterm period has some scores; otherwise show "Not enough data yet"

**Early warning:** when a student's label changes to `needs_attention`, notify the instructor (and
program head summary). Notify the student with a supportive message and generic study tips. Never
show raw probability to students; instructors and program heads see probability + factors.

---

## 8. Screens

**Shared (built):** login (locked-out message via django-axes), forced password change (doubles as
a voluntary "Change Password" page — `accounts:force_password_change` has no must-change-password
guard, it just also redirects to privacy consent if that's still outstanding), profile (view all
fields; the only one the user can edit themselves is email — name/ID/role changes are admin-only),
help (placeholder), notifications bell (built, Phase 4 part 1 — unread badge + dropdown, HTMX-
polled every 60s, see section 5), responsive sidebar/topbar layout, Data Privacy notice/consent
shown on first login (RA 10173), styled 403 page.

Layout specifics worth preserving: the sidebar is flush against the left edge (no outer margin/
rounded corners/shadow — only inner elements like the active-item tile and popover are rounded);
its header row and the topbar share one `h-16` height with borders that line up into a single
horizontal divider; the topbar carries only the page title/subtitle and the notification bell — no
duplicate user info; the sidebar footer's user card is a single clickable element (Alpine popover,
opens upward, closes on outside-click/Escape) with Profile/Help/Change Password/Logout — there is no
separate quick-action icon row. Every page sets `{% block page_title %}` directly in `base.html`
(not in an included partial — Django block tags don't cross an `{% include %}` boundary) to drive
both that topbar heading and, implicitly, what the page is for; the `<title>` tag itself is static
("CITCI GradeTrack") since Django disallows the same block name appearing twice in one template.

**Admin (built, Phase 2):** dashboard with real counts (active students/instructors/active
classes/programs) · Academic Years & Semesters (two tables, one page, "Set as active") · Programs
(program_head dropdown only lists active PROGRAM_HEAD users) · Sections · Subjects · Classes
(+ read-only roster; instructor field uses the searchable-select widget) · Class Lists (pick a
class via the searchable-select widget → roster, Add Entire Section, Add Students multi-select
with live search, Mark as Dropped/Restore, Import class list from an .xlsx/.csv). All these
list pages share one generic pattern — search + filters + pagination, HTMX-swapped table, Add/Edit
via a modal form, Delete via a modal confirm that offers "Deactivate instead" when a `PROTECT` FK
blocks it — implemented once in `core/crud.py` (`EntityListView`/`EntityFormView`/
`EntityDeleteView`/`ToggleActiveView`) rather than per page.

**Admin — Users (built, Phase 2.2):** replaces the old read-only Students list. Tabs (All/Admins/
Program Heads/Instructors/Students, each with a live count) + search (name/username/ID number) +
filters (role, status, and for students program/major/year level/section) + pagination, same
generic list pattern as above (`accounts.views.UserListView`, extends `core.crud.EntityListView`).
Add/Edit via a modal (`accounts.forms.UserForm`) with HTMX-cascading program → major → section
dropdowns for students; username is forced to the ID number for students, admin-chosen (with a
surname-based suggestion) for staff. A new or password-reset account gets a generated temporary
password shown once in a copyable box (`accounts/_user_password_reveal.html`) and must change it
on next login. Row actions: Edit, Reset Password, Deactivate/Reactivate (blocked for your own
account and for the last active admin — `accounts.views.user_toggle_active`), Unlock (clears a
django-axes lockout). "Import Students"/"Import Instructors" (.xlsx/.csv) share one upload →
preview (new/update/invalid-with-reason) → confirm flow with the Phase 2.1 class-list importer,
built on the same parser (`core/importing.py`); confirming returns a downloadable `.xlsx` of new
accounts' temporary passwords, generated in memory for that response only.

**Admin — Grading Templates (built, Phase 3):** list/add/edit templates (`grading:templates`),
live weight-total badge (green at 100%, amber otherwise — a template over/under 100% can't be
applied to a class until fixed), "Classes Using It" count, set-default, deactivate. Each template's
components get their own add/edit/delete sub-page (`grading:template_components`) — now also
showing category, a lock toggle, school-locked weight total, and "Instructor-defined share" (100 −
locked total); only admin can lock a component or set its fixed weight. Editing a template never
touches a class's existing `ClassGradingScheme` snapshot. Admin can also view any class's grading
page read-only and change its template via "Change Template" (blocked once the class has any score
encoded).

*(Transmutation scale doesn't apply here — see section 4. Historical data import and model training
are still placeholder pages.)*

**Admin — Grade Sheets (built, Phase 4 part 1):** `approvals:admin_sheets`, under Management. Every
grade sheet in the active semester, filterable by program/status/instructor, a funnel progress
summary ("X / Y submitted", "X / Y approved", "X / Y released" — each cumulative: "submitted" means
SUBMITTED-or-further, not currently-exactly-SUBMITTED), a "Lock Term" button (confirms the count of
RELEASED sheets it's about to lock), and a "View" link into the same read-only review page the
Program Head uses, with a "Correct grade" action per entry once the sheet is RELEASED/LOCKED.

**Program Head (built, Phase 4 part 1):** Classes (built, Phase 2 — read-only, classes in the
active semester for programs they head, object-level-checked: a different program head gets 403) ·
**Grade Approvals** (`approvals:index`) — status tabs (Submitted/Returned/Approved/Released/All)
each with a live count, a sidebar badge showing the SUBMITTED count · **Review page**
(`approvals:review`) — read-only snapshot table (always from `GradeSheetEntry`, never recomputed),
class summary + Chart.js distribution, the transition timeline, and Approve / Return (remarks
required, modal) / Release buttons gated by the sheet's current status · "Release all approved"
releases every APPROVED sheet across the Program Head's program(s) in the active semester in one
action. **Reports page** (built, Phase 4 part 2 — `reports:index`) adds, for a chosen semester:
Grade Submission Status, Class Performance Summary, Students with Failing/INC Grades (table +
Excel export each), and a per-program Program Grade Report PDF — all scoped to the Program Head's
own program(s) at the query level (`reports.views._scope_programs`). *(Dashboard grade-distribution
chart and At-Risk Students are still placeholders — those are the forecasting phase.)*

**Instructor (built, Phase 4 part 1):** My Classes (built, Phase 2 — card layout, active-semester
classes; "Encode Grades" button links to the class grading page below) · Class Grading page
(`grading:class_grading`, built Phase 3) with three tabs, all server-rendered together and switched
client-side via Alpine `x-show` (no per-tab page load) — now status-aware: a status badge next to
the title, a "Submit Grades"/"Resubmit Grades" button, a banner explaining *why* the page is
read-only once submitted, and the Program Head's return remarks shown prominently while RETURNED:
  - **Setup** — the "Grading Components" panel (`grading:class_components_save`): an editable
    formset, one row per component — locked ones (e.g. Examination) read-only with a lock icon and
    a "Set by the school" tooltip, unlocked ones freely rename/recategorize/reweight/delete
    (`+ Add component` clones a blank row client-side), a live "Instructor share: X / Y%" progress
    bar (green only at exactly the target), Save disabled until locked+unlocked totals exactly
    100%, and a collapsible "Change history" panel off `SchemeComponentChangeLog`. Below that,
    assessment-item CRUD (add/edit/delete, delete blocked with a warning if the item already has
    scores, confirmable anyway; an item can be moved to a different component from its edit form)
  - **Class Record** — the spreadsheet-style encoding grid: sticky header + first three columns,
    gold scrollbar (`.gold-scroll`, same look as the sidebar's), inline cell autosave on blur
    (`hx-trigger="blur changed"`, re-renders just that row), keyboard Up/Down/Left/Right/Enter
    navigation (`static/js/grading-grid.js`), per-item "Fill Column" (blanks only, confirm first),
    term filter (display-only — doesn't change what counts toward a grade), per-student "Mark INC",
    missing-score warning banner
  - **Summary** — passed/failed/INC/dropped counts, class average, Chart.js grade-distribution bar
    chart (vendored, `static/vendor/chartjs/`), per-student component/running-grade table
  All three tabs become read-only (server-enforced, not just hidden buttons — see section 5) once
  the grade sheet leaves DRAFT/RETURNED. **Submitted Grades** (`approvals:submitted`, replaces the
  old placeholder) — the instructor's own grade sheets in the active semester, status-filterable.
  **Built, Phase 4 part 2:** "Export Excel" (Class Record, formula-driven) and "Grade Sheet PDF"
  buttons on the class grading page header; on the Class Record tab, "Download blank class record"
  and "Import from Excel" (preview → confirm, DRAFT/RETURNED only) next to the missing-score
  banner. Forecast is still a placeholder (O4 phase).

**Student (built, Phase 5):** a student only ever sees their OWN roster entries — every lookup
filters by `student=request.user` (or a roster_entry already scoped that way), and a mismatched pk
404s rather than 403s, so a student can't even learn another roster entry id exists. Two kinds of
grades, never mixed up: **OFFICIAL** (`approvals.GradeSheetEntry` snapshots of RELEASED/LOCKED
sheets — `grading.services.released_entry_for`) and **UNOFFICIAL** (live `compute_student()` running
scores while a class is still in progress, always labeled "Unofficial — running grade, may still
change" with an amber chip) — gated by the admin "Show running (unofficial) scores to students"
toggle (`InstitutionSettings.show_unofficial_scores_to_students`, default on; off shows only
"Grades not yet released" for anything not yet released). **Dashboard** (`dashboard:home`) — greeting
+ program/major/year/section, stat cards (Enrolled Subjects, Official/Partial GWA with a tooltip and
an "n of m subjects released" note, Subjects Released n/m, Warnings = count of in-progress subjects
with a running grade > 3.00), mobile-first subject cards (status chip, official grade+remarks or
unofficial running grade, a progress bar for items encoded so far), an "Academic Forecast — Coming
soon" placeholder card, and the latest 5 notifications. **My Grades** (`grading:my_grades`) —
semester selector (every semester the student has class-list entries in), cards on mobile / a table
from `sm:` up, a footer with total units and Official/Partial GWA
(`approvals.services.compute_gwa`, now also returning `released_count`/`total_count` for the partial
note), and "Download Report of Grades (PDF)". **Subject detail**
(`grading:subject_detail`, pk = roster entry id) — component breakdown (official snapshot if
released, else live), an item list grouped by term (always live `AssessmentItem`/`Score` data —
informational only, and frozen in practice once a class is submitted since editing locks), a
≥5-active-students-only class average per component (`grading.services.class_average_per_component`
— aggregate only, never another student's own data), and two Chart.js charts (component % bar;
running-grade-progression line via `grading.services.running_grade_progression`, which windows the
running-grade calculation to items at or before each term). **My Progress**
(`grading:my_progress`) — a GWA-history line chart (inverted y-axis, 1.00 best) + table (semester,
units, GWA, passed/failed/INC) across every semester the student has records in, and a current-
semester horizontal bar chart of each subject's grade colored by status with a dashed 3.00 passing
line (a small inline Chart.js plugin — `afterDraw` — not an external annotation plugin). **Report of
Grades PDF** (`reports:student_grade_report_pdf`, reuses `reports/pdf.py`): RELEASED/LOCKED entries
only for the chosen semester, with a "Partial — n of m subjects released" note when incomplete;
signed by Registrar (new `InstitutionSettings.registrar_name/title` — the student's own report is
the one PDF the Dean doesn't sign) and Dean. Ownership is structural, not a checked parameter — the
view never takes a student id, only a semester id, so it can only ever render `request.user`'s own
data. **Notifications** (`dashboard:notifications`, shared with every role) gained a "Mark all as
read" button (`dashboard:notifications_mark_all_read` — a plain POST+redirect, distinct from the
topbar bell's own HTMX `mark_all_read`, which must keep returning the bell fragment). Release and
grade-correction now also notify every affected student
(`approvals.services.release_grade_sheet`/`correct_grade`), not just the instructor.

**PDF grade sheet layout (built, Phase 4 part 2 — see `templates/reports/pdf/grade_sheet.html`):**
institution header (from `InstitutionSettings`), "REPORT OF GRADES" title, subject code/title +
section(s) + schedule/room + instructor meta, a No./ID Number/Name/Final Grade/Remarks table sorted
by last name, pass/fail/INC/dropped counts, and a signature block (Submitted by: instructor,
Checked by: Program Head, Noted by: Dean) with each step's date from the sheet's timeline. Not
released yet → a diagonal "UNOFFICIAL — status" watermark. The Class Record Excel export
(`reports/excel.py`) mirrors `grading-system.xlsx`'s columns but adds an ID Number column (the real
sheet has none) for reliable re-import matching.

---

## 9. Non-Functional Requirements

- Django's password hashing (PBKDF2 default), CSRF, session regeneration on login, login lockout
  after 5 failed attempts (django-axes, by username, 15 min cooloff — Phase 2.2), 30-minute sliding
  session expiry + expire-on-browser-close (Phase 2.2), HTTPS-ready config for production
- RBAC enforced server-side on every route; IDOR tests as data ownership exists
- Audit log for: logins, user changes, score changes, grade status transitions, grade corrections,
  model training/activation (added alongside the features they audit)
- Response time < 2 s for normal pages with seeded data of 500 users; `select_related`/
  `prefetch_related`, add indexes, paginate lists
- Deployable on an institution-controlled server (on-prem or institution-managed VPS); write
  `docs/DEPLOYMENT.md` when a deployment target is chosen
- Accessible: labels on inputs, sufficient color contrast (WCAG AA verified for the brand palette),
  works at 360 px width
- All dates/times in `Asia/Manila` (set in `config/settings.py`)

---

## 10. Build Phases

Work one phase at a time. At the end of each phase: run all tests, fix failures, commit with a
clear message, and give a short summary of what was built and what's next. Do not start a phase
until the previous one passes its tests.

- **Phase 1 — Auth & RBAC + navigation shell (done):** custom user model, login/logout, forced
  password change, privacy consent, role-based sidebar + topbar layout (desktop collapsible rail,
  mobile drawer), per-role dashboards with placeholder stats, a role-gated placeholder page for
  every planned menu item, `seed_demo_users` management command, brand palette extraction.
- **Phase 2 — Academic structure (done, revised by Phase 2.1):** academic years/semesters
  (single-active-semester rule), programs, sections, subjects, class offerings, instructor
  assignment, student profiles (auto-created via signal), real dashboard counts for
  admin/instructor/student, object-level access checks (instructor/program-head roster ownership).
  Full user management is still Phase 3.
- **Phase 2.1 — Real CITCI data + scope correction (done):** dropped the "enrollment" concept
  entirely in favor of class lists (`academics.ClassRosterEntry`) built/imported for grading, with
  an .xlsx/.csv "Import class list" flow (`academics/roster_import.py`: match-by-id_number preview
  → confirm, auto-creates missing student accounts) available to admin for any class and to an
  instructor for their own. Added `academics.Major` (Program → Major → Section hierarchy) and made
  `ClassOffering.sections` a M2M (one class can serve several sections at once). Replaced the demo
  BSIT data with real CITCI BSED/TCP A.Y. 2026–2027 offerings parsed from the Registrar's .docx
  (`import_offerings_docx` → `docs/source/citci_offerings_2026_2027.json` →
  `seed_citci_academics`); the old `seed_demo_academics` command is gone.
- **Phase 2.2 — User management (done):** admin Users page (tabs/search/filters/pagination,
  replacing the read-only Students list), add/edit user modal with HTMX-cascading student
  program/major/section fields, generated one-time-reveal temporary passwords (create + reset),
  deactivate/reactivate with self- and last-admin guards, "Import Students"/"Import Instructors"
  bulk import sharing the Phase 2.1 parser, Profile page (email-only self-edit), django-axes login
  lockout + 30-minute sliding session expiry, and the reusable `SearchableSelectWidget` (now used
  for the instructor/class/student pickers). See the README "Gotcha" note on `FORM_RENDERER` if a
  future custom form widget throws `TemplateDoesNotExist`.
- **Phase 3 — Grading engine (O2, done):** grading templates + components (live weight-total
  validation), per-class frozen `ClassGradingScheme` snapshot, assessment items (Prelim/Midterm/
  Semi-Final/Final), the spreadsheet-style score-encoding grid (autosave, keyboard nav, fill-column,
  mark INC, term filter, missing-score warning), Setup/Class Record/Summary tabs with a Chart.js
  distribution chart, and `grading/services.py`'s computation functions with full unit tests
  (including the hand-verified `grading-system.xlsx` row-11 case). Deliberately **not** built this
  phase (see the task brief that drove it): grade-sheet submit/approval workflow, student-facing
  grade pages, Excel class-record import. Also fixed this phase: `seed_citci_academics` is now
  actually idempotent (`_seed_instructors` matches an existing instructor by `last_name` before
  generating a new username), and `CLAUDE.md` moved into the repo it describes. Two follow-up
  passes within this same phase: (1) whole-number scores/max-scores/weights, hiding not-yet-set-up
  components from the Class Record grid, and the spreadsheet-visual rework (zebra rows, borderless
  cells, sticky-header fix, row-actions menu); (2) **instructor-defined grading components with a
  school-locked Examination weight** — component `category`, per-component `is_locked`, the Setup
  tab's editable "Grading Components" panel (formset, live total bar, add/delete, change history),
  and `grading.SchemeComponentChangeLog` — see section 4 for the confirmed CITCI policy and section
  6 for the schema.
- **Phase 4 part 1 — Grade sheet workflow (O2, done):** the full
  draft→submitted→approved→released→locked (+returned) state machine in `approvals/services.py`
  with explicit allowed-transition checks and a `GradeSheetTransition` timeline; the frozen-at-
  submission `GradeSheetEntry` snapshot (approved/released grades never recomputed live); the
  instructor's submit pre-review modal (counts/average/missing-or-INC list, required certify
  checkbox) and server-side edit lock (`grading.views._can_edit` now also checks
  `approvals.services.is_class_editable`); Program Head approve/return/release (object-level
  checked — any head of a shared class's programs) and "release all approved"; Admin "Lock term"
  and per-entry grade correction (`GradeCorrection`, required reason); in-app notifications
  (`dashboard.Notification`, HTMX-polled bell) on every transition; `approvals.services.compute_gwa`
  (Decimal, excludes DROPPED/INC, `is_complete` flag) with no UI yet beyond what review pages show.
  Deliberately **not** built this pass (Phase 4 part 2): PDF/Excel grade-sheet exports.
- **Phase 4 part 2 — Reports & exports (O2, done):** `reports.InstitutionSettings` singleton
  (school header + Dean/Academic Head signatories, admin-editable, System → Settings) feeding every
  report — nothing hardcoded in a template. PDF engine: **xhtml2pdf, not WeasyPrint** — WeasyPrint
  needs GTK3/Pango/Cairo native libraries not available on the Windows dev machine without a manual
  system install (`import weasyprint` raised `OSError: cannot load library 'libgobject-2.0-0'`);
  xhtml2pdf is pure-Python over reportlab and needs nothing extra on Windows or Ubuntu, at the cost
  of no CSS `transform`/`rotate` support (the "UNOFFICIAL — status" watermark on a not-yet-released
  Grade Sheet PDF is a Pillow-rotated PNG embedded as a base64 `data:` URI instead,
  `reports/pdf.py:watermark_data_uri`). Grade Sheet PDF (`reports:grade_sheet_pdf`) renders the
  `GradeSheetEntry` snapshot, never live computation. Class Record Excel export
  (`reports/excel.py`) mirrors `grading-system.xlsx`'s layout plus an added ID Number column, with
  every total/grade/weighted/final cell a **real Excel formula** (not a pre-computed value) so
  faculty can recompute by hand; `?blank=1` doubles as the import template. Class Record Excel
  import (`reports/excel_import.py`) previews new/changed scores, unmatched students/items, and
  invalid values before a separate confirm step — DRAFT/RETURNED only. Reports page
  (`reports:index`) is now role-aware: instructors get per-class PDF/Excel links; Program Head
  (own programs)/Admin (all) get semester-scoped Grade Submission Status, Class Performance
  Summary, and Students with Failing/INC Grades (table + Excel export each), plus a per-program
  Program Grade Report PDF. All report queries take a pre-scoped `programs` queryset
  (`reports.views._scope_programs`) so role scoping happens once, at the call site.
- **Phase 4 part 2 fixes (done):** three issues found after the pass above shipped.
  1. **Provisional remarks bug** — `approvals.services.submit_grade_sheet` was snapshotting
     `StudentGradeResult.remarks` (grading/services.py), which deliberately shows a provisional
     `ON_TRACK`/`AT_RISK` label off the *running* grade whenever a class has a not-yet-set-up
     component (zero items) — harmless for mid-term display, but wrong once frozen into an official
     `GradeSheetEntry` snapshot, where only `PASSED`/`FAILED`/`INC`/`DROPPED` may ever appear. Fixed
     with a new `StudentGradeResult.final_remarks` property (always reads the FINAL grade, never the
     running one) that `submit_grade_sheet` now uses instead. `approvals.GradeSheetEntry` also
     gained a `CheckConstraint` (`valid_grade_sheet_entry_remarks`) restricting `remarks` to those
     four values at the DB level — `choices=` alone doesn't stop a bare `.create()`/`.save()` that
     skips `full_clean()`, which is exactly how the bug got in. A data migration
     (`approvals.0002_fix_provisional_final_remarks`, ahead of the constraint migration so existing
     bad rows get fixed before the constraint would reject them) recomputed every affected row's
     `remarks` from its already-stored `final_grade`, deliberately without writing a
     `GradeSheetTransition`/`GradeCorrection` — a system data fix, not a human grade correction.
  2. **PDF images depended on the network** — `reports/views.py`'s `_logo_context` used to call
     `request.build_absolute_uri(...)` and have xhtml2pdf fetch that URL over HTTP, which fails with
     no server running (e.g. from `manage.py shell`, or in tests, where it silently dropped the
     image and warned `Blocked by the resource policy`). Fixed with `reports/pdf.py:link_callback`,
     an xhtml2pdf `link_callback` that resolves a `STATIC_URL`/`MEDIA_URL`-prefixed `<img>` src
     straight to a filesystem path (via `django.contrib.staticfiles.finders` in DEBUG, else
     `STATIC_ROOT`/`MEDIA_ROOT`) and rejects anything that resolves outside those roots (or
     `STATICFILES_DIRS`, which `finders.find()` can also return) — path-traversal guard, not just a
     convenience. `_logo_context` now returns a plain `/static/...`/`/media/...` path instead of an
     absolute URL; `render_pdf` passes `link_callback` on every `pisa.CreatePDF()` call.
  3. **Excel import couldn't create new items** — originally a disclosed limitation ("an unmatched
     item column is reported, never auto-created"). `reports/excel_import.py` now offers each
     unmatched item column on the preview as an optional "create as new item" row — a checkbox
     (default on), a component dropdown (pre-selected by case-insensitive name match against the
     class's scheme, locked components included — only a new *component* can't be created here,
     per CITCI's school-locked-Examination-weight policy, section 4), a required term dropdown, and
     a max-score field pre-filled from the sheet's own max-score row. `validate_new_item_decisions`
     validates all checked rows before anything commits — an invalid max score (not a whole number
     ≥ 1) blocks the entire confirm, never a partial commit — and `commit_import` creates the
     `AssessmentItem` plus every valid per-student score for it inside one `transaction.atomic()`
     alongside the already-matched writes.
- **Phase 5 — Student portal (O3, done):** student dashboard (stat cards, mobile-first subject
  cards, latest notifications, an "Academic Forecast — Coming soon" placeholder), My Grades
  (semester selector, cards/table, total units + Official/Partial GWA, Report of Grades PDF), Subject
  detail (component breakdown, item list by term, ≥5-student class average, component-% bar +
  running-grade-progression line charts), My Progress (GWA history line chart + table, current-
  semester bar chart with a 3.00 passing line). OFFICIAL (released snapshot) vs UNOFFICIAL (live
  running grade, amber "Unofficial" chip) are never mixed up, gated by a new admin toggle
  (`InstitutionSettings.show_unofficial_scores_to_students`); every lookup is scoped to
  `request.user` so a mismatched id 404s rather than 403s. Added
  `grading.services.running_grade_progression`/`class_average_per_component`/`released_entry_for`/
  `subject_status_chip`/`show_unofficial_scores_to_students` (shared by the student views and the
  dashboard); `approvals.services.compute_gwa` now also returns `released_count`/`total_count` for
  the "Partial GWA: x.xx (n of m)" note; `release_grade_sheet`/`correct_grade` now notify affected
  students, not just the instructor. `reports.InstitutionSettings` gained `registrar_name`/
  `registrar_title` (signs the student's own Report of Grades PDF; the Dean doesn't) alongside the
  unofficial-scores toggle. Forecasting is still a placeholder card — Phase 6/7, not this phase.
  Demo data: `grading.management.commands.seed_student_portal_demo` (auto-run at the end of
  `seed_citci_academics`) guarantees the demo `student` account shows every state — a SUBMITTED
  subject (shown as "in progress"), a subject with a running grade > 3.00 (the Warnings stat), and a
  past semester (A.Y. 2025–2026, 2nd Sem) with released+locked grades so GWA history has 2+ points —
  on top of whatever `seed_grading_demo` already produced (RELEASED, in-progress-with-partial-
  scores, no-scores-yet all come free from its existing classes).
- **Phase 6 — ML service (O4):** synthetic generator, training, evaluation with bootstrap CIs,
  predict endpoint with contributions, pytest.
- **Phase 7 — Integration (O3, O4):** Django ↔ ML client, queued/scheduled predictions, forecast
  UIs for all roles, interventions, early-warning notifications, historical data import with
  masking, model performance page.
- **Phase 8 — Testing & evaluation (O5):**
  - Feature/unit tests for all modules; target ≥ 80% coverage of services and access-control logic
  - Seeder: 1 admin, 2 program heads, 15 instructors, 450 students, current + 2 past terms with
    realistic scores
  - Simple performance check script (timed requests on key pages with seeded data), results in
    `docs/PERFORMANCE.md`
  - `docs/UAT_QUESTIONNAIRE.md`: ISO/IEC 25010 Likert (1–5) questionnaire covering Functional
    Suitability, Performance Efficiency, Usability, Reliability, Security, Maintainability,
    Compatibility, Portability — separate versions for instructors and students
  - `tools/uat_analysis.py`: reads a CSV of responses, outputs per-item and per-characteristic
    weighted mean, SD, percentage distribution, interpretation (4.21–5.00 Excellent, 3.41–4.20 Very
    Good, 2.61–3.40 Good, 1.81–2.60 Fair, 1.00–1.80 Poor), and one-way ANOVA between instructor and
    student groups
  - Final `docs/` set: ERD, architecture diagram, data flow diagram, user manual per role,
    deployment guide

---

## 11. Rules for You (Claude Code)

- Follow Django conventions: thin views, business logic in app-level services once real logic
  exists (e.g. `GradeComputationService`, `GwaService`, `ForecastClient`), Django Forms for
  validation.
- Never hardcode grading weights or the transmutation scale — they're DB-backed config once that
  phase is built.
- Never send names or real student numbers to the ML service.
- No features outside the current phase's scope (no LMS, chat, file submissions) unless asked.
- Keep code readable for undergraduate students: clear names, short comments only on non-obvious
  logic.
- The sidebar menu is defined once in `accounts/menu.py`; icons are inline SVG via
  `accounts/templatetags/sidebar_icons.py` (no icon CDN, per the original design constraint).
- `INSTALLED_APPS` order is `..., academics, grading, approvals, forecasting, reports, dashboard`.
  `approvals` imports `grading.services`/`grading.models` at module level (grading loads first,
  that's fine); the reverse (`grading` needing an `approvals` status check, e.g.
  `grading.views._can_edit` consulting `approvals.services.is_class_editable`) can only be a
  function-local import, or Django's app loading order breaks. Same pattern for
  `accounts.context_processors` reading `approvals.models` for the sidebar badge count.
- For a new admin list+CRUD page, extend `core.crud.EntityListView`/`EntityFormView`/
  `EntityDeleteView` (see any class in `academics/views.py` for the pattern) rather than writing
  list/create/update/delete from scratch — it's already wired for search, filters, pagination, the
  shared modal, and `PROTECT`-vs-"Deactivate instead" handling.
- `static/js/htmx-csrf.js` attaches the CSRF header to every HTMX request already — don't add
  `{% csrf_token %}` workarounds to bare `hx-post`/`hx-delete` buttons, they don't need one.
- When a server response needs to both close the shared modal and update page content outside it in
  one round trip, use `response["HX-Trigger"] = "modal-success"` on a normal (200) render — htmx
  processes `HX-Trigger` on any status, not just 204 — and give the two elements matching
  `hx-target`s (don't render the same `id="..."` fragment into both the modal and the page, or
  you'll get two elements sharing one id; see `class_list_import_confirm` in `academics/views.py`
  for the pattern, and use `HX-Retarget`/`HX-Reswap` headers if an error response needs to land
  back in the modal instead).
- Re-deriving `docs/source/citci_offerings_2026_2027.json` from a new Registrar .docx: run
  `python manage.py import_offerings_docx docs/source/<file>.docx`, review
  `docs/source/DATA_ISSUES.md` (flagged instructor-name pairs — confirm with CITCI, never
  auto-merge), then `python manage.py seed_citci_academics`. Both commands only understand the
  specific table shape of the 2026–2027 sheet (see the docstring in `import_offerings_docx.py`) —
  a materially different sheet layout needs parser changes first. `seed_citci_academics` is
  idempotent (`_seed_instructors` matches an existing instructor by `last_name` before generating a
  new username, so re-running it is safe) and also seeds demo grading data at the end
  (`seed_grading_demo` — default template + assessment items/scores for the first two classes it
  finds with an instructor and a roster).
- Tests that log a user in must use `self.client.force_login(user)`, not
  `self.client.login(username=..., password=...)` — django-axes' `AxesStandaloneBackend` needs a
  real `request` object passed to `authenticate()`, which Django's test `Client.login()` doesn't
  provide, so it raises `AxesBackendRequestParameterRequired`. `force_login()` sets the session
  directly and bypasses the backend chain entirely (this is django-axes' own documented fix for
  test suites).
- If a requirement conflicts with another, or with this file, stop and ask before building.
