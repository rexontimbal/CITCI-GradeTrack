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
                ("academics:sections", "Sections", "grid"),
                ("academics:subjects", "Subjects", "book"),
                ("academics:classes", "Classes", "chalkboard"),
                ("academics:class_lists", "Class Lists", "clipboard"),
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
                ("admin:index", "Django Admin", "settings"),
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
            "label": "Academics",
            "items": [
                ("academics:program_head_classes", "Classes", "chalkboard"),
                ("academics:teaching_loads", "Teaching Loads", "chart"),
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
