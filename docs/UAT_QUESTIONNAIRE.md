# User Acceptance Testing (UAT) Questionnaire — CITCI GradeTrack

## Quality model version

This questionnaire is built on **ISO/IEC 25010:2011** (Systems and software Quality Requirements
and Evaluation — SQuaRE, the 2011 edition, 8 quality characteristics). ISO/IEC 25010:2023 is a
later revision with largely the same structure; 2011 is used here because it matches the approved
proposal and remains common local (Philippine capstone) practice. Switching to the 2023 edition
later is a one-line change to this heading and the characteristic list in `tools/uat_analysis.py`
— no item renumbering needed, since every item below is coded by characteristic, not by edition.

## How this questionnaire is organized

Three respondent-scoped versions, each a subset of the same item bank (so results are comparable
across versions for any shared characteristic):

1. **Students** — Functional Suitability, Performance Efficiency, Usability, Reliability, Security
   (student-facing pages only: dashboard, My Grades, Subject detail, My Progress, notifications).
2. **Instructors / Program Heads / Admin** — the same five end-user characteristics, worded around
   their own workflows (encoding, approvals, reports, forecasts, teaching-load assignment).
3. **IT experts** (technical evaluators) — all eight characteristics, including the three a
   typical end user can't meaningfully judge: Maintainability, Portability, Compatibility.

Each item uses a **5-point Likert scale**: 1 = Strongly Disagree, 2 = Disagree, 3 = Neutral,
4 = Agree, 5 = Strongly Agree. Item codes (e.g. `FS1`) are the column headers `tools/uat_analysis.py`
expects in a response CSV — see `docs/uat/sample_responses.csv`.

Machine-readable twins of each version live in `docs/uat/`:
`UAT_Students.csv` / `.docx`, `UAT_Staff.csv` / `.docx`, `UAT_ITExperts.csv` / `.docx` — the `.csv`
files are formatted for a straight import into Google Forms (one row per item: code, text, scale);
the `.docx` files are print-ready.

---

## Respondent information (every version)

- Role: ☐ Student ☐ Instructor ☐ Program Head ☐ Admin ☐ IT Expert / Technical Evaluator
- For students: Year level: ☐ 1st ☐ 2nd ☐ 3rd ☐ 4th
- For instructors/program heads/admin: Years of teaching/administrative experience: ______
- For IT experts: Years of software development/QA experience: ______
- Date: ______

*No names or ID numbers are collected on this form.*

## Informed consent (RA 10173 — Data Privacy Act of 2012)

> You are invited to evaluate CITCI GradeTrack, a grading management system with academic
> performance forecasting developed as a capstone project for the College Department of Candelaria
> Institute of Technology in Cabadbaran Inc. Your responses are **anonymous** — no name, ID number,
> or other directly-identifying information is collected on this form, and responses are used
> **only** for this study's evaluation of the system's quality. Participation is voluntary; you may
> skip any item or stop at any time without consequence. By proceeding, you acknowledge that you
> understand this and consent to your anonymous responses being used for this evaluation, in
> accordance with the Data Privacy Act of 2012 (RA 10173).
>
> ☐ I have read and understood the above, and I consent to participate.

---

## Verbal interpretation bands (used by `tools/uat_analysis.py`)

| Weighted mean range | Interpretation |
|---|---|
| 4.21 – 5.00 | Excellent |
| 3.41 – 4.20 | Very Good |
| 2.61 – 3.40 | Good |
| 1.81 – 2.60 | Fair |
| 1.00 – 1.80 | Poor |

---

## Version 1 — Students

**Functional Suitability (FS)**
- FS1. I can find my grades, GWA, and progress on the system without confusion.
- FS2. The grades and GWA I see match what I expect from my actual scores.
- FS3. The system clearly tells me whether a grade is official (released) or still unofficial
  (running).
- FS4. The forecast message I see (e.g. "needs your attention" / "on track") is helpful without
  being confusing or alarming.

**Performance Efficiency (PE)**
- PE1. Pages (dashboard, My Grades, Subject detail, My Progress) load quickly.
- PE2. The system responds quickly when I switch semesters or open a subject's detail page.
- PE3. I did not experience noticeable slowdowns or freezing while using the system.

**Usability (US)**
- US1. The system is easy to navigate without needing help.
- US2. Menu items and page titles are clear and make sense to me.
- US3. The system works well on my phone/tablet, not just a desktop computer.
- US4. Charts and progress visuals are easy to understand.

**Reliability (REL)**
- REL1. The system is available whenever I need to check my grades.
- REL2. I have not encountered error pages or broken pages while using the system.
- REL3. My data (grades, progress) is consistent every time I log in — nothing seems to randomly
  change or disappear.

**Security (SEC)**
- SEC1. I feel confident that only I can see my own grades.
- SEC2. The login process (password, lockout after failed attempts) feels secure.
- SEC3. I was asked to agree to a Data Privacy notice before using the system.

---

## Version 2 — Instructors / Program Heads / Admin

**Functional Suitability (FS)**
- FS1. The system lets me complete my actual tasks (encoding scores / approving grade sheets /
  managing accounts and academic setup) without needing a workaround.
