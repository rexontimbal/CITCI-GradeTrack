# Changes From the Approved Proposal

Every difference below is cited against the approved capstone proposal
(`CITCI-GradeTrack_Grading-System-and-Student-Peformance-Forecasting (2).pdf`, 32 pages) with its
section/figure, the reason for the change, and which proposal section needs revising for the final
paper. Nothing here is a silent deviation — each one is also narrated, as it happened, in the dated
notes at the top of `CLAUDE.md`.

---

## 1. Tech stack: PHP/Laravel/MySQL → Django/PostgreSQL

**Proposal:** Backend "PHP with the Laravel framework"; database "MySQL, a relational database
management system" (§2.18 Technical Background); Software Requirements lists "Backend: PHP 8.x
with Laravel Framework", "Database: MySQL 8.x" (§3.7); System Architecture Figure 5's Application
Tier is "Laravel Backend" over a "MySQL Database" Data Tier.

**Built:** Python 3.12 / Django 5.2 LTS, PostgreSQL via psycopg 3.

**Reason:** Confirmed with the user before any code was written (`CLAUDE.md`'s 2026-10-25 dated
note) — Django's batteries-included ORM/admin/forms/auth and PostgreSQL's stronger
constraint/JSON support suited the grading + forecasting domain better than the originally
proposed stack, with no functional requirement depending on PHP/MySQL specifically.

**Revise:** §2.18 Technical Background, §3.6/§3.7 Hardware/Software Requirements, Figure 5 System
Architecture (tier labels).

---

## 2. Forecasting: separate Python "AI service" → in-process Django app

**Proposal:** "The overall system follows a client-server architecture where the web application
serves as the main platform for grade management, while the Python-based analytics module
functions as a separate service for academic performance forecasting" — exposed "as an API that
communicates with the Laravel backend through HTTP requests" (§2.18); Figure 5 draws a distinct
"3. AI & Analytics Tier (Python Service)" with its own "Prediction API" box, "Recommendation
Engine" box, and a "Send Data / Receive Prediction Results" link to the Application Tier.

**Built:** `forecasting/ml/` is a plain Python package imported directly by Django views/commands —
same process, same deploy. No FastAPI, no `/ml-service`, no network hop, no API key, no
"Recommendation Engine" (replaced by static, non-AI `STUDENT_STUDY_TIPS` — see item 6).

