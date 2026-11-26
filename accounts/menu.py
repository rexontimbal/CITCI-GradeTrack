"""Sidebar menu definitions, one list of groups per role.

Each item: (url_name, label, icon_key). Icon keys are looked up in the
`sidebar_icon` template tag (templates/partials/_sidebar.html) against a
small inline-SVG library — see accounts/templatetags/sidebar_icons.py.
"""

from .models import User

MENUS = {
    User.Role.ADMIN: [
        {
            "label": "Main",
            "items": [
                ("dashboard:home", "Dashboard", "home"),
            ],
        },
        {
            "label": "Academic Setup",
            "items": [
                ("academics:terms", "Academic Years & Semesters", "calendar"),
                ("academics:programs", "Programs", "folder"),
                ("academics:majors", "Majors", "folder"),
                ("academics:rooms", "Rooms", "grid"),
                ("academics:subject_catalog", "Subject Catalog", "book"),
            ],
        },
        {
            "label": "Override",
            "items": [
                ("academics:sections", "Sections", "grid"),
                ("academics:subjects", "Subjects", "book"),
                ("academics:classes", "Classes", "chalkboard"),
                ("academics:teaching_loads", "Teaching Loads", "chart"),
            ],
        },
        {
            "label": "Management",
            "items": [
                ("accounts:users", "Users", "users"),
                ("grading:templates", "Grading Templates", "sliders"),
                ("approvals:admin_sheets", "Grade Sheets", "clipboard"),
                ("forecasting:model", "Forecast Model", "chart"),
                ("forecasting:historical", "Historical Data", "folder"),
            ],
        },
        {
            "label": "Reports",
            "items": [
                ("reports:index", "Reports", "document"),
            ],
        },
        {
            "label": "System",
            "items": [
                ("reports:settings", "Settings", "settings"),
                ("accounts:audit_log", "Audit Log", "document"),
            ],
        },
    ],
    User.Role.PROGRAM_HEAD: [
        {
            "label": "Main",
            "items": [
                ("dashboard:home", "Dashboard", "home"),
            ],
        },
        {
            "label": "My Program",
            "items": [
                ("academics:ph_sections", "Sections", "grid"),
                ("academics:ph_subjects", "Subjects", "book"),
                ("academics:program_head_classes", "Classes", "chalkboard"),
                ("academics:teaching_loads", "Teaching Loads", "chart"),
            ],
        },
        {
            "label": "Grades",
            "items": [
                ("approvals:index", "Grade Approvals", "check-circle"),
                ("forecasting:at_risk", "At-Risk Students", "alert"),
            ],
        },
        {
            "label": "Reports",
            "items": [
                ("reports:index", "Reports", "document"),
            ],
        },
    ],
    User.Role.INSTRUCTOR: [
        {
            "label": "Main",
            "items": [
                ("dashboard:home", "Dashboard", "home"),
            ],
        },
        {
            "label": "Teaching",
            "items": [
                ("academics:my_classes", "My Classes", "chalkboard"),
                ("approvals:submitted", "Submitted Grades", "clipboard"),
                ("approvals:inc_completions_list", "INC to Complete", "document"),
                ("forecasting:at_risk", "At-Risk Students", "alert"),
            ],
        },
        {
            "label": "Reports",
            "items": [
                ("reports:index", "Reports", "document"),
            ],
        },
    ],
    User.Role.STUDENT: [
        {
            "label": "Main",
            "items": [
                ("dashboard:home", "Dashboard", "home"),
            ],
        },
        {
            "label": "Academics",
            "items": [
                ("academics:student_my_classes", "My Classes", "chalkboard"),
                ("grading:my_grades", "My Grades", "book"),
                ("grading:my_progress", "My Progress", "chart"),
            ],
        },
        {
            "label": "Others",
            "items": [
                ("dashboard:notifications", "Notifications", "bell"),
            ],
        },
    ],
}


def menu_for(user):
    return MENUS.get(user.role, [])


# Curated, mobile-only bottom navigation -- a quick-access supplement to the
# full sidebar menu above, not a replacement (see templates/partials/
# _bottom_nav.html). Each role gets exactly 2 left + 1 raised center +
# 2 right items, same (url_name, label, icon_key) shape as MENUS.
BOTTOM_NAV = {
    User.Role.ADMIN: {
        "left": [
            ("dashboard:home", "Dashboard", "home"),
            ("accounts:users", "Users", "users"),
        ],
        "center": ("approvals:admin_sheets", "Grade Sheets", "clipboard"),
        "right": [
            ("reports:index", "Reports", "document"),
            ("reports:settings", "Settings", "settings"),
        ],
    },
    User.Role.PROGRAM_HEAD: {
        "left": [
            ("dashboard:home", "Dashboard", "home"),
            ("academics:program_head_classes", "Classes", "chalkboard"),
        ],
        "center": ("approvals:index", "Grade Approvals", "check-circle"),
        "right": [
            ("forecasting:at_risk", "At-Risk Students", "alert"),
            ("reports:index", "Reports", "document"),
        ],
    },
    User.Role.INSTRUCTOR: {
        "left": [
            ("dashboard:home", "Dashboard", "home"),
            ("academics:my_classes", "My Classes", "chalkboard"),
        ],
        "center": ("approvals:submitted", "Submitted Grades", "clipboard"),
        "right": [
            ("forecasting:at_risk", "At-Risk Students", "alert"),
            ("reports:index", "Reports", "document"),
        ],
    },
    User.Role.STUDENT: {
        "left": [
            ("dashboard:home", "Dashboard", "home"),
            ("academics:student_my_classes", "My Classes", "chalkboard"),
        ],
        "center": ("academics:student_my_classes", "Join Class", "qr"),
        "right": [
            ("grading:my_grades", "My Grades", "book"),
            ("dashboard:notifications", "Notifications", "bell"),
        ],
    },
}


def bottom_nav_for(user):
    return BOTTOM_NAV.get(user.role)