- FS2. Computed grades (component grades, final grades, GWA) match what I expect from the formulas.
- FS3. The grade sheet submit/approve/release workflow matches how our department actually works.
- FS4. The at-risk/forecast information is specific enough to act on (which students, which
  class, why).

**Performance Efficiency (PE)**
- PE1. Pages I use often (Class Record, dashboards, Approvals, Reports, Teaching Loads) load
  quickly, even for a large class.
- PE2. Saving a score or submitting a grade sheet responds quickly, without a noticeable delay.
- PE3. Generating a PDF or Excel report does not take an unreasonable amount of time.

**Usability (US)**
- US1. The system is easy to learn without extensive training.
- US2. The Class Record grid (encoding scores) is easy to use, including keyboard navigation.
- US3. It's clear what to do next at each step of the grade-sheet workflow (draft, submit, return,
  approve, release).
- US4. Error messages (e.g. a blocked instructor change, a missing score) clearly explain what's
  wrong and what to do about it.

**Reliability (REL)**
- REL1. The system is available when I need it, including during peak periods (e.g. grading
  deadlines).
- REL2. I have not lost work (unsaved scores, an in-progress form) due to a system error.
- REL3. Once grades are released or locked, they stay consistent — I trust the official record.

**Security (SEC)**
- SEC1. I can only see and act on classes/students that are actually assigned to me or my
  program.
- SEC2. Sensitive actions (grade correction, instructor override, account changes) are logged in a
  way I trust.
- SEC3. The account lockout/password-change requirements feel appropriately secure, not excessive.

---

## Version 3 — IT Experts / Technical Evaluators

*(All eight characteristics. Evaluators should have reviewed the codebase, architecture, and
deployment docs, not just clicked through the UI.)*

**Functional Suitability (FS)**
- FS1. The implemented features match the documented requirements/proposal scope.
- FS2. Core computations (grading formula, GWA, forecasting features/label) are correctly and
  verifiably implemented (e.g. the hand-verified test cases in `grading/tests.py`).
- FS3. No functionality is missing that a grading-and-forecasting system of this scope should have.

**Performance Efficiency (PE)**
- PE1. Database queries are reasonably optimized (no obvious N+1 patterns) for the heaviest pages.
- PE2. Response times stay well under 2 seconds under realistic data volume (see
  `docs/PERFORMANCE.md`).
- PE3. Resource usage (DB connections, memory) is reasonable for the deployment target.

**Compatibility (COMP)**
- COMP1. The system runs correctly across modern browsers (Chrome, Firefox, Edge).
- COMP2. The system does not conflict with other services on the same deployment (e.g. shares a
  Postgres instance safely, doesn't hard-code ports/paths that would collide).
- COMP3. Data interchange (Excel import/export, PDF generation) is correct and round-trips cleanly.

**Usability (US)**
- US1. The UI follows consistent, predictable patterns across pages (shared CRUD, shared modal,
  shared table conventions).
- US2. Accessibility basics (labels, contrast, keyboard navigation, landmark roles) are present —
  see `docs/ACCESSIBILITY.md`.
- US3. The information architecture (sidebar, role-based menus) is logical for each role.

**Reliability (REL)**
- REL1. The test suite is comprehensive and the measured coverage (see `docs/TEST_REPORT.md`) is
  adequate for the code's risk level.
- REL2. Error handling is graceful — a failure in one subsystem (e.g. forecasting) does not break
  unrelated pages (confirmed in code: forecasting failures are caught and logged, never raised).
- REL3. The backup/restore tooling (`backup_db`/`restore_db`) is correct and usable.

**Security (SEC)**
- SEC1. Authentication and session handling (password hashing, lockout, session expiry) follow
  reasonable security practice.
- SEC2. Authorization is enforced server-side, not just hidden in the UI (role-based + object-level
  checks).
- SEC3. Sensitive data (passwords, personal data used in forecasting) is handled appropriately
  (masked identifiers, no plaintext secrets in logs).
- SEC4. Production settings (`config/settings/prod.py`) enforce secure defaults (HTTPS gating,
  secret key validation, security headers).

**Maintainability (MAIN)**
- MAIN1. The codebase is modular (clear app boundaries: accounts, academics, grading, approvals,
  forecasting, reports, dashboard, core) with minimal unnecessary coupling.
- MAIN2. Business logic lives in testable service functions, not scattered across views/templates.
- MAIN3. The code and `CLAUDE.md` documentation are sufficient for a new developer to understand
  and extend the system.
- MAIN4. The test suite would catch a regression if a future change broke existing behavior.

**Portability (PORT)**
- PORT1. The application can be deployed to a different environment (Ubuntu/Gunicorn/Nginx **or**
  Windows/Waitress/NSSM) using the documented steps (`docs/DEPLOYMENT.md`) without code changes.
- PORT2. Configuration (secrets, hosts, feature flags) is externalized via environment variables,
  not hard-coded.
- PORT3. The system has no unnecessary dependency on a specific OS or hosting provider.

---

## Scoring

See `tools/uat_analysis.py` for the full computation. Summary: each item's **weighted mean** and
**standard deviation** are computed per respondent group, rolled up into a per-characteristic
weighted mean (average of its items' means), given a verbal interpretation from the band table
above, and compared across groups (Student / Staff / IT Expert) with a one-way ANOVA per shared
characteristic (α = 0.05).
