"""Per-role Help page content -- plain data, no Django imports, so this
can be shared by both the in-app Help page (accounts.views.help_page) and
the standalone Playwright screenshot script (tools/generate_user_manuals.py)
without either one needing Django's app registry set up first.

Each step: (step title, plain-language instruction, path). A path with no
"{...}" placeholder is rendered as a clickable "Go there" link on the Help
page; one with a placeholder (e.g. a specific class/roster-entry id) is
shown as reference text only, since there's no single right id to link to
generically.
"""

HELP_CONTENT = {
    "admin": {
        "title": "Admin Guide",
        "steps": [
            (
                "Managing users",
                "Users: tabs for Admins/Program Heads/Instructors/Students, with search and "
                "filters. Use 'Add' to create an account, or the bulk import for students/"
                "instructors from a spreadsheet.",
                "/accounts/users/",
            ),
            (
                "Managing classes",
                "Academic Setup / Override: Classes lists every class offering for the active "
                "semester, with filters by program/semester/instructor.",
                "/academics/classes/",
            ),
            (
                "Teaching Loads",
                "Shows per-instructor totals (classes, units, students) for the active semester, "
                "plus any unassigned classes. You can override an instructor assignment from the "
                "Classes page -- it's logged as an admin override.",
                "/academics/teaching-loads/",
            ),
            (
                "Grading templates",
                "Management: the CITCI Default template and its components, including the "
                "school-locked Examination weight.",
                "/grading/templates/",
            ),
            (
                "Grade Sheets oversight",
                "Every grade sheet in the active semester with a submission/approval/release "
                "progress summary, and a 'Lock Term' action.",
                "/approvals/admin/sheets/",
            ),
            (
                "Forecast Model",
                "Metrics (accuracy/precision/recall/F1/ROC-AUC), the threshold trade-off table, "
                "and version history with an Activate action.",
                "/forecasting/model/",
            ),
            (
                "Reports",
                "System-wide submission status, class performance, and failing/INC lists, each "
                "exportable to Excel.",
                "/reports/",
            ),
            (
                "Audit Log",
                "Every account change, grade correction, and teaching-load/academic-setup "
                "override, in one filterable, exportable page.",
                "/accounts/audit-log/",
            ),
        ],
    },
    "program_head": {
        "title": "Program Head Guide",
        "steps": [
            (
                "Dashboard",
                "At-risk student counts and an 'Unassigned Classes' card for your program(s), "
                "linking straight to the filtered list.",
                "/dashboard/",
            ),
            (
                "Assigning teaching loads",
                "Classes shows every class under your program(s). Use 'Assign/Change Instructor' "
                "per class, the 'Unassigned only' filter, and the bulk-assign action for several "
                "classes at once.",
                "/academics/program-head/classes/",
            ),
            (
                "Subjects",
                "Your program's prospectus, grouped by year level with 1st/2nd Sem sub-tables. "
                "'Add Subject' can attach an existing catalog subject or create a new one; a "
                "'Shared' subject (used by another program/major too) can only be edited by Admin.",
                "/academics/my-program/subjects/",
            ),
            (
                "Grade Approvals",
                "Review a submitted grade sheet's frozen snapshot, class distribution chart, and "
                "transition timeline, then Approve, Return (with remarks), or Release.",
                "/approvals/",
            ),
            (
                "At-Risk Students",
                "Summary cards (at risk/watch/classes affected/interventions), a by-class "
                "breakdown, and the same student-level detail instructors see.",
                "/forecasting/at-risk/",
            ),
        ],
    },
    "instructor": {
        "title": "Instructor Guide",
        "steps": [
            (
                "My Classes",
                "Every class assigned to you for the active semester. Click 'Encode Grades' to "
                "open a class's grading page.",
                "/academics/my-classes/",
            ),
            (
                "Setup tab -- grading components",
                "Add/rename/reweight your own (unlocked) grading components; the school-locked "
                "Examination weight is shown read-only. Scroll down for assessment items.",
                None,
            ),
            (
                "Encoding scores",
                "The Class Record tab is a spreadsheet-style grid -- click a cell to type a "
                "score, Tab/Enter/arrow keys to move between cells, autosave on blur.",
                None,
            ),
            (
                "Submitting grades",
                "Once every active student has a score, 'Submit Grades' opens a review (counts, "
                "class average, missing/INC list) before locking the sheet for the Program "
                "Head's review.",
                None,
            ),
            (
                "Submitted Grades",
                "Your own grade sheets across the active semester, filterable by status.",
                "/approvals/submitted/",
            ),
            (
                "At-Risk Students",
                "Students flagged at-risk or watch across your classes, with plain-language "
                "reasons and an intervention log.",
                "/forecasting/at-risk/",
            ),
            (
                "Reports",
                "Per-class PDF/Excel grade-sheet exports.",
                "/reports/",
            ),
        ],
    },
    "student": {
        "title": "Student Guide",
        "steps": [
            (
                "Dashboard",
                "Your subjects this term, Official/Partial GWA, and a supportive forecast card "
                "(never a number, never the words 'at risk') when enabled.",
                "/dashboard/",
            ),
            (
                "Joining a class",
                "My Classes: use 'Join class' to enter a 7-character code or scan the QR your "
                "instructor shares. Your instructor still approves the request before it shows "
                "up on your class list.",
                "/academics/my-classes/student/",
            ),
            (
                "My Grades",
                "A semester selector, your grades per subject, and total units + GWA -- official "
                "once released, clearly marked 'Unofficial' before that.",
                "/grading/my-grades/",
            ),
            (
                "My Progress",
                "A GWA-history line chart across every semester, plus the current semester's "
                "subjects by grade.",
                "/grading/my-progress/",
            ),
            (
                "Notifications",
                "Submission/return/release updates and forecast alerts land here, with an unread "
                "badge on the bell icon.",
                "/dashboard/notifications/",
            ),
        ],
    },
}
