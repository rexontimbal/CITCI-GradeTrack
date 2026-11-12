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
>
> **2026-11-04:** **Phase 6 (Forecasting — ML core) is done, with one correction to the original
> spec: no separate FastAPI "ml-service."** The model lives in-process inside Django
> (`forecasting/ml/`) — see the rewritten Tech Stack and section 7, and the Phase 6 bullet under
> "Build Phases." Checkpoints (PRELIM/MIDTERM) replace the old spec's "midterm grade" concept, and
> the at-risk label is `FINAL grade > 3.00` (not `== 5.00`) or INC/DROPPED. Deliberately not built
> this phase (Phase 7): the at-risk list UI, the student's forecast card, early-warning
> notifications.
>
> **2026-11-04 (later the same day):** **Phase 7 (Forecasting part 2 — predictions in the UI,
> interventions, early warning) is done.** Section 7 below is rewritten to describe what's actually
> built: the checkpoint-determination rule, the `risk_level` 3-tier display helper (never stored —
> it's mathematically derived from the already-stored probability/threshold), the
> recompute-after-save trigger (`forecasting.services.recompute_and_notify`, measured well under the
> spec's 150ms budget — see the Phase 7 bullet under "Build Phases" for the numbers), At-Risk
> Students pages for instructor and program head, the forecast drawer with a Chart.js contributions
> chart, the new `forecasting.Intervention` model, the student-facing (never-numeric)
> `student_forecast_card`, `InstitutionSettings.show_forecasts_to_students`, and episode-based
> early-warning notification de-dup. See the Phase 7 bullet under "Build Phases" for the full list
> and the judgment calls made along the way.
>
> **2026-11-04 (later still):** **Phase 8 part A (Production hardening, polish, deployment setup)
> is done — part B (the ISO/IEC 25010 UAT questionnaire + analysis script) is not built yet, by
> design (a separate, later task).** Settings are now split into `config/settings/{base,dev,prod}.py`
> (`DJANGO_SETTINGS_MODULE` selects one — dev.py by default); prod.py refuses to start without a
> real `SECRET_KEY`/`ALLOWED_HOSTS` and gates HSTS/secure-cookies behind one `ENABLE_HTTPS` flag
> (off by default — CITCI may start on plain LAN HTTP). New: an admin Audit Log page combining
> account changes + every existing domain change-log table, standalone 404/500/CSRF-failure pages
> that don't depend on the database, `/healthz`, `backup_db`/`restore_db` management commands,
> rotating file logging in prod, a global toast system + htmx loading-state CSS, a `setup_production`
> first-run command, and every demo seeder now refuses to run under the production settings module
> without `--force-demo`. Deployment docs/configs for both an Ubuntu+Gunicorn+Nginx target and a
> Windows+Waitress+NSSM target live under `deploy/` and `docs/DEPLOYMENT.md`. See the Phase 8 part A
> bullet under "Build Phases" for the full list, the measured query-count improvements, and the
> judgment calls made along the way.
>
> **2026-11-05:** **Teaching load assignment (built), out of phase order — a standalone follow-up
> task, not part of Phase 8 part B.** Confirmed CITCI practice: Admin assigns each program's
> Program Head (unchanged); the Program Head then assigns which instructor teaches each class in
> their program — not Admin, except as a logged "admin override." See the new section 3a for the
> full rule set (unassigned classes, the Teaching Loads page, notifications, audit logging, the
> submitted-sheet lock) and `academics.TeachingAssignmentLog`/`academics/services.py` for what was
> actually built. Phase 8 part B (coverage/perf/UAT/docs) remains the next task after this one.
>
> **2026-11-05 (later the same day):** **Debug-toolbar opt-in + dashboard/student-portal
> query-count pass (done), ahead of the rest of Phase 8 part B.** `django-debug-toolbar` is now
> gated behind `DEBUG_TOOLBAR=1` (was always-on in dev when installed) since its panels were
> skewing the very query-count/latency numbers this pass measured. Re-measured after the teaching-
> load changes above (which touched the Program Head dashboard): Program Head dashboard 101→13
> queries, student dashboard 111→32, My Grades 53→23, My Progress 61→31, subject detail ~29→24-25
> — see the new "Query-count pass, Phase 8 part B" bullet under section 9 for the specific fixes
> (new batch primitives in `forecasting.services`/`grading.services`/`approvals.services`) and
> `dashboard.tests.DashboardQueryCountTests` for the regression guard. The rest of Phase 8 part B
> (coverage ≥80%, At-Risk query reduction, accessibility audit, load/perf tooling, UAT
> questionnaires, diagrams, manuals, `CHANGES_FROM_PROPOSAL.md`, demo script) is still the next task.
>
> **2026-11-07: Phase 8 part B is done — the project is complete.** At-Risk query reduction: 118 →
> 21 queries on a 6-class fixture (`forecasting.services.get_display_forecasts_for_classes`, see
> `forecasting.tests.AtRiskQueryCountTests`). Coverage: 293 tests, 76.1% overall, ≥80% on every
> service module and every access-control module (the spec's actual target — see
> `docs/TEST_REPORT.md`). Accessibility: an axe-core audit (`tools/accessibility_audit.py`) found
> and fixed a project-wide color-contrast issue plus several unlabeled-control issues — 0
> violations on re-run across 35 page/modal visits (`docs/ACCESSIBILITY.md` — note its "the earlier
> audit was invalid" postscript: the first pass accidentally audited the onboarding gate page
> instead of real content, caught and corrected the same session). Load/perf: `seed_load_test` +
> `tools/perf_check.py` — every page under the 2s requirement including a worst-case 450-student
> class (`docs/PERFORMANCE.md`). UAT: three ISO/IEC 25010:2011 questionnaire versions (Students /
> Staff / IT Experts) plus `tools/uat_analysis.py` (weighted means, interpretation bands, one-way
> ANOVA — `docs/UAT_QUESTIONNAIRE.md`, `docs/uat/`). Docs: `docs/ERD.md`/`DATA_DICTIONARY.md`
> generated straight from the models (`tools/generate_erd.py`), architecture/DFD/use-case diagrams
> (`docs/diagrams/`), a user manual per role with real screenshots
> (`tools/generate_user_manuals.py`, `docs/manuals/`), `docs/CHANGES_FROM_PROPOSAL.md` (every
> deviation from the approved proposal, cited section-by-section — including the fourth role,
> Program Head, and the grade-sheet/teaching-load workflows the proposal never described), and
> `docs/DEFENSE_DEMO_SCRIPT.md`. See `README.md`'s "Documentation" section for the full index and
> how to regenerate each generated doc. No further phases are planned — future work is whatever the
> defense panel or continued CITCI use surfaces.
>
> **2026-11-07 (post-completion enhancements, 6 items from a system-flow review):** The project
> above was complete; this follow-up work (not a numbered phase) addressed 6 gaps the review
> surfaced, each its own commit:
> 1. **Admin: Import Class Offerings + Copy classes from previous semester** — a new
>    `academics/offerings_import.py` (xlsx or the existing Registrar `.docx` format through the
>    same preview, reusing `import_offerings_docx.py`'s parse/normalize helpers) with a preview
>    step (new subjects / new classes / shared classes / unknown instructors — never auto-created
>    or merged) before confirming; "Copy classes from previous semester" on the Classes page always
>    leaves the copy's instructor Unassigned.
> 2. **Admin: New Academic Year wizard** (`academics/ay_wizard.py`) — 4 plain-page steps (new A.Y.
>    + semesters → recreate the section structure → review/exclude student promotions → confirm,
>    one transaction) reachable from Academic Years & Semesters. Added `StudentProfile.status`
>    (ACTIVE/COMPLETED) — 4th-years and no-year-level students (TCP) are marked Completed rather
>    than deleted; the account stays loginable, it just drops out of "currently enrolled"
>    counts/pickers. Writes one summarizing `accounts.AuditLog` row per run.
> 3. **INC completion workflow** — a new `approvals.IncCompletion` model (PENDING/APPROVED/
>    REJECTED): the instructor files "Complete INC" on a RELEASED/LOCKED+INC entry; the owning
>    Program Head approves (reusing `approvals.services.correct_grade` verbatim — same
>    `GradeCorrection`/timeline/notifications as an admin correction) or rejects (remarks required)
>    from a new "INC Completions" tab on Grade Approvals. "Completed INC" is never a stored flag —
>    it's derived at display time from an approved `IncCompletion` row, the same philosophy as
>    `risk_level`. A configurable window (`InstitutionSettings.inc_completion_window_days`, default
>    365) blocks filing past it ("INC lapsed — contact Registrar") with no automatic grade change.
> 4. **Grade submission deadline** — `academics.Semester.submission_deadline`; submitting after it
>    still succeeds but snapshots `approvals.GradeSheet.is_late=True` at submission time (never
>    retroactively recomputed); Grade Approvals/Grade Sheets/the Submission Status report all gained
>    a late filter + counts. New standalone `send_reminders` management command (deliberately
>    separate from forecasting's `run_forecasts`) notifies instructors starting 3 days before the
>    deadline, de-duplicated via `GradeSheet.reminder_sent_at`.
> 5. **Instructor to-do dashboard** — replaced the instructor dashboard's count-only placeholders
>    with a real to-do list (missing scores, returned sheets, not-yet-submitted sheets with a
>    countdown, at-risk students with no intervention logged, pending INC completions), backed by
>    new batched service helpers following the codebase's established "resolve for every class in a
>    handful of queries" shape — including a new `forecasting.services.at_risk_without_intervention`
>    (no prior function filtered by absence of an `Intervention`).
> 6. **Django Admin hardened** — removed from the sidebar for every role; `config/admin.py`'s
>    `SuperuserOnlyAdminSite` (every app's `admin.py` now registers against it, not the default
>    site) enforces superuser-only access server-side; `DJANGO_ADMIN_URL` moves it off the default
>    path in production. Day-to-day work must use the app's own pages — see `docs/DEPLOYMENT.md`.
>
> All 6 are additive — no existing behavior changed except Django Admin's access being made
> explicit (item 6) and `StudentProfile.status`/`is_late`/`is_overdue` fields now excluding
> completed students and flagging late sheets where they weren't tracked before. See section 3
> (roles), section 5 (INC completion), section 6 (new fields/models), and section 8 (new screens)
> below, now updated to describe this state; `docs/CHANGES_FROM_PROPOSAL.md` records these as
> post-proposal enhancements, not deviations from the original proposal.
>
> **2026-11-09 (Program Head scope redesign, built):** Confirmed CITCI practice:
> **day-to-day academic setup belongs to each program's Program Head, scoped to their own
> program/major — Admin works at institution level and keeps a full, audited override.** A
> Program Head can now be assigned at PROGRAM level (`Program.program_head`, unchanged, covers
> every major with no head of its own) or at MAJOR level (new `Major.program_head`, takes
> precedence for that one major). One helper, `academics.scoping.scope_for(user)`, is the single
> source of truth every object-level "does this head own X" check now uses — it replaced ~10
> independently-duplicated `sections__program__program_head=user`-style expressions across
> academics/approvals/dashboard/forecasting/grading/reports/accounts. Program Heads gained their
> own scoped pages — Sections, Subjects (a shared catalog; editing is scope-restricted, a
> shared/general subject with no program stays admin-only), Classes (including "Join existing
> class" for a shared class across programs, and "Leave," which auto-deactivates a class once its
> last section is removed), Class Lists, and Import Class Offerings (out-of-scope rows rejected in
> preview with a reason) — all under a new "My Program" sidebar group, alongside the existing
> Teaching Loads. Admin's sidebar splits "Academic Setup" (now just Academic Years & Semesters,
> Programs, Majors) from a new "Override" group holding the same five entities, banner-marked and
> logged to a new shared `academics.AcademicSetupChangeLog` with `is_admin_override=True` — the
> same audit shape already used for teaching-load admin overrides, now combined into the Audit
> Log page as a new `academic_setup` source. The Program Head dashboard's old placeholder stat
> cards were replaced with a linked setup checklist (sections/classes created, classes without an
> instructor, empty class lists, sheets submitted) and the head's scope shown under the page
> title; every Program Head page shows a clear empty state if Admin hasn't set an active semester
> yet. See section 3 (roles table) and the new section 3b for the full scope rules, section 8 for
> the new/moved screens, and the "Program Head scope redesign" bullet under "Build Phases."
>
> **2026-11-11 (Curriculum mapping + prospectus Subjects page, built):** `academics.Subject` no
> longer carries `program`/`major`/`year_level`/`term` directly — a new `academics.CurriculumEntry`
> model places a subject into one program/major's prospectus at a given year level and term, and
> the same subject code can now sit in several curricula at once (e.g. a Gen Ed subject shared
> across majors), which the old one-slot-per-subject design couldn't represent. Existing placement
> data was copied into `CurriculumEntry` by a data migration before the old fields were dropped
> (three migrations: add the model, copy the data, remove the fields — in that order, so the data
> migration could still read the columns being removed). `academics.scoping` gained
> `curriculum_entries_in_scope`/a rewritten `subjects_editable_by` (a subject is editable by a
> Program Head only if **every** one of its `CurriculumEntry` rows is in their own scope — a count
> comparison, not a negated scope query, after a real Django ORM bug surfaced: negating a `Q()`
> built from multiple conditions on a to-many relation lets *different* rows of that relation each
> satisfy one condition, instead of requiring one row to satisfy all of them). Both the Program
> Head and Admin Subjects pages were rebuilt as a shared prospectus-style view
> (`academics.views.subjects_home`) — a segmented major-filter (Program Head, scoped) or a
> program/major selector (Admin, everything) over cards per year level, each with 1st/2nd Sem
> sub-tables, a "Shared" badge on a subject used by another program/major, and a two-path "Add
> Subject" modal (use an existing subject from the catalog, or create a new one) — admin's page
> keeps the Override banner and logs every change as an admin override, same pattern as Sections/
> Classes. "Remove from curriculum" deletes only the `CurriculumEntry`, never the `Subject`, and is
> blocked while an active-semester class still uses that placement. The Class-creation subject
> picker (`academics.forms._grouped_subject_choices`) groups "From the curriculum" subjects ahead
> of "All subjects" once a section is chosen, live — an htmx re-render fires on the sections field
> the same way `_user_form_modal.html` already re-renders on a role change (same-day follow-up,
> see below; the first pass only computed this from an already-saved class's sections on edit). A
> new `load_citci_curriculum`
> management command (dev-only, `python-docx`) loads CITCI's real curriculum from the Registrar's
> `docs/source/all_subject_per_major.docx` — it turned out to be the exact same table shape
> `import_offerings_docx.py` already parses, so it reuses `parse_docx` directly and just ignores
> the instructor/room/schedule columns it doesn't need. Same-code rows with conflicting titles or
> units across tables keep the BSED-table's value and are logged to `DATA_ISSUES.md`; near-
> duplicate codes (e.g. "PEd 205" vs "PEd 205 Elec") are flagged, never auto-merged, matching the
> project's existing "never auto-merge, confirm with CITCI" policy for suspicious instructor-name
> pairs. See the "Curriculum mapping" bullet under "Build Phases" for the exact findings from the
> real file (duplicate-code list, near-duplicates, a unit-count oddity) and the counts from running
> it against the dev database.
>
> **2026-11-11 (same-day follow-up — Subjects filters, live curriculum suggestions, loader name
> matching):** the Program Head Subjects pills are now one per **major** ("English", "Social
> Studies" — display names, not codes), never a program-level pill once the program actually has
> majors (that scope tuple only ever covers majors with no head of their own, which can never be
> the SAME program-level pill shown alongside its own majors — showing it was always an empty
> view). A program with no majors at all (e.g. TCP) still gets one pill, labeled with the
> program's code. Two more segmented filters sit alongside the pills: **Semester** (All / 1st Sem /
> 2nd Sem / Summer — Summer only shown if any entry actually uses it; defaults to the active
> semester's term, not "All") and **Year Level** (All / 1st–4th — hidden entirely for a TCP-style
> selection with no year-level entries). All three filters (`program`/`major` via the pill,
> `term`, `year_level`) plus the search box stay in the URL, so a filtered view is bookmarkable/
> shareable; a subject-count + total-units line reflects whatever's currently filtered. Admin's
> Subjects page gained the same two segmented filters alongside its existing program/major
> selector (also switched to display names).
>
> The Class-creation subject-picker suggestion (see above) now re-renders live: changing the
> `sections` field fires an htmx `hx-get` back to the same create/edit URL
> (`academics.views._wire_live_subject_regroup`), re-rendering the whole modal with the `subject`
> field's curriculum-matched grouping recomputed from whatever sections are now selected — wired
> for both the Program Head and Admin Class forms, closing the gap the first pass had disclosed.
>
> `load_citci_curriculum`'s program/major resolution now matches by **code OR name**, case-
> insensitive (`academics.management.commands.load_citci_curriculum._resolve_program_major`) — a
> hand-created Program/Major doesn't have to use the docx's exact short code to be found.
>
> **2026-11-11 (same-day follow-up — Add/Edit Subject redesign):** the Add-to-curriculum modal
> dropped its "use existing / create new" tab switch for **one field-driven form**
> (`academics.forms.SubjectAddForm`): the `code` field doubles as a live lookup (an htmx `hx-get`
> fires on every keystroke) — typing a code that matches the catalog, case/spacing-insensitive
> (`academics.services.normalize_code`/`find_subject_by_normalized_code`), locks `title`/`units`
> read-only with "Existing subject — it will be added…"; a non-matching code leaves them editable
> with "New subject — it will be created and added." Submitting never creates a duplicate Subject
> row for a differently-cased/spaced version of an existing code — it silently reuses the match.
> The code field's dropdown (shown while typing, hidden once an exact match locks the form) orders
> results — subjects already in this exact program/major first, then ones shared across more than
> one program, then the rest — and tags/disables a result already placed in this program/major
> with where ("Already in 1st Year · 1st Semester").
>
> **`CurriculumEntry`'s uniqueness tightened** (migration `0011_subject_once_per_program_major`,
> with a defensive dedup pass first): a subject now sits **once per program/major, period** — not
> once per year-level/term slot as before. Two conditional `UniqueConstraint`s, not one plain
> `(program, major, subject)` constraint: SQL never treats two NULLs as equal in a unique index, so
> a plain constraint would silently fail to catch a TCP-style duplicate (`major` is always NULL
> there) — `condition=Q(major__isnull=False)` / `condition=Q(major__isnull=True)` handles both
> cases. `academics.services.subject_duplicate_error` gives the two user-facing messages (exact
> slot already used / already elsewhere in this program-major, "remove it there first") that this
> rule implies — there's no third case, since a subject can only ever be in one slot per program/
> major now.
>
> **Edit Subject gained code editing** (title/units already were) for both Admin and a scope-
> restricted Program Head (`academics.views.subject_edit`) — normalized-uniqueness-checked against
> the whole catalog, and blocked once the subject is used in a RELEASED/LOCKED grade sheet
> (`academics.services.subject_used_in_released_grades`) by disabling the field server-side (a
> posted change to a disabled field is simply ignored by Django's ModelForm, not an error — title/
> units still save normally). Admin gets an explicit escape hatch, **"Correct code"**
> (`academics.views.subject_correct_code`, a separate action requiring a reason), logged as an
> admin override with the old/new code and reason in `AcademicSetupChangeLog.details`
> (`Action.CODE_CORRECTED`). A genuine Django footgun was caught and fixed while building this:
> comparing `subject.code` against the posted value *after* calling `form.is_valid()` silently
> compared the ALREADY-mutated value against itself, since `ModelForm.is_valid()`/`_post_clean()`
> writes cleaned field values onto `form.instance` in place — the same object as `subject` here,
> not a copy — so the "did the code actually change" check now captures `subject.code` *before*
> binding the form to it.
>
> **2026-11-12 (Class join codes with QR + instructor approval, built):** a fourth path onto a
> class's roster, alongside the existing Program-Head section auto-fill, instructor manual-add, and
> import — a student can now self-join with a 7-character code (`academics.services.
> generate_join_code`, `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` — no `0/O/1/I`) or by scanning a QR code
> that encodes `/join/<code>/`, generated server-side as pure-vector SVG via the `qrcode` package's
> `SvgPathImage` factory (no PIL, no external service, no network call). **It is never an automatic
> roster add** — every request is a `academics.ClassJoinRequest` row (PENDING/APPROVED/REJECTED/
> CANCELLED) the owning instructor still approves or rejects; approval creates the
> `ClassRosterEntry` with the new `source=JOIN_CODE` (alongside existing SECTION/MANUAL/IMPORT
> values). `ClassOffering` gained `join_code` (unique, nullable until first viewed —
> `services.ensure_join_code` lazily assigns one) and `join_enabled` (instructor's own on/off
> switch, independent of resetting the code). The request row itself is the full audit trail
> (status + `decided_by`/`decided_at`/`reject_reason`, never deleted) — no separate change-log
> table needed, same philosophy as not duplicating state that's already fully represented elsewhere.
>
> Eligibility (`services.check_join_eligibility`) is checked at BOTH request time and approval time
> (a grade sheet can be submitted in the gap between the two): join disabled, semester not the
> active one, grade sheet already submitted-or-later (`approvals.services.is_class_editable`),
> already on the roster, or an open request already pending — each its own clear message, never a
> generic failure. Wrong-code attempts (not eligibility failures on an otherwise-valid code) are
> rate-limited via Django's cache framework (`services.check_join_rate_limit`/`record_join_attempt`
> — 10 per 15 minutes per user, LocMemCache is fine at this scale, same "no Celery/Redis" philosophy
> as everywhere else in this codebase) — a legitimate repeat visit to a valid code's confirmation
> page never counts against the limit, only genuine guesses do.
>
> **Instructor side**: the Class List page (`academics:class_roster`, "View Roster" renamed to
> "Class List" with a red pending-count badge on My Classes) gained an "Invite Students" card (code
> + copy button, inline QR `<img>` served by `academics:class_join_qr`, download/print, a join
> on/off toggle, "Reset code" with a confirm modal) and a "Pending Requests" list (name/ID/program-
> section/requested-time + a "Matches section ✓"/"Different section ⚠" badge off
> `services.join_request_section_match` — queries `StudentProfile` directly rather than the
> `student.student_profile` reverse accessor, which can cache stale on an in-memory `User` instance
> created before Admin assigns its section) — row Approve/Reject (`hx-prompt` for an optional reject
> reason) plus the project's standard checkbox + sticky-bottom-bar bulk pattern
> (`services.bulk_decide_join_requests`, skip-with-reason per row, same shape as
> `withdraw_offerings_bulk`). Program Head gets a read-only "+N pending" badge on the existing
> Classes page (`academics:program_head_classes`) — no approve/reject access, just visibility.
>
> **Student side**: a new "My Classes" page (`academics:student_my_classes`, new sidebar item — did
> not exist before this phase) lists joined classes plus any PENDING ("Pending approval", with
> Cancel) or REJECTED ("Request declined" + reason) requests; "Join class" opens a code-entry modal
> that redirects (`HX-Redirect`) to `/join/<code>/` — the same page a scanned QR lands on — so both
> paths share one confirmation screen (subject/section/instructor/semester, shown before anything is
> submitted) and one "Request sent" screen after. `/join/<code>/` is `@role_required(STUDENT)`,
> which already sends an unauthenticated visitor to login with `?next=` back to itself — no custom
> auth-redirect code needed. A student can never leave an approved class themselves (only the
> instructor can remove or mark Dropped) — joining is one-directional from the student's side once
> approved.
>
> Notifications (`dashboard.services.notify`, existing pattern): the instructor gets one per new
> request, its message naming the current pending count (a lightweight "grouped" signal without
> building real notification-batching machinery); the student gets one on approve or reject.
> `requirements.txt` gained `qrcode==8.2`. See `academics/tests.py`'s `ClassJoinCode*`/`JoinRequest*`/
> `ClassJoinViewTests` classes for the full coverage (join → pending → approve → in roster and
> Class Record; reject with reason; duplicate pending request; already-on-roster; invalid/disabled/
> reset code; inactive semester; locked grade sheet blocking both join and a since-submitted
> approval; rate limiting; section-match badge; bulk skip-already-decided; and permissions — a
> student can't decide requests, an unrelated instructor can't even view the class's roster page).
>
> **2026-11-13 (Students: section membership per semester; fix Edit User prefill, built):**
> `academics.StudentProfile.year_level`/`.section` are gone — a student's year level and section
> change every semester (promotion, moving sections, sitting a term with none at all while joining
> by code), so they never belonged on the permanent account. A new `academics.SectionMembership`
> (`student`, `section`, `semester`, unique per student per semester — year level is derived from
> `section.year_level`, never stored a second time) replaces them everywhere: the Program Head's
> section auto-fill (`services.fill_roster_from_section`), the "Matches section" join-request badge
> (`services.join_request_section_match`), the AY wizard's promotion step (`ay_wizard.step3/
> step4`), the class-list/roster importers, the bulk "Import Students" flow, and every report/
> template that used to read `profile.section`/`.year_level` directly (Users list, Class List,
> student dashboard/profile, the Failing/INC Excel report). A three-migration data move (`0017` add
> the model, `0018` copy existing `StudentProfile.section`/`.year_level` into a `SectionMembership`
> for whichever semester actually matches the section's academic year, `0019` drop the old fields)
> — same "add, copy, remove" shape already established for `CurriculumEntry`.
>
> **ID Number is now the student account's one required identifier** (`services.
> check_join_eligibility` blocks joining by code without one, with a clear message) — Year Level/
> Section are gone from the Add/Edit User form entirely (moved to the Program Head's Sections page,
> see below) and from the bulk "Import Students" template's handling: an old import file that still
> has a Year Level column keeps working (resolved to a section, written as a `SectionMembership` for
> the active semester at commit time) but a blank value is now a perfectly valid row instead of a
> forced "no matching section" rejection — a student with no section is normal (TCP-style, an
> irregular, or one who only joins classes by code).
>
> **Section Students** (`academics:section_students`, Program Head's Sections page) is now scoped to
> one semester at a time (a `?semester=` selector defaulting to the active one) and gained: Add/
> Remove students directly (not just "Move"), **"Copy from previous semester"** (same section, same
> academic year, 1st Sem → 2nd Sem — never overwrites a student already placed for the target
> semester), and **Promote…** (`academics:section_promote`) — a lighter, Program-Head-reachable
> counterpart to the AY wizard's system-wide promotion, for moving one section (e.g. BSED-ENG 1-A)
> into a target section in a newer academic year one at a time; a preview step pre-unchecks any
> student who already has a membership for the target semester (an irregular placed elsewhere),
> never silently moving them. The Users list's "Program/Section/Scope" column now shows Program–
> Major plus the *current* semester's section if any (e.g. "BSED-ENG · 1-A (1st Sem 2027–2028)"), and
> a student with no ID number gets a "No ID number" warning badge instead of a blank cell.
>
> **The Edit User modal prefill bug report turned out not to reproduce** — a live Playwright check
> against the actual running server confirmed `id_number`/`program`/`major`/`section` all prefilled
> correctly from the database before this change (the form's `__init__`/`is_bound` logic was already
> correct); the most likely explanation is the same stale-browser-tab class of issue documented
> earlier this session, not a code bug. A regression test (`UserFormPrefillTests` — open the edit
> form, submit unchanged, assert nothing on the account/profile changed) is now in place as a
> standing guard regardless. The year_level/section cascade removed from `UserForm`/`accounts.views.
> user_form` along the way (dead code once those fields left the form) incidentally simplifies a
> GET-cascade code path that was a plausible place for exactly this class of bug to hide, if it
> existed anywhere.

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
- Queue: **none — decided against, Phase 6.** Predictions are cheap at this data scale; no
  Celery/Redis/django-rq. Recomputed synchronously after score saves (Phase 7) plus a `run_forecasts`
  management command schedulable via Windows Task Scheduler/cron.
- Local dev: PostgreSQL running locally; see `README.md` for Windows setup
- Settings (Phase 8 part A): split into `config/settings/{base,dev,prod}.py` — `DJANGO_SETTINGS_MODULE`
  selects one (`manage.py`/dev default to `config.settings.dev`; `wsgi.py`/`asgi.py` default to
  `config.settings.prod`). `prod.py` refuses to start without a real `SECRET_KEY`/`ALLOWED_HOSTS`,
  gates HSTS/secure-cookies behind one `ENABLE_HTTPS` env flag, and adds rotating file logging. See
  section 9 and `docs/DEPLOYMENT.md`.
- Production WSGI/deployment (Phase 8 part A): Gunicorn (Ubuntu + systemd + Nginx, the primary
  target) or Waitress (Windows + NSSM, the alternative), WhiteNoise (Windows target only — Nginx
  serves static/ directly on the primary target). `requirements-prod.txt` adds these on top of
  `requirements.txt`. See `deploy/` and `docs/DEPLOYMENT.md`.

**Forecasting (Phase 6, built in-process — not a separate service)**
- scikit-learn, pandas, numpy, joblib — all **in the `forecasting` app**, same process as the rest
  of Django. **No FastAPI, no `/ml-service`, no network hop, no API key.** The original spec's
  "forecasting service" design (separate FastAPI process called over HTTP) was superseded before any
  of it was built — at this data scale a same-process `forecasting/ml/` package (`features.py`,
  `synthetic.py`, `train.py`, `evaluate.py`, `predict.py`) does the same job as plain Python
  functions, with no deployment/availability story to build (Django can't "lose connectivity" to
  code running in its own process). See section 7 for what actually got built.

## Brand palette

Extracted from `static/img/citci-logo.png` via a Pillow dominant-color scan:
- `brand-primary` (navy, measured `#283082`) — sidebar background, headers, dark surfaces.
- `brand-accent` (gold, measured `#f0dc1e`) — active menu state, primary buttons, focus rings.
- Full 50–950 Tailwind shade scales for both live as `@theme` tokens in
  `.django_tailwind_cli/source.css` — the single source of truth for the palette. Change the two
  base hexes there (and regenerate the scale) if the logo ever changes.
- White text on `brand-primary-600`/`-700` and dark text on `brand-accent-600` both clear WCAG AA
  (11–15:1 measured) — no adjustment was needed.

## Layout & scroll conventions (page-level horizontal scroll fix)

A wide table (the Class Record grid, Subjects, Classes, Teaching Loads, any admin list) must never
force the whole PAGE to scroll horizontally — only the table's own container may. The document
(`<body>`) stays `overflow-x: hidden` as a safety net, but the real fix is structural: `base.html`'s
app shell is `<div class="min-h-full md:flex">` (sidebar + main column) and the main column
**must** carry `min-w-0` alongside `flex-1` (`<div class="flex min-h-screen min-w-0 flex-1
flex-col">`) — without it, a flex child's default `min-width: auto` lets it grow to fit its widest
descendant (a wide table), which pushes the whole shell wider than the viewport and drags the
sidebar along with it when the user scrolls. The sidebar itself is already `sticky top-0 shrink-0`
and needs no change. Every wide-table wrapper still needs its own `overflow-x-auto` (or
`overflow-auto` for a grid that also scrolls vertically) + `max-width: 100%` so IT absorbs the
overflow instead of the page.

**`.gold-scroll`** (`.django_tailwind_cli/source.css`) is the ONE shared thin-scrollbar class for
every scroll container in the system — the sidebar `<nav>`, the Class Record grid, and every
wide-table wrapper (`overflow-x-auto rounded-2xl border border-gray-200 bg-white gold-scroll` is
the standard combination). 6px thin, brand-accent gold thumb (`rgba(245, 231, 102, …)`, brighter on
hover), transparent track, no arrow buttons, `scrollbar-width: thin` for Firefox. Never write a new
one-off scrollbar rule — add `gold-scroll` to the container instead.

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
| **admin** (Registrar/System Admin) | Manage users (CRUD, bulk import, activate/deactivate, reset password); manage academic years/semesters, programs, majors; assign Program Heads (Chairpersons) per program or per major; **override** Sections/Subjects/Classes/Class Lists/Import Class Offerings/Teaching Loads for any program (audited as an admin override — see section 3b) — these are normally the Program Head's own job; configure grading templates; lock/unlock terms; import historical data; train/activate ML model versions and view model metrics; view audit logs; system-wide reports |
| **program_head** | **Day-to-day academic setup for their own program/major scope — Sections, Subjects, Classes (including joining/leaving a shared class across programs), Class Lists, Import Class Offerings — confirmed CITCI practice** (see section 3b); **assign/change which instructor teaches each class in their program (teaching loads)** (see section 3a); view department dashboard (setup checklist, at-risk counts per class/subject); view at-risk list with contributing factors; approve or return submitted grade sheets; release approved grades; export reports |
| **instructor** | View assigned classes only; adjust grading component weights for own class (within template rules); create assessments; encode scores (inline table + Excel import using downloadable template); see auto-computed grades live; submit grade sheet; export PDF/Excel grade sheet; view class at-risk list with factors; add intervention notes per student |
| **student** | View own class-list subjects, running grades per component, period grades, released final grades; term GWA + cumulative GWA; progress charts; own forecast shown as **"Needs Attention" / "On Track"** (never the words "at-risk") with plain-language contributing factors and generic tips; notifications |

### 3a. Teaching load assignment (built)

**Admin assigns Program Heads; Program Heads assign teaching loads; an admin override is always
audited.** Admin picks each program's Program Head (Admin → Programs — unchanged); a class
(`academics.ClassOffering`) can exist with **no instructor** ("Unassigned") — every page that can
show a class (My Classes, approvals, forecasting, reports) handles this gracefully, it just never
appears on an instructor's own list. From there, assigning who actually teaches a class is the
Program Head's job for classes whose sections belong to a program they head (a class shared across
programs can be assigned by any of those programs' heads) — `academics:program_head_classes` is now
a teaching-load manager: an "Assign/Change Instructor" action per class (the existing searchable
instructor picker, active INSTRUCTOR users only), an "Unassigned only" filter, a banner counting
unassigned classes, and a bulk "select several → assign one instructor" action
(`academics:class_bulk_assign_instructor`). Admin keeps the ability to set/change it too — through
the same Classes CRUD edit form (`academics:class_edit`) — as a logged **admin override**: the
instructor field's help text warns "Teaching loads are normally assigned by the Program Head", and
`ClassFormView.post()` routes an instructor-field change through the same
`academics.services.assign_instructor`/`log_and_notify_instructor_change` path as the Program Head
flow, rather than a bare `form.save()`, so both paths behave identically.

**Rules** (`academics/services.py`): changing a class's instructor is blocked once its grade sheet
is SUBMITTED-or-later (`check_instructor_change_allowed`, reusing
`approvals.services.is_class_editable` — allowed in DRAFT/RETURNED or when no sheet exists yet);
a no-op reassignment (same instructor) is never logged or notified. Every real change notifies the
new instructor ("You've been assigned PEd 205 – BSED-ENG 3, BSED-SS 3") and the previous one if any
("PEd 205 was reassigned") via `dashboard.services.notify`, and writes an
`academics.TeachingAssignmentLog` row (class, old → new instructor, changed_by, `is_admin_override`,
optional reason, timestamp) — combined into the admin Audit Log page (`accounts/audit.py`'s new
`"teaching_assignment"` source) and shown as a small "Assignment history" list on the class's roster
page. **Teaching Loads** (`academics:teaching_loads`, Program Head sidebar under Academics / Admin
sidebar under Academic Setup; Program Head scoped to their own program(s), Admin all with a program
filter): per instructor in the active semester — classes, total units, student count — plus a
separately-listed "Unassigned classes" section (never silently dropped) and an instructor filter;
Excel export. The Program Head dashboard's placeholder "Avg. Pass Rate" stat card was replaced with
a real "Unassigned Classes" count linking to the filtered Classes page.

Enforce access with middleware + Django Policies (view-level `role_required`/`RoleRequiredMixin`
today; move to per-object permission checks once there's per-object data to protect). Instructors
must never see classes not assigned to them; students only their own data. Write tests for every
authorization rule — `accounts/tests.py` has the pattern (login, menu visibility, 403s).

### 3b. Program Head academic-setup scope (built)

**Day-to-day academic setup belongs to each program's Program Head, scoped to their own
program/major — Admin works at institution level and keeps a full, audited override.** A Program
Head can be assigned at **PROGRAM level** (`Program.program_head`, unchanged — covers every major
in that program with no head of its own) or at **MAJOR level** (`Major.program_head`, nullable —
takes precedence over the program-level catch-all for that one major; a program-level and a
major-level assignment for the same user are both kept, since they mean different things). One
helper, `academics.scoping.scope_for(user)`, is the single source of truth every object-level
"does this Program Head own X" check uses — it returns `None` for admin (unrestricted — every
caller must branch on this before filtering, rather than treating `None` as "no matches") or a set
of `(program_id, major_id-or-None)` tuples for everyone else; companion querysets
`sections_in_scope`/`classes_in_scope`/`subjects_editable_by`/`programs_in_scope` and a membership
check `is_in_scope(user, program_id, major_id)` build on it. `scope_for` is memoized on the user
instance — it used to be recomputed (2 queries each) up to 3x in a single request (the sidebar
badge, the INC-completions badge, the page's own class list); a fresh request always gets a
freshly-queried `User` instance, so this never leaks across requests or users. This replaced ~10
independently-duplicated `sections__program__program_head=user`/`program__program_head_id=
user.id` expressions across academics/approvals/dashboard/forecasting/grading/reports/accounts.

**What moved to the Program Head** (all under a new "My Program" sidebar group, scoped — no
program/major dropdowns to pick from, since there's only ever one correct choice):
- **Sections** (`academics:ph_sections`) — create/edit for the active semester's academic year;
  program/major pre-filled and locked to scope (or offered as a choice if the head covers more
  than one). Section has no `is_active` field, so delete is a real delete with the same
  `ProtectedError` → friendly-message handling as admin's own Sections page.
- **Subjects** (`academics:ph_subjects`, built as a prospectus-style view, see section 3b's
  Curriculum mapping note below) — the subject catalog stays **shared**: subject codes are unique
  school-wide (GE 2, PEd 202 are created once and reused), so a Program Head can use *any* active
  subject when building a class. A subject's placement into a program/major's prospectus (year
  level, term) is a separate `academics.CurriculumEntry` row, not a field on `Subject` itself — the
  same subject code can sit in several curricula at once. "Add Subject" offers two paths: attach an
  existing catalog subject into the current program/major's prospectus, or create a brand-new one
  and attach it in the same step. **Editing** a subject's title/units is only allowed when *every*
  one of its `CurriculumEntry` rows belongs to the head's own scope (`academics.scoping.
  subjects_editable_by`) — a subject placed in any other program/major shows "Shared — ask the
  Admin to edit" instead. "Remove from curriculum" deletes only the `CurriculumEntry`, never the
  `Subject` (and any other program/major still using it) — blocked while an active-semester class
  uses that placement.
- **Classes** (`academics:program_head_classes`, now a full create/edit page, not just a teaching-
  load manager) — subject (any active) + their own sections + schedule/room/instructor. A class
  shared across programs (one Gen Ed class serving two majors' sections) can be **joined**
  (`academics:ph_class_join` — pick an existing class with the same subject in the active
  semester, add only their own in-scope sections to it, never a duplicate class) or **left**
  (`academics:ph_class_leave` — removes only the acting head's own sections; if that was the
  class's last section, it's auto-deactivated, logged with `details={"reason": "last section
  removed"}`). A class is manageable by every head whose section is in it; instructor assignment
  by any of them (teaching-load rules, section 3a, unchanged).
- **Class Lists** (`academics:class_lists`) and **Import Class Offerings**
  (`academics:offerings_import`) — same pages admin uses, scoped: a Program Head only sees/
  manages classes with at least one of their own sections (`_can_manage_roster` in
  `academics/views.py`); an import row resolving to a program/major outside scope is rejected in
  preview with `"<program>[-<major>] is outside your scope."`, and `commit_offerings_import`
  re-validates scope per row defensively at commit time too — the preview is session-stashed and
  round-tripped through the browser, never trusted blindly.
- **Teaching Loads** — unchanged (section 3a), now naturally including classes the Program Head
  created themselves.

**Admin's "Override" group** (sidebar, separate from "Academic Setup" which now only holds
Academic Years & Semesters/Programs/Majors) keeps the same five entities — Sections, Subjects,
Classes, Class Lists, Import Class Offerings, plus Teaching Loads — unscoped, with an amber banner
("These are normally managed by each program's Program Head...") on every one of those pages.
Every save there writes an `academics.AcademicSetupChangeLog` row (model, action, program/major
scope at the time, actor, `is_admin_override`, a JSON `details` snapshot) — the Program-Head
academic-setup equivalent of `TeachingAssignmentLog` (section 3a), one shared model rather than
three per-domain ones since Section/Subject/Class go through near-identical CRUD flows. Combined
into the admin Audit Log page as a new `"academic_setup"` source, labeled e.g. "Section updated
(admin override)" when `is_admin_override=True`, plain "Section updated" for a Program Head's own
edit.

**Dashboard & empty states**: the Program Head dashboard (`dashboard:home`) shows the head's scope
(`User.program_head_scope_label`, e.g. "BSED – English" or "BSIT (all majors)") under the page
title and a linked setup checklist for the active semester — sections created, classes created,
classes without an instructor, class lists still empty, grade sheets submitted — each scoped the
same way and linking to the page that fixes it. Every Program Head page shows a clear, shared
empty state (`partials/_no_active_semester.html`) when Admin hasn't activated a semester yet,
rather than a confusing blank page.

Admin assigns the Program Head role itself — Programs page (program-level) and Majors page
(major-level), both pickers listing only active PROGRAM_HEAD users; assigning or changing one
notifies the new head (`academics.services.notify_program_head_assignment`, no-op guarded against
a re-save that doesn't actually change anything). The Users page shows each head's current scope
next to their row.

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

**INC completion (post-completion enhancement, built — section 10):** on a RELEASED/LOCKED sheet,
for an entry with remarks INC, the instructor files "Complete INC" (`approvals.services.
file_inc_completion` — new final grade, date complied, notes), creating an `approvals.IncCompletion`
row (PENDING). The owning Program Head approves (`decide_inc_completion(..., approve=True)`, which
calls `correct_grade` verbatim — the same `GradeCorrection`/timeline/notifications as an admin
correction) or rejects (remarks required) from a new "INC Completions" tab on Grade Approvals.
"Completed INC" is never a stored flag on `GradeSheetEntry` (its `remarks` stays DB-constrained to
PASSED/FAILED/INC/DROPPED) — it's derived at display time from `entry.inc_completions.filter(
status=APPROVED).exists()`. A configurable window (`InstitutionSettings.inc_completion_window_days`,
default 365 days after `released_at`) blocks filing past it with "INC lapsed — contact Registrar"
and makes no automatic grade change. `compute_gwa` needs no extra recompute step — it's a pure
read-time computation, so the next call already reflects an approved completion's corrected grade.

**Grade submission deadline (post-completion enhancement, built — section 10):**
`academics.Semester.submission_deadline` (optional, admin-set per semester). Submitting after it
still succeeds but `approvals.services.submit_grade_sheet` snapshots `GradeSheet.is_late=True` at
submission time (never retroactively recomputed if the deadline later changes — a resubmit after
RETURNED recomputes fresh against the then-current deadline). Grade Approvals, Grade Sheets, and
the Submission Status report all gained a "late" filter + counts
(`approvals.services.late_or_unsubmitted_counts`). A standalone `send_reminders` management command
(deliberately separate from forecasting's `run_forecasts` — different domain) notifies instructors
with an unsubmitted sheet starting 3 days before the deadline, de-duplicated via a new
`GradeSheet.reminder_sent_at` field (set once, never cleared — a deadline doesn't recur).

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
- `academics.Subject` — code (unique school-wide), title, **units** (single Decimal — not split
  lec/lab), is_active. No program/major/year_level/term here (built, 2026-11-11) — where a subject
  sits in a program/major's prospectus is `CurriculumEntry` below, since the same subject can sit
  in several curricula at once (built, 2026-11-11).
- `academics.CurriculumEntry` — subject FK (PROTECT), program FK (PROTECT), major FK (PROTECT,
  nullable — TCP-style, no major), year_level (nullable), term; unique per (program, major,
  year_level, term, subject). Places a subject into one program/major's prospectus slot.
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
- `academics.TeachingAssignmentLog` (built, teaching-load assignment follow-up, section 3a) — one
  row per instructor assignment/reassignment: class_offering FK (CASCADE), old_instructor/
  new_instructor FK User (SET_NULL, nullable — None means "was/now Unassigned"), changed_by FK User
  (SET_NULL), is_admin_override (bool), reason (optional text). Combined into the admin Audit Log
  page (`accounts/audit.py`'s `"teaching_assignment"` source) and shown as a class's own
  "Assignment history" (`academics:class_roster`).

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
  student portal's OFFICIAL-vs-UNOFFICIAL toggle, see section 8). **Added Phase 7:**
  show_forecasts_to_students (BooleanField, default False — off while the active checkpoint models
  are SYNTHETIC; see section 7).

**Built (`forecasting`, Phase 6):**
- `forecasting.MlModelVersion` — checkpoint (`Checkpoint`: PRELIM/MIDTERM), trained_at,
  training_source (`TrainingSource`: SYNTHETIC/HISTORICAL/MIXED), n_samples, positive_rate,
  threshold (default 0.5, admin-adjustable), metrics_json (accuracy/precision/recall/f1/roc_auc +
  95% bootstrap CIs), cv_json (5-fold stratified CV mean ± SD), confusion_matrix_json,
  coefficients_json (feature, coefficient, odds ratio), feature_list (JSON — the exact feature
  names/order the model was trained on, plus each missing-category imputation median), is_active,
  model_file (joblib path under `MEDIA_ROOT/models/`, **not committed to git**). At most one active
  version per checkpoint (`save()` deactivates any other active version for the same checkpoint, same
  single-active pattern as `Semester`/`GradingTemplate`).
- `forecasting.Prediction` — roster_entry FK (CASCADE), checkpoint, model_version FK (PROTECT),
  probability, label (`RiskLabel`: AT_RISK/NOT_AT_RISK — internal/staff-facing value; the student-
  facing copy is "Needs Attention"/"On Track", applied at the template layer, never stored this way),
  contributions_json (per-feature contribution + plain-language reasons, sorted by impact),
  computed_at.
- `forecasting.HistoricalImportBatch` — uploaded_by FK User, uploaded_at, file_count, row_count,
  positive_count, term_assignment_note (the disclosed chronological-order-by-position assumption for
  old sheets' non-exam items — see section 7), skipped_rows_json (row, reason).
- `forecasting.HistoricalRecord` — masked_id (SHA-256, app-secret salt — **never** a name or
  ID number), semester_label, subject_code, checkpoint, features_json, label, batch FK (CASCADE to
  `HistoricalImportBatch`). No `StudentProfile`/`User` FK anywhere on this model, by design.

**Built (`forecasting`, Phase 7):**
- `Prediction` gained `instructor_notified_at`/`student_notified_at` (nullable DateTimeField,
  early-warning de-duplication — set when a notification fires for the current at-risk/watch
  episode, cleared back to `None` once the level drops, so a later episode can notify again — see
  section 7).
- `forecasting.Intervention` — roster_entry FK (CASCADE), created_by FK User (SET_NULL), date, type
  (`InterventionType`: CONSULTATION/REMEDIAL/REFERRAL/PARENT_CONTACT/OTHER), notes, follow_up_date
  (nullable), outcome (`InterventionOutcome`: PENDING/IMPROVED/NO_CHANGE, default PENDING) — logged
  from the forecast drawer, visible to instructor + program head only, never to students.

**Built (`accounts`, Phase 8 part A):**
- `accounts.AuditLog` — actor FK User (SET_NULL, nullable — null for a system-originated event like
  an axes lockout), action (`Action`: USER_CREATED/USER_UPDATED/USER_DEACTIVATED/USER_REACTIVATED/
  PASSWORD_RESET/ACCOUNT_UNLOCKED/ACCOUNT_LOCKED_OUT), target_user FK User (SET_NULL, nullable),
  details (JSONField — small non-personal context only, e.g. `{"role": "INSTRUCTOR"}` or
  `{"ip_address": "..."}`, never a name/ID number/password). Written via `accounts.audit.log_audit`
  from `accounts/views.py`'s user-management actions and from an `axes.signals.user_locked_out`
  receiver (`accounts/signals.py`). Combined with the pre-existing domain change-log tables into
  the admin Audit Log page — see section 9.

Produce `docs/ERD.md` as a Mermaid `erDiagram` that matches the final migrations exactly, once these exist.

**Built (post-completion enhancements, section 10):**
- `academics.StudentProfile.status` (`Status`: ACTIVE/COMPLETED, default ACTIVE) — set to COMPLETED
  by the New Academic Year wizard for 4th-years/TCP finishers (never deleted); "active student"
  counts/pickers (admin dashboard total, class-list "Add Students") exclude COMPLETED.
- `academics.Semester.submission_deadline` (nullable DateTimeField).
- `approvals.GradeSheet.is_late` (bool, default False, snapshotted at submission) and
  `reminder_sent_at` (nullable DateTimeField, de-dup for `send_reminders`).
- `approvals.IncCompletion` — entry FK (CASCADE to `GradeSheetEntry`), filed_by FK User (SET_NULL),
  new_grade, new_remarks (PASSED/FAILED only), date_complied, remarks_text, status
  (`IncCompletionStatus`: PENDING/APPROVED/REJECTED), decided_by FK User (SET_NULL), decided_at,
  decision_remarks (required on rejection).
- `reports.InstitutionSettings.inc_completion_window_days` (PositiveIntegerField, default 365).
- `accounts.AuditLog.Action` gained `ACADEMIC_YEAR_WIZARD_RUN` (one row per wizard run, counts only).

---

## 7. Forecasting Module (Logistic Regression)

**Status: Phase 6 (ML core, O4) is done — model lives in-process inside Django, no FastAPI, no
network hop.** The at-risk UIs, student forecast card, and early-warning notifications are Phase 7,
not yet built — see the Phase 6/7 split under "Build Phases".

**Goal:** predict, at a **checkpoint** mid-semester, whether a student is at risk of failing a
subject, so the instructor can intervene early.

**No separate ML service.** `forecasting/ml/` is a plain Python package (`features.py`,
`synthetic.py`, `train.py`, `evaluate.py`, `predict.py`) imported directly by Django views/commands
— same process, same deploy, nothing to keep available. This superseded the original spec's
FastAPI-service design before any of it was built (see Tech Stack).

**Checkpoints, not "midterm grade."** CITCI's class record has no separate midterm grade (section
4) — only four grading *periods* (Prelim/Midterm/Semi-final/Final, `grading.AssessmentTerm`). A
forecast is computed for a `(roster_entry, checkpoint)` pair, `checkpoint ∈ {PRELIM, MIDTERM}`
(`forecasting.Checkpoint`). Features for a checkpoint use **only** assessment items whose term is at
or before that checkpoint — Semi-final/Final items must never reach a PRELIM or MIDTERM feature row
(data leakage) — enforced by `features.py` and covered by a dedicated leakage-guard test. **Two
active model versions exist at a time, one per checkpoint** — trained, evaluated, and activated
independently.

**Target label (y = 1, "at risk"):** FINAL grade > 3.00 (CITCI passing is ≤ 3.00 — grades are
continuous 1.00–5.00, not only a flat 5.00, so the comparison must be `> 3.00`, never `== 5.00`),
or remarks = INC, or remarks = DROPPED. Otherwise 0. Labels come **only** from RELEASED/LOCKED
`GradeSheetEntry` snapshots (live/in-progress data has no final label yet) or from
`HistoricalRecord` rows.

**Features** (`forecasting/ml/features.py`) — **keyed off `grading.ComponentCategory`, never off a
component's free-text name**, since instructors rename/reweight their own (unlocked) components per
class (section 4); a renamed/instructor-invented component still feeds the right feature because
extraction groups by category, not name. All percentages are earned ÷ possible × 100 over items
with term ≤ the checkpoint and at least one score anywhere in the class (same "encoded" rule
`grading.services.running_grade` already uses). The final feature list:

| Feature | Source |
|---|---|
| `quiz_pct` | category=QUIZ |
| `recitation_pct` | category=RECITATION |
| `project_pct` | category=PROJECT **or** OTHER (merged — CITCI's "Other" bucket is project-adjacent, not its own signal) |
| `attendance_pct` | category=ATTENDANCE |
| `exam_pct` | category=EXAM, items up to the checkpoint only |
| `running_grade` | the 1.00–5.00 running grade at the checkpoint (`grading.services`' formula, restricted to items up to the checkpoint — not the live current-term running grade) |
| `missing_rate_pct` | % of in-scope items (term ≤ checkpoint) with no score for this student |

A **missing category** (the instructor never set up that component at all — not to be confused with
a category that exists but isn't yet scored) is imputed with the **training-set median** for that
feature, plus a binary `<feature>_missing` indicator column so the model can still distinguish
"never had this component" from "scored 0 on it." Imputation values are fit on the training split
only and reused as-is for the test split and for live prediction (never refit on new data) — stored
in the model version's `feature_list` JSON alongside the median used.

**Pipeline:** `StandardScaler` → `LogisticRegression(class_weight="balanced", max_iter=1000,
random_state=<fixed>)`, fitted with maximum likelihood (scikit-learn's default solver).

**Threshold:** default 0.5, stored per model version, adjustable by admin — the Model Performance
page shows a precision/recall trade-off table for thresholds 0.3–0.7 so the admin can choose with
recall explicitly prioritized (missing an at-risk student costs more than a false alarm).

**Explainability** (`forecasting/ml/predict.py`): per-feature contribution = coefficient ×
standardized value, sorted by |impact|, plus a plain-language reason per top feature (e.g. "Quiz
average (42%) is low", "Many missing scores (35%)") — stored in `Prediction.contributions_json`.
Contributions plus the intercept sum exactly to the logit (`ln(p/(1-p))`) — a dedicated test checks
this to the Decimal/float precision scikit-learn allows.

**Training data**
- **Synthetic** (`forecasting/ml/synthetic.py` + `generate_synthetic_data` management command):
  ≈2,000 rows per checkpoint, 15–25% positive class, correlated features (low exam/quiz → higher
  risk, `missing_rate_pct` strongly predictive), fixed random seed. **Development and demo only —
  see the Chapter 4 rule below.** `generate_synthetic_data --csv <path>` (Phase 7) exports the
  deterministic dataset (features + label, per checkpoint) to CSV for the paper's
  appendix/reproducibility — no DB persistence, a pure export.
- **Historical import** (admin "Historical Data" page): upload past CITCI class records as `.xlsx`
  — either the CITCI class-record layout (`grading-system.xlsx`'s shape) or this system's own Class
  Record export (`reports/excel.py`) — one file per class, many files per batch. Reuses the existing
  preview → confirm import pattern (`reports/excel_import.py`'s shape, not its code — a different
  domain). Column mapping: component headers (Attendance/Quizzes/Recitation/Project/Examination) map
  to `ComponentCategory`; the four Examination columns (P/M/S/F) map to
  Prelim/Midterm/Semi-final/Final. **Old sheets' non-exam items carry no term** — assumed
  chronological-order-by-position, split into quarters (1st quarter of columns → Prelim, 2nd →
  Midterm, …). **This is a disclosed limitation, not a silent guess** — recorded on the import batch
  (`HistoricalImportBatch.term_assignment_note`) and called out here for Chapter 3. Identities are
  masked before anything is saved: `masked_id = SHA256(app secret salt + student identifier)`, names
  are **never** stored or logged — `HistoricalRecord` only ever holds `masked_id`, semester label,
  subject code, checkpoint, a features JSON, the label, and a batch FK.
- **Live data → historical**: an admin action ("Add released semesters to training data") exports
  the system's own RELEASED/LOCKED `GradeSheetEntry` data into masked `HistoricalRecord` rows the
  same way, for classes CITCI has actually run through GradeTrack.

**Evaluation** (`forecasting/ml/evaluate.py`, run on every training run)
- Stratified 80/20 train/test split, fixed random seed
- Accuracy, precision, recall, F1, ROC-AUC, confusion matrix
- 95% CIs via 1,000 bootstrap resamples of the test set
- 5-fold stratified cross-validation mean ± SD (in addition to the single-split metrics, not instead
  of them — CV guards against an unlucky split; the single split is what the CIs are computed on)
- A coefficients table (feature, coefficient, odds ratio = `exp(coefficient)`) for interpretability
- **Refuse to train on HISTORICAL alone** if fewer than 200 rows or fewer than 30 positives for that
  checkpoint — raise with a message explaining why and suggesting MIXED for development (never
  silently fall back to synthetic).
- Results saved to `forecasting.MlModelVersion` and shown on the admin **Model Performance** page;
  exportable as a PDF for Chapter 4 (`reports/pdf.py`, same `link_callback` pattern as every other
  report).

**`train_forecast_model` management command** — `--checkpoint {PRELIM,MIDTERM} --source
{synthetic,historical,mixed}`; trains, evaluates, saves a new (inactive) `MlModelVersion`. Activating
a version is a separate admin action (Model Performance page's "Activate" button on a version in its
history), never automatic on training — a newly-trained model must be reviewed first.

**Prediction** (`forecasting/ml/predict.py`): `predict(roster_entry, checkpoint)` →
`{probability, label ("at_risk"/"not_at_risk"), contributions}`, or `"insufficient_data"` when the
class has no scored items up to that checkpoint yet (nothing to extract features from). Every
prediction is persisted to `forecasting.Prediction` (roster_entry, checkpoint, model_version,
probability, label, contributions_json, computed_at) — no UI beyond the admin pages this phase; the
instructor/program-head at-risk list and the student's own forecast card are Phase 7.

**When predictions run:** no task queue (Celery/Redis — decided against, see Tech Stack) — cheap
enough to run synchronously. Phase 7 will recompute after an instructor saves scores (debounced per
class) and offer a "Recompute" button; this phase ships the primitive both of those will call,
`run_forecasts` — a management command (no view yet) that predicts for every active class-list entry
at both checkpoints, schedulable via Windows Task Scheduler/cron (no Celery beat needed for a
once/twice-daily job at this scale).

**Chapter 4 / final-defense rule:** The model shown in the final defense and Chapter 4 **must** be
trained and evaluated on real, masked CITCI historical data (or a MIXED set only if clearly
reported as such). Synthetic data is for development and demo only and **must always be labeled as
such** — the Model Performance page shows a prominent banner ("Trained on SYNTHETIC data — for
demonstration only") whenever `training_source != HISTORICAL`, and the PDF export carries the same
disclosure in its dataset-summary section.

## Forecasting in the UI (Phase 7, built)

**Display risk level — one helper, three tiers, never stored.**
`forecasting.services.risk_level(probability, threshold)`:
- **AT RISK:** probability ≥ the active model's threshold.
- **WATCH:** probability ≥ threshold − 0.15.
- **ON TRACK:** otherwise.

This is purely a display-time derivation off `Prediction.probability` and
`MlModelVersion.threshold` — there is no 3-tier column on `Prediction`, since AT_RISK here is
mathematically identical to the already-stored binary `RiskLabel.AT_RISK`; storing both would only
create a sync-drift risk. Every screen that shows a risk badge (At-Risk pages, Class Record forecast
column, Summary tab counts, the forecast drawer) calls this same function — there's no second
implementation anywhere. Each prediction's display always shows which checkpoint it's based on
("as of Midterm") and when it was computed.

**Current checkpoint of a class** (`forecasting.services.current_checkpoint_for_class`): MIDTERM if
any Examination-category item with term ≤ MIDTERM has a score anywhere in the class; else PRELIM if
any PRELIM item has a score; else `None` — shown everywhere as "Not enough data yet."

**When predictions recompute** — `forecasting.services.recompute_and_notify(roster_entries)` is the
single function every trigger below calls; it groups entries by class, skips a class whose grade
sheet is SUBMITTED or later (`approvals.services.is_class_editable` — the last forecast stays on the
record for evaluation, sitting next to the eventual actual outcome, rather than being clobbered by
scores that are no longer editable), and skips a class with no determinable checkpoint yet.
- **After a score save** (`grading.views.save_cell`), **fill-column**, and **Excel import confirm**
  (`reports/excel_import.py`'s `commit_import`, called once per import outside the atomic block):
  recomputes synchronously for the affected student(s) only, using the active model for the class's
  current checkpoint.
- **"Recompute forecasts" button** per class (instructor, program head on a class in their program)
  and per program (program head, all their program's classes) — `forecasting.views.recompute_class`/
  `recompute_program`, object-level checked (`_owns_class_for_forecasting`).
- **`run_forecasts` management command** — recomputes every active roster entry, for scheduled runs
  (Windows Task Scheduler/cron); also builds the program-head daily digest (below).
- **Display reads also lazily backfill** a still-missing prediction
  (`get_display_forecast`/`get_display_forecasts_for_class`), but only while the class is still
  editable — this is what satisfies the spec's "if recompute-after-save ever gets too slow, fall back
  to recomputing on the next page load" clause, as a natural side effect of the display layer rather
  than a separate latency-triggered code path (see the measured latency below — it was never actually
  needed). The cheap dashboard stat-card path (`count_at_risk_watch`) never backfills — it only reads
  what's already stored, to keep dashboard loads fast.
- **No active model, or any error:** `get_display_forecast` returns a sentinel ("unavailable") that
  every template renders as "Forecast unavailable" — grading pages must never break because
  forecasting failed; errors are logged, not raised.

**Measured latency** (spec: must not slow saves noticeably; budget 150ms/save). `save_score` +
`recompute_and_notify` for one student, called directly: median ~4–6ms, worst case under 25ms across
repeated runs with a warm model cache. The same path through the real `grading:save_cell` HTTP view
(Django test client): median ~4ms, worst case ~5ms. Both are well under budget — synchronous
recompute-after-save stays exactly as designed; the "next page load" fallback was never triggered by
latency and exists only as the natural consequence of the lazy-backfill display path above.

**Instructor — "At-Risk Students"** (`forecasting:at_risk`, replaces the old placeholder menu item):
every AT_RISK/WATCH student across the instructor's active-semester classes — student, class,
checkpoint, risk badge, probability, top 3 reasons (plain language, from
`Prediction.contributions_json`), last intervention, actions. Filters: class, risk level. Sorted by
probability desc. The Class Record grid gets an optional "Forecast" column (toggle, default ON) with
the risk badge; hover/tap shows probability + reasons. The Summary tab shows counts by risk level.
A **student forecast drawer** (`forecasting:forecast_detail`, HTMX modal): probability, all feature
contributions as a horizontal Chart.js bar chart (positive = increases risk, negative = decreases —
`json_script`-embedded data so the chart survives an HTMX swap), reasons, forecast history
(Prelim → Midterm), and the interventions list.

**Interventions** (`forecasting.Intervention`: roster_entry, created_by, date, type — Consultation /
Remedial activity / Referral to guidance / Parent or guardian contact / Other — notes, optional
follow-up date, outcome — Pending / Improved / No change): logged from the drawer
(`forecasting:intervention_create`). Visible to the instructor and program head only, **never** to
students — `InterventionPrivacyTests` in `forecasting/tests.py` checks the student-facing pages never
render intervention content, even though the data (scoped to a roster entry a student *can* view
elsewhere) sits right next to data they can see.

**Program Head — "At-Risk Students"**: for their program(s) in the active semester — summary cards
(students at risk, watch, classes affected, interventions logged), a table by class (class,
instructor, at risk count, watch count, interventions count, a per-class Recompute action), and the
same student-list table as the instructor's page (read-only interventions, can add notes). Excel
export (`forecasting:at_risk_export`). The admin and program-head dashboards' "At-Risk Students" stat
cards use real counts (`forecasting.services.count_at_risk_watch`), never a placeholder "—".

**Students — supportive, never raw probability** (`forecasting.services.student_forecast_card`):
replaces the dashboard's old "Academic Forecast — Coming soon" placeholder and adds a matching
section to Subject detail.
- ON TRACK: "You're on track in PEd 205. Keep it up!"
- WATCH/AT RISK: "PEd 205 needs your attention." + the top 1–2 factors in student-friendly words
  (its own `_STUDENT_FACTOR_LABELS` mapping — **never** the instructor-facing contribution-reason
  strings, which contain percentages) + 3 generic study tips + "Talk to your instructor."
- The function never returns probability, the words "at risk"/`AT_RISK`, or any model detail —
  `StudentPrivacyTests` asserts this against both the rendered dashboard/Subject-detail HTML and the
  raw dict the function returns.
- **`InstitutionSettings.show_forecasts_to_students`** (System → Settings): **off by default** while
  the active checkpoint models are SYNTHETIC — students then see no forecast content at all (not even
  a placeholder). Admin turns it on once a real, masked-historical model is active.

**Early-warning notifications**, de-duplicated per *episode* (not per recompute) via two nullable
timestamps on `Prediction` — `instructor_notified_at`/`student_notified_at` — set when a notification
actually fires for the student's current at-risk/watch run, and cleared back to `None` the moment the
level drops below the relevant tier, so a *later* episode can notify again without ever repeating on
every recompute while the student stays at the same level (`NotificationDeduplicationTests`).
- **Instructor:** when a student's level changes to AT RISK, one batched notification per class per
  recompute ("2 students in PEd 205 may need attention"), linking to the At-Risk page — never one
  notification per student.
- **Program Head:** one **daily digest** notification, created by `run_forecasts`, summarizing new
  at-risk students across their program(s) that day.
- **Student:** one supportive notification per class per checkpoint when newly WATCH-or-worse — only
  if `show_forecasts_to_students` is on, and never for a class whose grades are already released.

**Synthetic-model transparency:** whenever the active model for either checkpoint has
`training_source` SYNTHETIC or MIXED, every instructor/program-head/admin forecast view (At-Risk
pages, forecast drawer) shows a small gray banner: "Demo model — trained on synthetic data. Results
are for demonstration only." (`forecasting/_synthetic_banner.html`, reused from the existing Model
Performance page pattern.)

**Demo data** (`python manage.py seed_forecasting_demo`, idempotent, auto-run at the end of
`seed_citci_academics`): trains + activates a synthetic model per checkpoint if none is active,
recomputes forecasts for the existing demo classes' rosters, and logs one or two Interventions for an
at-risk student. In practice the already-seeded low/high performer scores (from
`seed_grading_demo`/`seed_student_portal_demo`) produce a natural mix of AT_RISK/WATCH/ON_TRACK
without any nudging — the command has a one-student "nudge toward at-risk" fallback for the rare case
a run produces no variety at all, but it was not exercised on the actual seeded data.
`show_forecasts_to_students` is deliberately left off by the seeder (matching its documented
synthetic-model default) — an admin must turn it on by hand to see the student forecast card render
with real content.

---

## 8. Screens

**Shared (built):** login (locked-out message via django-axes), forced password change (doubles as
a voluntary "Change Password" page — `accounts:force_password_change` has no must-change-password
guard, it just also redirects to privacy consent if that's still outstanding), profile (view all
fields; the only one the user can edit themselves is email — name/ID/role changes are admin-only),
help (placeholder), notifications bell (built, Phase 4 part 1 — unread badge + dropdown, HTMX-
polled every 60s, see section 5), responsive sidebar/topbar layout, Data Privacy notice/consent
shown on first login (RA 10173) — **built, Phase 8 part A:** both the login page's modal and the
forced first-login consent page now render `InstitutionSettings.privacy_notice_text`/
`data_privacy_officer_contact` (admin-editable, System → Settings) instead of two separately
hardcoded copies of the same text — styled 403/404/500/CSRF-failure pages (the last three built
Phase 8 part A, standalone templates, see section 9), a global toast notification system (Phase 8
part A, see section 9), per-page browser tab `<title>`, favicon.

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
`EntityDeleteView`/`ToggleActiveView`) rather than per page. **Program Head scope redesign (built
— see section 3b):** Sections/Subjects/Classes/Class Lists/Import Class Offerings/Teaching Loads
move to a new sidebar "Override" group (Academic Setup keeps only Academic Years & Semesters/
Programs/Majors) — each of those 5 pages now shows an amber "Override mode" banner, and every
save on them logs an `academics.AcademicSetupChangeLog` row with `is_admin_override=True`
(`SectionFormView`/`SubjectFormView`/`ClassFormView` in `academics/views.py`).

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
own program(s) at the query level (`reports.views._scope_programs`). **At-Risk Students (built,
Phase 7 — `forecasting:at_risk`):** summary cards (at risk/watch/classes affected/interventions
logged), a by-class breakdown table with a per-class Recompute action, the same filtered student
list the instructor sees (read-only interventions, can add notes), and an Excel export. The
dashboard's "At-Risk Students" stat card now shows a real count too. *(Dashboard's grade-distribution
chart is still a placeholder.)*

**Program Head scope redesign (built — see section 3b):** a new "My Program" sidebar group adds
**Sections** (`academics:ph_sections`), **Subjects** (`academics:ph_subjects`, shared catalog —
edit only within scope), and turns **Classes** (`academics:program_head_classes`) into a full
create/edit/join/leave page, all scoped to `academics.scoping.scope_for(user)` with no program/
major dropdowns (pre-filled and locked); **Class Lists** and **Import Class Offerings** are now
also reachable here (same pages admin uses, scoped — out-of-scope rows rejected in preview with a
reason). The dashboard's old placeholder stat cards were replaced with a linked setup checklist
(sections/classes created, classes without an instructor, empty class lists, sheets submitted)
and the head's scope (`User.program_head_scope_label`) shown under the page title; every page
shows a shared empty state if Admin hasn't set an active semester yet.

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
  banner. **Built, Phase 7:** an "At-Risk Students" menu item (`forecasting:at_risk`) replacing the
  old placeholder; the Class Record tab gets an optional "Forecast" column (toggle, default ON,
  risk badge per row, hover/tap for probability + reasons) and the Summary tab gets an AT_RISK/
  WATCH/ON_TRACK count row; a forecast drawer (probability, Chart.js feature-contributions bar
  chart, forecast history, interventions) opens from either the Class Record or the At-Risk page.

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
unofficial running grade, a progress bar for items encoded so far), an Academic Forecast card
(built, Phase 7 — `forecasting.services.student_forecast_card`; supportive wording only, gated by
`InstitutionSettings.show_forecasts_to_students`, shows nothing at all when off — see section 7),
and the latest 5 notifications. **My Grades** (`grading:my_grades`) —
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
running-grade calculation to items at or before each term), and (built, Phase 7) the same Academic
Forecast section as the dashboard, scoped to this one subject. **My Progress**
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

**Post-completion enhancements (built, section 10):** **Admin** — "Import Class Offerings"
(`academics:offerings_import`, Academic Setup) and "Copy from Previous Semester" (button on
Classes); a 4-step "New Academic Year Wizard" (button on Academic Years & Semesters) for AY/
semester/section creation and student promotion. **Instructor** — "INC to Complete"
(`approvals:inc_completions_list`); the dashboard is now a to-do list (section 10, item 5) instead
of count-only placeholders; the class grading page header shows a deadline countdown chip while
still DRAFT. **Program Head** — an "INC Completions" tab on Grade Approvals; a "late"/"not yet
submitted" filter + counts on Grade Approvals and the Submission Status report. **Admin (Grade
Sheets)** — the same late filter + counts. Django Admin no longer appears in any sidebar (section
10, item 6).

---

## 9. Non-Functional Requirements

- Django's password hashing (PBKDF2 default), CSRF, session regeneration on login, login lockout
  after 5 failed attempts (django-axes, by username, 15 min cooloff — Phase 2.2), 30-minute sliding
  session expiry + expire-on-browser-close (Phase 2.2), HTTPS-ready config for production (built,
  Phase 8 part A — `config/settings/prod.py`, see below)
- RBAC enforced server-side on every route; IDOR tests as data ownership exists
- **Audit log (built, Phase 8 part A):** `accounts.AuditLog` (user create/update/deactivate/
  reactivate, password reset, admin unlock, login-lockout — the last written with no `actor`, via
  an `axes.signals.user_locked_out` receiver in `accounts/signals.py`) combined with the existing
  per-domain change logs (`grading.ScoreChangeLog`, `grading.SchemeComponentChangeLog`,
  `approvals.GradeSheetTransition`, `approvals.GradeCorrection`) into one admin-only, filterable,
  Excel-exportable page (`accounts:audit_log`, `accounts/audit.py`'s `collect_audit_rows` —
  normalizes all five sources into one sorted list rather than a shared table, since each source
  already exists with its own FKs into its own domain). Model-training/activation events are
  implicit in `forecasting.MlModelVersion.trained_at`/`is_active` — not duplicated into AuditLog.
- **Production settings split (built, Phase 8 part A):** `config/settings/{base,dev,prod}.py` —
  `DJANGO_SETTINGS_MODULE` picks one (`manage.py` defaults to `config.settings.dev`; `wsgi.py`/
  `asgi.py` default to `config.settings.prod`, since a WSGI/ASGI server is inherently a production
  concern). `prod.py`: `DEBUG=False`; refuses to start (`ImproperlyConfigured`) on a missing/
  insecure `SECRET_KEY` or empty `ALLOWED_HOSTS`; `CSRF_TRUSTED_ORIGINS` from env;
  `X_FRAME_OPTIONS=DENY`/`SECURE_CONTENT_TYPE_NOSNIFF`/`SECURE_REFERRER_POLICY` always on (in
  `base.py`, so dev gets them too); HSTS/`SECURE_SSL_REDIRECT`/`SESSION_COOKIE_SECURE`/
  `CSRF_COOKIE_SECURE` all gated behind one `ENABLE_HTTPS` env flag (**off by default** — CITCI may
  start on a plain-HTTP LAN with no certificate yet; turning it on without an actual TLS front end
  makes the site unreachable, see `docs/DEPLOYMENT.md` "Turning on HTTPS"). `manage.py check
  --deploy` against `prod.py` with `ENABLE_HTTPS=False` shows exactly 4 warnings
  (W004/W008/W012/W016, all HSTS/secure-cookie related) — these are the **intentional, documented**
  exceptions for a plain-LAN-HTTP deployment, not oversights; with `ENABLE_HTTPS=True` (and a real
  cert) the same check is clean.
- **Error pages (built, Phase 8 part A):** standalone, brand-colored 404/500/CSRF-failure
  templates under `templates/errors/` (`accounts.views.not_found_view`/`server_error_view`/
  `csrf_failure_view`) that do **not** `{% extends "base.html" %}` and are rendered via
  `loader.render_to_string(name)` with no `request` argument, so they never run the
  `auth`/`accounts.context_processors.sidebar`/`academics.context_processors.active_semester`
  context processors — all three touch the database, and the whole point of a 500 page is to still
  render when the database is the thing that broke. 403 (`accounts/403.html`, pre-existing) is
  unchanged — it only ever fires post-authentication, so its DB dependency is lower-risk.
  `CSRF_FAILURE_VIEW` wired to `csrf_failure_view` for an expired-session-friendly message instead
  of Django's default raw CSRF error page.
- **Health check (built, Phase 8 part A):** unauthenticated `GET /healthz` (`core.views.healthz`,
  `core/tests.py`) — `SELECT 1`, 200 `{"status": "ok", "db": true}` or 503
  `{"status": "error", "db": false}` on `OperationalError`. For the server admin / an external
  monitor, not for app logic.
- **Backups (built, Phase 8 part A):** `python manage.py backup_db`
  (`core/management/commands/backup_db.py`) — `pg_dump -Fc` to `BACKUP_DIR` (env, default
  `./backups`) with a timestamped filename, plus a timestamped `MEDIA_ROOT` copy, pruning beyond
  the last `BACKUP_KEEP` (env, default 30) of each; `subprocess.run` is wrapped in an overridable
  `Command._run` specifically so tests can mock it without a real `pg_dump`. `restore_db` runs
  `pg_restore --clean --if-exists` and refuses without an explicit `--yes-i-am-sure` flag (no
  interactive prompt — this is meant to be scriptable, the flag itself is the confirmation).
  Scheduling examples (cron + Windows Task Scheduler) in `docs/DEPLOYMENT.md`.
- **Logging (built, Phase 8 part A):** rotating file handlers in `prod.py` only (dev stays
  console-only) — `logs/app.log` (INFO+, 10MB × 10 files) and `logs/error.log` (WARNING+ only, so
  routine request noise doesn't drown out real errors), dir overridable via `LOG_DIR`. Reviewed
  every existing logger call (`forecasting/services.py`, the only app-level logger in the codebase)
  for personal data — it only ever logs a `roster_entry.pk`, never a name/ID number/score.
- **Demo-seeder guard (built, Phase 8 part A):** every `seed_*` management command
  (`seed_demo_users`, `seed_citci_academics` and the three it chains to internally) refuses to run
  under the production settings module unless `--force-demo` is passed (`core/management/guards.py`'s
  `ensure_demo_allowed`/`add_force_demo_argument`) — seeding fake students/grades onto a live
  production database by habit (running the usual setup command) would be a serious mistake.
  Deliberately checks `settings.SETTINGS_MODULE.endswith(".prod")`, not `settings.DEBUG` — Django's
  test runner always forces `DEBUG=False` for every test regardless of settings module (so test
  results never depend on dev-only behavior), which would make a DEBUG-based guard fire on every
  test that calls a seed command; this was caught by `academics.tests.SeedCitciAcademicsIdempotencyTests`
  failing when this guard first shipped, and fixed the same session.
  `setup_production` (`accounts/management/commands/setup_production.py`) is the real first-run
  command instead: creates the first admin (interactive by default, `--username`/`--email`/
  `--password` for scripted/test use), `InstitutionSettings`, and the CITCI Default grading
  template (`grading.services.ensure_default_grading_template`, extracted so both this command and
  `seed_grading_demo` — which additionally needs per-item max-score lists for its fake data — share
  the template-creation logic rather than duplicating it) — deliberately **no** demo data.
- **UI polish (built, Phase 8 part A):** a global toast system (`templates/base.html`'s
  `x-data="toasts()"` stack, `aria-live="polite"`) fed by Django messages
  (`templates/partials/_messages.html`, one `toast` CustomEvent per message) and by any HTMX
  response whose `HX-Trigger` JSON includes a `"toast": {"message": ..., "level": ...}` key —
  `core.crud.trigger_response` grew an optional `toast=`/`toast_level=` kwarg, and the shared
  `EntityFormView`/`EntityDeleteView`/`ToggleActiveView` (used by every admin academic-setup CRUD
  page) plus several explicit `trigger_response` call sites (Users, Grading Templates, Class Lists,
  Semester "Set active") now pass one — broad coverage from a few call sites rather than touching
  every view in the app. HTMX loading state is global CSS, not per-template wiring: htmx already
  adds an `htmx-request` class to the triggering element (or an explicit `hx-indicator` target) for
  the duration of any request with zero template changes needed, so
  `.django_tailwind_cli/source.css` just styles that class (dimmed + `pointer-events: none`) plus a
  `.spinner`/`.htmx-indicator` utility for a template that wants an explicit "Saving…" indicator.
  Non-HTMX `<form>` submits get the same double-submit protection via a tiny global listener
  (`static/js/form-guard.js`) that disables submit buttons on `submit`, skipping any form that
  already carries `hx-post`/`hx-get` (htmx handles its own). Per-page `<title>` ("Page — CITCI
  GradeTrack") is the existing `h1#page-heading` topbar text mirrored into `document.title` by a
  small inline script in `base.html` — not a second `{% block %}`, since Django disallows the same
  block name twice in one template and this avoids needing a differently-named block added to every
  page template; the two guest-only pages (login, locked-out) set `{% block html_title %}` directly
  since they have no `#page-heading`. Favicon: `static/img/citci-seal-256.png` via `<link rel="icon">`.
- Response time < 2 s for normal pages with seeded data of 500 users; `select_related`/
  `prefetch_related`, add indexes, paginate lists. **Query-count pass, Phase 8 part A** (measured
  via `CaptureQueriesContext` against the four heaviest pages, instructor/program-head accounts,
  the largest seeded class): Class Record tab 39 queries, Summary tab 39, Admin Grade Sheets
  33 → **18** (fixed a `ClassOffering.__str__`/`Section.__str__` N+1 — iterating `sections.all()`
  per sheet with no prefetch — via `prefetch_related("class_offering__sections__program",
  "class_offering__sections__major")`), Program Head At-Risk 176 → **118** (two fixes:
  `forecasting.services.current_checkpoint_for_class` rewritten to resolve its "term ≤ checkpoint"
  cutoff to a list of term values in Python — no query — and check score existence via one
  `term__in=` query per tier instead of materializing `AssessmentItem` objects first and querying
  `Score` separately; `_at_risk_program_head`'s per-class `Intervention.objects....count()` replaced
  with one grouped `.values(...).annotate(Count(...))` query; `_class_at_risk_rows`'s
  `entry.interventions.first()` per AT_RISK/WATCH row now reads a `prefetch_related` cache via
  `next(iter(entry.interventions.all()), None)` instead of re-querying). Further reduction on the
  At-Risk page (e.g. batching checkpoint-determination across all of a program head's classes in one
  query) would need a larger refactor of `current_checkpoint_for_class`'s per-class signature — not
  attempted this pass. Pagination added to every list page that had none and could plausibly grow
  past one screen: `approvals:index`/`approvals:submitted` (Django `Paginator`, 20/page,
  HTMX-aware "Previous"/"Next" matching the existing `core.crud` pattern) and both At-Risk pages
  (25/page; the Excel export still exports every row, unpaginated, by design). Admin academic-setup
  CRUD pages were already paginated (`core.crud.EntityListView`, 20/page) — untouched.
  `django-debug-toolbar` wired in `config/settings/dev.py` only (guarded by `try/except ImportError`
  so a fresh checkout without `requirements-dev.txt` installed still runs; **opt-in** via
  `DEBUG_TOOLBAR=1` as of the Phase 8 part B pass below — always-on skewed the query-count/latency
  numbers this file documents), never loads in prod.

  **Query-count pass, Phase 8 part B** (dashboards and the student portal; same
  `CaptureQueriesContext` method, measured against the real demo accounts with `DEBUG_TOOLBAR`
  off). Program Head dashboard 101 → **13** queries (31 ms) — `forecasting.services.
  count_at_risk_watch` was calling `current_checkpoint_for_class` in a per-class loop (~3 queries x
  every class); rewritten around a new shared `_checkpoints_for_classes` batch primitive (2 queries
  total for however many classes) plus one grouped `Prediction` query instead of one per class —
  `get_display_forecasts_for_classes` (the At-Risk pages) was refactored onto the same primitive, no
  behavior change. Student dashboard 111 → **32** queries (78 ms) — `released_entry_for`,
  `compute_student`, and `student_forecast_card` were each called once PER subject in a loop;
  `grading.services` gained batch siblings `released_entries_for`/`compute_students_batch` and
  `forecasting.services` gained `student_forecast_cards_batch`, all built on the same "resolve for
  every row in a handful of queries total" shape as the Phase 8 part A fixes above (`compute_student`/
  `running_grade_progression` also gained an optional pre-fetched-`components` parameter so a caller
  that already has the scheme, like `subject_detail`, doesn't make it re-query); `approvals.services.
  compute_gwa`'s own per-roster-entry `GradeSheetEntry.objects....first()` loop was replaced with one
  call to the new batch helper too. My Grades 53 → **23** (53 ms), My Progress 61 → **31** (67 ms),
  Subject detail ~29 → **24-25** (50 ms, after also deduplicating three separate scheme/component/
  score fetches down to one, threaded through `compute_student`/`running_grade_progression`).
  Instructor dashboard was already cheap (9 queries) and untouched. All times are well under the
  200/400 ms interactive-page intuition **and** this phase's own ≤20-query targets wherever the
  underlying page's legitimate per-request chrome (session/auth/sidebar/student-profile lookups —
  present on every authenticated page, not specific to these views) left room to reach it; the
  Program Head dashboard and instructor dashboard do, the student-facing pages land in the
  low-to-mid-20s/30s once that fixed chrome is counted — see `dashboard.tests.
  DashboardQueryCountTests` for the regression guard (asserts each page stays flat as subject/class
  count grows, not a specific number).
- Deployable on an institution-controlled server (on-prem or institution-managed VPS) — **built,
  Phase 8 part A**: `docs/DEPLOYMENT.md` (two targets — Ubuntu/Gunicorn/Nginx primary,
  Windows/Waitress/NSSM alternative — first-time setup, updating, backups/restore, log locations,
  SECRET_KEY rotation, giving the server a fixed LAN hostname, HTTPS setup, and a post-install
  checklist) + `deploy/` (`gunicorn.service`, `nginx.conf`, `.env.prod.example`,
  `scripts/deploy.sh`, `waitress_serve.py`) + `requirements-prod.txt` (gunicorn, waitress,
  whitenoise — Windows needs `waitress_serve.py` to insert the project root onto `sys.path`
  explicitly, since NSSM invokes it as a script file rather than a module, which otherwise puts only
  its own `deploy/` directory on the path). Local prod-mode smoke test passed: `DEBUG=False`,
  `collectstatic` (found and fixed a latent bug along the way — the vendored
  `chart.umd.min.js`'s trailing `//# sourceMappingURL=chart.umd.js.map` comment pointed at a
  `.map` file that was never vendored, which `ManifestStaticFilesStorage`/WhiteNoise's manifest
  storage both reject by default since they validate every referenced asset exists — fixed by
  stripping that comment line, a pure devtools convenience reference with no runtime effect),
  Waitress + WhiteNoise serving manifest-hashed static files correctly, security headers present
  (`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`), and
  the custom 404 page rendering (confirmed only reachable with `DEBUG=False` — Django's own
  technical debug page takes over otherwise, by design).
- Accessible: labels on inputs, sufficient color contrast (WCAG AA verified for the brand palette),
  works at 360 px width. **Phase 8 part A pass** (global chrome, not an exhaustive per-template
  audit — see the note under "Build Phases"): `aria-live="polite"` on the toast stack; `aria-label`
  added to every icon-only button in the shared chrome that had none (sidebar collapse/expand
  toggle, mobile menu open/close, notification bell); Escape-to-close on the shared modal
  (pre-existing) and the mobile sidebar drawer/user-menu popover (pre-existing,
  `@click.outside`/`@keydown.escape.window`) already cover keyboard reachability for those.
- All dates/times in `Asia/Manila` (`config/settings/base.py`).

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
- **Phase 6 — ML core (O4, done):** the model lives **in-process inside Django** (`forecasting/ml/`
  — `features.py`/`synthetic.py`/`train.py`/`evaluate.py`/`predict.py`), not a separate FastAPI
  service — that part of the original spec was superseded before anything was built (see Tech
  Stack and section 7). Checkpoints (PRELIM/MIDTERM) replace "midterm grade" since CITCI's class
  record has no such field; features are keyed off `ComponentCategory`, never component name; the
  leakage guard (no Semi-final/Final item ever reaches a PRELIM/MIDTERM feature row) is unit-tested.
  Label: FINAL grade > 3.00, INC, or DROPPED = at risk — from RELEASED/LOCKED `GradeSheetEntry`
  snapshots or `HistoricalRecord` only. `StandardScaler` → `LogisticRegression(class_weight=
  "balanced")`; stratified 80/20 split, bootstrap CIs, 5-fold CV, a 0.3–0.7 threshold trade-off
  table, coefficients/odds-ratios. Training data: a synthetic generator
  (`generate_synthetic_data` command, dev/demo only) and a masked historical import (admin
  "Historical Data" page, `.xlsx`, SHA-256-salted `masked_id`, names never stored — plus an
  "Add released semesters to training data" action that masks GradeTrack's own released data the
  same way). Training refuses HISTORICAL-only runs under 200 rows / 30 positives for a checkpoint.
  No task queue — predictions are synchronous; `run_forecasts` management command is the
  schedulable primitive Phase 7's "after score save" and "Recompute" triggers will both call. Admin
  **Model Performance** page (metrics/CIs/CV/confusion matrix/ROC/coefficients, a "Trained on
  SYNTHETIC data" banner when applicable, version history with Activate, a PDF export for Chapter
  4) and **Historical Data** page (batch list, import, delete). **Chapter 4 rule:** the model shown
  in the final defense must be trained on real masked CITCI data (or MIXED, clearly reported) —
  synthetic is dev/demo only and always labeled as such. Deliberately **not** built this phase
  (Phase 7): the at-risk list UI, the student's forecast card, and early-warning notifications —
  this phase ships the model and the data pipeline those will read from, not the UI.
- **Phase 7 — Predictions in the UI, interventions, early warning (O3, O4, done):** recompute wired
  to real triggers — synchronous after a score save/fill-column/Excel-import confirm (measured
  ~4–6ms per student, well under the 150ms "must not slow saves noticeably" budget, so no fallback
  to next-page-load recompute was needed in practice), plus per-class/per-program "Recompute"
  buttons and the `run_forecasts` schedulable command. The `risk_level` 3-tier display helper
  (AT_RISK/WATCH/ON_TRACK, derived from probability + threshold, never stored) backs every risk
  badge. At-Risk Students pages for instructor and program head (filters, summary cards, by-class
  breakdown, Excel export), a Class Record "Forecast" column + Summary risk counts, and a forecast
  drawer (Chart.js feature-contributions bar chart, forecast history, interventions) replace the
  old placeholder menu item and "Coming soon" cards. New `forecasting.Intervention` model
  (instructor/program-head only, never shown to students). Student-facing
  `student_forecast_card` never returns probability or the words "at risk" — supportive message +
  plain-language factors + generic tips — gated by `InstitutionSettings.show_forecasts_to_students`
  (off by default while the active model is SYNTHETIC). Early-warning notifications de-duplicated
  per episode via `Prediction.instructor_notified_at`/`student_notified_at` (instructor: batched
  per class per recompute; program head: one daily digest from `run_forecasts`; student: one per
  class per checkpoint, only if the settings toggle is on). A synthetic-model banner appears on
  every staff-facing forecast view whenever the active checkpoint model isn't HISTORICAL. Also
  added this phase: `generate_synthetic_data --csv <path>` (pure export, no DB write, for the
  paper's appendix). `seed_forecasting_demo` (idempotent, auto-run at the end of
  `seed_citci_academics`) ensures active models exist and a couple of Interventions are logged, so
  the new pages aren't empty on a fresh environment — in practice the existing seeded low/high
  performer scores produced a natural AT_RISK/WATCH/ON_TRACK mix without needing the command's
  "nudge one student" fallback. `show_forecasts_to_students` was deliberately left off by the
  seeder, matching its documented synthetic-model default, rather than force-enabled for demo
  purposes.
- **Phase 8 part A — Production hardening, polish, and deployment setup (done):** settings split
  into `config/settings/{base,dev,prod}.py` with hard SECRET_KEY/ALLOWED_HOSTS checks and an
  `ENABLE_HTTPS`-gated security posture (see section 9 for the full list — 4 intentional
  `check --deploy` warnings with HTTPS off, clean with it on); an admin Audit Log page combining
  `accounts.AuditLog` (new — account changes + axes lockouts) with every existing domain
  change-log table; standalone, DB-independent 404/500/CSRF-failure pages; `/healthz`;
  `backup_db`/`restore_db` management commands (subprocess mocked in tests); rotating file logging
  in prod only; every demo seeder gated behind `DEBUG` + `--force-demo`
  (`core/management/guards.py`) and a new `setup_production` first-run command that creates a real
  admin + Institution Settings + the CITCI Default template with **no** demo data; a global toast
  system + htmx loading-state CSS + non-htmx double-submit guard; per-page `<title>` via the
  existing topbar heading (no new per-template block); a query-count pass that took Admin Grade
  Sheets from 33→18 queries and the Program Head At-Risk page from 176→118 (two N+1 fixes — see
  section 9 for both); pagination added to every previously-unpaginated list page that could grow;
  `docs/DEPLOYMENT.md` + `deploy/` (Gunicorn/Nginx/systemd for Ubuntu, Waitress/NSSM for Windows,
  both smoke-tested locally — the Waitress/WhiteNoise test caught and fixed a latent vendored-asset
  bug that would have broken `collectstatic` on either target, see section 9). Deliberately not
  attempted this pass: an exhaustive per-template accessibility audit (did the shared chrome —
  toast `aria-live`, icon-button `aria-label`s — rather than every form in every app) and further
  At-Risk-page query reduction (would need batching `current_checkpoint_for_class` across classes,
  a larger refactor of its per-class signature). **Part B (ISO/IEC 25010 UAT questionnaire +
  analysis script) is the next phase, not built yet** — see below.
- **Phase 8 part B — Testing & evaluation (O5, done — project complete):**
  - 293 tests, 76.1% overall line coverage, ≥80% on every service module and every access-control
    module (the spec's actual target — see `docs/TEST_REPORT.md` for the full breakdown and why the
    overall number sits lower: HTTP view-layer secondary branches and two data-import parsers,
    neither a service nor access-control code).
  - `core.management.commands.seed_load_test`: 1 admin, 2 program heads, 15 instructors, 450
    students, current + 2 past terms with realistic scores, released sheets, computed forecasts —
    all data clearly prefixed `load_`/`LOAD*`, refuses under prod settings.
  - `tools/perf_check.py`: timed requests on key pages (p50/p95/max) plus a 50/100-concurrent-user
    burst, against `seed_load_test` data — results in `docs/PERFORMANCE.md` (every page under the
    2s non-functional requirement, including a worst-case 450-student class).
  - `tools/accessibility_audit.py`: axe-core via Playwright, 35 page/modal visits across all four
    roles — 0 violations after fixing a project-wide color-contrast issue and several
    unlabeled-control issues (`docs/ACCESSIBILITY.md`).
  - `docs/UAT_QUESTIONNAIRE.md` (+ `docs/uat/`): ISO/IEC 25010:2011 Likert (1–5) questionnaire,
    three versions — Students (5 end-user characteristics), Instructors/Program Heads/Admin (the
    same 5 for their workflows), IT Experts (all 8, including Maintainability/Portability/
    Compatibility). `tools/generate_uat_docs.py` emits a `.docx`/`.csv` twin of each from one
    item-bank definition.
  - `tools/uat_analysis.py`: reads a response CSV, outputs per-item and per-characteristic weighted
    mean, SD, percentage distribution, interpretation (4.21–5.00 Excellent, 3.41–4.20 Very Good,
    2.61–3.40 Good, 1.81–2.60 Fair, 1.00–1.80 Poor), and one-way ANOVA between respondent groups
    (scipy) — an `.xlsx` workbook + Markdown summary, with a sample response CSV and a test suite
    (`tools/test_uat_analysis.py`).
  - Final `docs/` set: `docs/ERD.md`/`DATA_DICTIONARY.md` generated from the Django models
    (`tools/generate_erd.py`), `docs/diagrams/` (architecture, context + level-1 DFD, one use-case
    diagram per role), a user manual per role with real screenshots from seeded demo data
    (`tools/generate_user_manuals.py`, `docs/manuals/`), `docs/CHANGES_FROM_PROPOSAL.md` (every
    deviation from the approved proposal, cited section-by-section), `docs/DEFENSE_DEMO_SCRIPT.md`,
    and the pre-existing `docs/DEPLOYMENT.md`. See `README.md`'s "Documentation" section for the
    full index.
- **Post-completion enhancements (not a numbered phase, done):** 6 items from a system-flow
  review, each its own commit — (1) Admin: Import Class Offerings + copy classes from a previous
  semester, (2) Admin: New Academic Year wizard with student promotion, (3) INC completion workflow
  (instructor files → Program Head approves/rejects, reusing `correct_grade`), (4) a per-semester
  grade submission deadline + late flag + `send_reminders`, (5) the instructor to-do dashboard, (6)
  Django Admin hidden from every sidebar and hardened to superuser-only with a configurable prod
  URL. See the dated note at the top of this file for the full list and the judgment calls made
  along the way (new `StudentProfile.status`/`IncCompletion`/deadline fields, all confirmed with
  the user before building).
- **Program Head scope redesign (not a numbered phase, done):** day-to-day academic setup moved
  from Admin to each program's Program Head, scoped via the new `academics.scoping.scope_for`
  helper (program-level or major-level assignment) — Sections, Subjects (shared catalog, scope-
  restricted editing), Classes (including shared-class join/leave with auto-deactivation), Class
  Lists, and Import Class Offerings all gained scoped Program-Head pages under a new "My Program"
  sidebar group; Admin keeps the same five pages (plus Teaching Loads) as an audited "Override"
  group (`academics.AcademicSetupChangeLog`, combined into the Audit Log page as a new
  `academic_setup` source); the Program Head dashboard's placeholder stat cards became a linked
  setup checklist. Also fixed along the way: a pre-existing query-count regression in
  `forecasting`'s Program Head At-Risk page (`scope_for` was being recomputed 3x per request —
  fixed by memoizing it on the user instance). See the dated note at the top of this file and
  section 3b for the full rule set and the judgment calls made along the way (shared
  `AcademicSetupChangeLog` model rather than three per-domain ones, hand-written Program-Head
  views rather than a new `core.crud` scoping hook, auto-deactivating a shared class on its last
  section leaving — all confirmed with the user before building).
- **Curriculum mapping, prospectus Subjects page, real CITCI curriculum (not a numbered phase,
  done):** new `academics.CurriculumEntry` model replaces `Subject.program`/`major`/`year_level`/
  `term` (three migrations: add the model, copy existing placement data into it, then drop the old
  fields) so one subject code can sit in several programs'/majors' curricula at once. Both the
  Program Head and Admin Subjects pages were rebuilt as one shared prospectus-style view
  (`academics.views.subjects_home`) — year-level cards with 1st/2nd Sem sub-tables, a major-filter
  segmented control (Program Head, scoped) or a program/major selector (Admin, everything), a
  "Shared" badge, and a two-path Add-Subject modal (attach an existing subject, or create a new
  one). `academics.scoping.subjects_editable_by` now checks every one of a subject's
  `CurriculumEntry` rows, not a field on `Subject` — implemented as a count comparison after a real
  Django ORM bug surfaced (negating a `Q()` with multiple conditions on a to-many relation lets
  different rows each satisfy one condition). The Class-creation subject picker
  (`academics.forms._grouped_subject_choices`) suggests curriculum-matched subjects first.

  A new `load_citci_curriculum` management command loads CITCI's real curriculum from
  `docs/source/all_subject_per_major.docx` — it turned out to be the exact same table shape
  `import_offerings_docx.py` already parses, so it reuses `parse_docx` directly rather than writing
  a second parser, ignoring the instructor/room/schedule columns per the task's own instruction.
  Run against the dev database: see the summary counts and the exact `DATA_ISSUES.md` findings
  (duplicate-code conflicts resolved BSED-wins, near-duplicate codes flagged but never auto-merged,
  the PATHFit 1–3-vs-4 unit-count oddity) reported to the user when this landed.

  **Same-day follow-up:** the Subjects pages gained a Semester + Year Level segmented filter
  alongside the major pills (all three — program/major, term, year_level — persisted in the URL),
  pills switched to one-per-major (no program-level pill once a program has majors), and the
  Class-creation subject suggestion got the live htmx re-grouping the first pass had deliberately
  deferred (`academics.views._wire_live_subject_regroup`). `load_citci_curriculum`'s program/major
  resolution also now matches by code OR name, case-insensitive.

---

## 11. Rules for You (Claude Code)

- Follow Django conventions: thin views, business logic in app-level services once real logic
  exists (e.g. `GradeComputationService`, `GwaService`, `ForecastClient`), Django Forms for
  validation.
- Never hardcode grading weights or the transmutation scale — they're DB-backed config once that
  phase is built.
- Never store or log a name or real student/ID number in `forecasting.HistoricalRecord` or anywhere
  else in the ML training pipeline — mask with `SHA256(app secret salt + identifier)` first, always.
- **The model shown in the final defense and Chapter 4 must be trained and evaluated on real,
  masked CITCI historical data (or a MIXED set only if clearly reported).** Synthetic data is for
  development and demo only and must always be labeled as such in the UI and reports (see section
  7's Chapter 4 rule) — never present a SYNTHETIC-trained model's numbers as the real result.
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
- Django Admin is superuser-only (`config/admin.py`'s `SuperuserOnlyAdminSite`, not the sidebar) —
  a new model registration must use `@admin.register(Model, site=site)` with `site` imported from
  `config.admin`, never the bare `@admin.register(Model)` decorator (which binds to the default,
  unrestricted `django.contrib.admin.site`).
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