**Reason:** At CITCI's data scale (one department, hundreds of students) a same-process module does
the same job as a separate service with none of the deployment/availability complexity — Django
can't "lose connectivity" to code running in its own process. Decided before the forecasting phase
was built (`CLAUDE.md`'s rewritten Tech Stack section and its 2026-11-04 dated note).

**Revise:** §2.18 (last two paragraphs), §3.8 System Models and Architecture narrative, Figure 5
(collapse tiers 2–3 into one Application Tier; drop the Prediction API/Recommendation Engine boxes
and the inter-tier HTTP arrow).

---

## 3. LMS features removed — this is a grading system, not a learning management system

**Proposal:** Functional Requirements: "Enable students to access learning materials, submit
assignments, and take quizzes" (§3.4). Operational Framework: "Course and material management.
Instructors upload course materials, create assignments, and configure quizzes…" and "Student
access. Students view materials, submit assignments, and take quizzes for the subjects in which
they are enrolled" (§3.12). Sprint 3 ("Assessment and Grading Module"): "Development of quiz
creation, assignment submission, and automated grading for objective assessments" (§3.11).

**Built:** None of this exists. CITCI GradeTrack never stores course materials, never accepts a
student assignment submission, and has no quiz-taking flow — scores are *entered by the instructor*
from assessments conducted outside the system (paper exams, recitation, etc.), not submitted
in-app by students.

**Reason:** The approved objectives (O1–O5, §1.4 of this project — the proposal's own General/
Specific Objectives) are about grading automation, GWA computation, and forecasting — not content
delivery. Building LMS features would have doubled the scope without serving any stated objective.
Scoped out explicitly and permanently (`CLAUDE.md`: *"This is a grading management system, NOT a
full LMS. Do not build course-material uploads, student assignment submission, online quizzes, or
login-activity tracking."*).

**Revise:** §3.4 (drop the materials/assignments/quizzes bullet), §3.11 Sprint 3 (retitle to just
"Grading Module" — assessment *items* and score encoding, not quiz-taking), §3.12 (drop "Course and
material management" and "Student access" bullets, replace with the actual encode/view flow).

---

## 4. Enrollment → class lists (Registrar's process is out of scope)

**Proposal:** ERD Figure 3 has an `enrollments` table (`student_id`, `subject_id`, `instructor_id`)
as a first-class entity the system manages.

**Built:** `academics.ClassRosterEntry` — deliberately never called "enrollment" anywhere in code,
UI copy, or model names. GradeTrack does not handle student enrollment; that is the Registrar's own
process, entirely outside this system. GradeTrack only stores each class's *official student list*
(imported from the Registrar or managed by hand) so instructors have someone to encode grades for.

**Reason:** Enrollment (adding/dropping a course, prerequisite checks, section capacity) was never
one of the approved objectives — conflating it with "who's on this class's roster for grading
purposes" would have pulled in Registrar-system scope the proposal never budgeted for.

**Revise:** Figure 3 ERD (rename `enrollments` → `class_roster_entries`, drop any enrollment-
specific fields not needed for a roster), any remaining "enrollment" wording in Chapter 1/3.

---

## 5. A fourth role: Program Head, and the grade-sheet approval workflow

**Proposal:** Three roles throughout — Student, Instructor, Admin (Figure 5's Client Tier is exactly
these three boxes; §1.4's target beneficiaries list Students / Teachers-Instructors / Academic
Administrators-Department Heads as a single undifferentiated "admin" audience). No
submit/approve/release workflow is described anywhere — grades appear to go straight from
instructor encoding to student visibility.

**Built:** A fourth role, **Program Head**, confirmed as CITCI's actual departmental structure — and
an entire `approvals` app implementing
`draft → submitted → approved → released → locked` (+ `returned`), where the Program Head
specifically reviews and approves/returns a class's grades before a student ever sees them as
official. Later (2026-11-05), Program Heads were also given ownership of **teaching-load
assignment** — deciding which instructor teaches each of their program's classes — with Admin
keeping that ability too, but only as a logged "admin override" (see `CLAUDE.md` §3a).

**Reason:** Confirmed with CITCI during development that grades go through a departmental approval
step before release, and that assigning who teaches a class is normally the Program Head's
call, not Admin's — neither matches the proposal's flat three-role model.

**Revise:** §1.4 Target Beneficiaries (split "Academic Administrators/Department Heads" into Admin
vs. Program Head with distinct responsibilities), Figure 5 Client Tier (add a fourth box), add a
grade-sheet-workflow subsection to Chapter 3 (none currently exists), and a teaching-load-assignment
subsection alongside it.

---

## 6. Forecasting features, label rule, and threshold

**Proposal (§3.9.1):** Features are "quiz score average (x₁), submission timeliness rate (x₂), login
frequency over the past two weeks (x₃), and assignment completion rate (x₄)"; threshold is a fixed
"0.7"; an undefined "Recommendation Engine" (Figure 5) implies AI-generated study suggestions.

**Built:** Features are keyed off `grading.ComponentCategory` at a **checkpoint** (Prelim/Midterm),
never off name: `quiz_pct`, `recitation_pct`, `project_pct` (merged with Other), `attendance_pct`,
`exam_pct`, `running_grade`, `missing_rate_pct` — none of the proposal's four features exist in the
built system (there is no login-frequency or submission-timeliness signal at all — CITCI GradeTrack
has no login-activity tracking or assignment-submission feature to source them from, see item 3).
Label: FINAL grade > 3.00, or INC, or DROPPED (not the proposal's unspecified "at risk of failing").
Threshold: default **0.5**, admin-adjustable with a precision/recall trade-off table (0.3–0.7) shown
on the Model Performance page — not a fixed 0.7. "Recommendations" are three **static, generic**
study tips (`STUDENT_STUDY_TIPS` in `forecasting/services.py`), never AI-generated, and the student
never sees a number or the words "at risk" at all (see `CLAUDE.md` §5/§7).

**Reason:** The proposal's features assume LMS-style activity logs (login frequency, submission
timeliness) that don't exist once LMS scope was cut (item 3) — CITCI GradeTrack's only real signal
is grading data itself, so features were redesigned around the actual `AssessmentItem`/`Score`
tables, grouped by category so a renamed/instructor-invented component still feeds the right
feature. The threshold was made adjustable (not fixed) because recall matters more than precision
for this use case (missing an at-risk student costs more than a false alarm) — a fixed value can't
be tuned per trained model.

**Revise:** §3.9.1 (replace the four `xᵢ` features and the logistic-function example with the
category-based checkpoint features above; state the actual label rule; note the threshold is
adjustable, not fixed 0.7), Figure 5 (drop the Recommendation Engine box).

---

## 7. Grading formula — specified precisely, not a deviation but a clarification

**Proposal:** Only ever describes grade computation generically ("Automated Grade Computation (GWA
Calculation)", §1.3/Figure 1) — no formula is given.

**Built:** Component grade = `5 − 4 × (earned ÷ possible)` (1.00 best, 5.00 worst — **not** a 0–100%
scale); final grade = `Σ(component grade × weight)`; passing = final grade ≤ 3.00. Verified against
CITCI's actual class record (`grading-system.xlsx`) to full Decimal precision — see
`grading/tests.py::DelaCruzFinalGradeTests`, a hand-verified real row.

**Reason:** Not a scope change — the proposal simply never specified the formula. Confirmed against
CITCI's real grading sheet once development reached that phase.

**Revise:** §1.3/Figure 1 could cite the formula explicitly for completeness, though this isn't a
correction of anything the proposal got wrong.

---

## 8. ISO/IEC 25010 edition

**Proposal:** Cites "ISO/IEC 25010 software quality standards" (§3.10, §3.13) without specifying an
edition.

**Built:** `docs/UAT_QUESTIONNAIRE.md` explicitly states **ISO/IEC 25010:2011** (8 characteristics),
with a one-line note that the 2023 revision exists and that 2011 matches common local capstone
practice — a one-line change if a panel asks for the newer edition.

**Reason:** The proposal's silence on edition needed resolving one way; 2011 was chosen as the safer
default. Not a deviation so much as filling a gap the proposal left open.

**Revise:** None required — optionally add "(2011)" to §3.10/§3.13's ISO/IEC 25010 references.

---

## 9. UAT scope: a third "IT Experts" questionnaire added

**Proposal:** "User Acceptance Testing (UAT) is conducted with selected CITCI instructors and
students" (§3.11 Sprint 6); §3.13 repeats "selected CITCI instructors and students" only.

**Built:** Three versions — Students; Instructors/Program Heads/Admin; and a new **IT Experts /
Technical Evaluators** version covering all eight ISO/IEC 25010 characteristics, including the
three (Maintainability, Portability, Compatibility) no end user can meaningfully judge.

**Reason:** Three of the eight characteristics genuinely require a technical evaluator — an
end-user questionnaire alone can't produce a defensible rating for "is the codebase modular" or "can
this be redeployed to a different OS." Added so Chapter 4 can report on all eight characteristics
with a credible source for each, not just the five an end user can answer.

**Revise:** §3.11 Sprint 6 and §3.13 (add the IT-expert evaluator group alongside instructors/
students).

---

## 10. Synthetic data, historical import, and the Chapter 4 rule

**Proposal:** "In the absence of sufficient initial datasets, a synthetic dataset based on
institutional performance patterns is used for initial deployment" (§3.9.1) — a brief mention, no
governance around when synthetic data may or may not appear in the final defense.

**Built:** The same idea, substantially extended: a deterministic synthetic generator (dev/demo
only, always visibly labeled "SYNTHETIC" in the UI and PDF exports whenever the active model isn't
trained on real data), a masked-historical-import pipeline (SHA-256-salted identifiers, names never
stored), a "MIXED" training source, minimum-row/minimum-positive-count guards that refuse to train
HISTORICAL-only below 200 rows / 30 positives, and an explicit rule that **the model shown in the
final defense must be trained on real, masked CITCI data** (or MIXED, clearly reported) — synthetic
numbers may never be presented as the real result.

**Reason:** The proposal's one sentence didn't address data governance for the eventual defense;
this was formalized once the forecasting phase was built, to prevent an easy mistake (demoing with
synthetic numbers and presenting them as real results).

**Revise:** §3.9.1 (add a sentence on the training-source governance rule and the historical-import
masking approach).

---

## 11. Post-completion enhancements (additions, not deviations — the proposal never mentioned these)

Unlike sections 1–10 above, nothing here changes or contradicts a specific proposal section — these
are 6 operational gaps a system-flow review surfaced *after* the system described by the proposal
was already complete (CLAUDE.md's 2026-11-07 dated note), each a standalone follow-up commit:

1. **Admin: Import Class Offerings + copy classes from a previous semester** — a spreadsheet-driven
   bulk way to set up a semester's classes (plus the existing Registrar `.docx` format through the
   same preview), instead of only the one-off `import_offerings_docx`/`seed_citci_academics`
   management-command pair.
2. **Admin: New Academic Year wizard** — a guided UI for what previously required direct database
   work: creating the next academic year/semesters, recreating the section structure, and promoting
   every active student to the next year level (or marking 4th-years/TCP finishers Completed).
3. **INC completion workflow** — lets an instructor resolve an INC grade through a proper
   instructor-files/Program-Head-approves flow (reusing the existing grade-correction mechanism)
   instead of requiring an ad-hoc admin correction every time.
4. **Grade submission deadline + late flag + reminders** — the proposal's grade-sheet workflow
   (§3.x, see section 5 above) had no notion of a deadline at all; this adds one per semester, a
   frozen late/on-time flag per sheet, and an automated reminder.
5. **Instructor to-do dashboard** — replaces the instructor dashboard's original count-only stat
   cards (two of which had shown a placeholder "—" since Phase 1) with an actionable list.
6. **Django Admin hardened** — tightened from "any `is_staff` account" to explicitly superuser-only,
   removed from every sidebar, and given a configurable production URL — closing a gap where the
   built-in admin bypassed the app's own validation and audit-log writes.

**Revise:** None of §1–§3.13 strictly require a revision for these — they're implementation detail
below the proposal's level of abstraction. If the final paper documents the system's full feature
set (e.g. an updated screen inventory or use-case diagram), these 6 items should be added there as
features delivered, not as corrections to anything previously stated.

---

## 12. Program Head scope redesign (addition — the Program Head role itself was already outside the proposal, item 2 above)

Unlike sections 1–10, this is a refinement of a role the proposal never described at all (the
Program Head/Chairperson role and its grade-approval/teaching-load workflows — see CLAUDE.md's
dated note on the fourth role), not a correction to a proposed feature.

**Confirmed CITCI practice (2026-11-09):** day-to-day academic setup — Sections, Subjects,
Classes, Class Lists, Import Class Offerings — moves from Admin to each program's own Program
Head, scoped to their program or major (`academics.scoping.scope_for`). Admin keeps the same five
pages as a full, audited override (a new "Override" sidebar group, banner-marked, logged to a new
`academics.AcademicSetupChangeLog` and the Audit Log page) — the same pattern already established
for teaching-load assignment (item 2's "a fourth role the proposal never described"). A Program
Head can now also be assigned per-major, not only per-program, and two Program Heads can share one
class across programs (join/leave a shared class, auto-deactivating it once its last section
leaves).

**Revise:** None of §1–§3.13 require revision — same reasoning as item 11. If the final paper's
screen inventory/use-case diagram documents the Program Head role at all (it should, per item 2),
it should now show these scoped Program-Head pages and the Admin Override group as part of that
role's description, not as a correction to anything the proposal stated.
