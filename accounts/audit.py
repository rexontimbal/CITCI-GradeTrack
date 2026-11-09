"""Audit log: writing events (`log_audit`) and reading a combined,
filterable view across every change-log table in the system
(`collect_audit_rows`) for the admin Audit Log page. Phase 8 part A."""

from .models import AuditLog


def log_audit(actor, action, target_user=None, **details):
    """Write one AuditLog row. `details` becomes the JSON `details` field —
    keep it to small, non-personal context (role, old/new state), never a
    name/ID number/password. `actor` is None for a system-originated event
    (e.g. an axes lockout, which has no admin actor)."""
    AuditLog.objects.create(
        actor=actor if (actor is not None and getattr(actor, "is_authenticated", True)) else None,
        action=action,
        target_user=target_user,
        details=details,
    )


def _row(timestamp, source, action, actor, target, details):
    return {
        "timestamp": timestamp,
        "source": source,
        "action": action,
        "actor": actor,
        "target": target,
        "details": details,
    }


def collect_audit_rows(date_from=None, date_to=None, user=None, source=None):
    """Combines accounts.AuditLog, grading.ScoreChangeLog,
    grading.SchemeComponentChangeLog, approvals.GradeSheetTransition, and
    approvals.GradeCorrection into one normalized, timestamp-sorted list of
    dicts. Filters: date_from/date_to (date, inclusive), user (a User
    instance — matches actor OR target/affected party), source (one of the
    SOURCES keys below). Pure function — no view/HTTP concerns; the view
    handles pagination."""
    from academics.models import AcademicSetupChangeLog, TeachingAssignmentLog
    from approvals.models import GradeCorrection, GradeSheetTransition
    from grading.models import ScoreChangeLog, SchemeComponentChangeLog

    rows = []

    account_qs = AuditLog.objects.select_related("actor", "target_user")
    if user is not None:
        account_qs = account_qs.filter(models_q_user(user, ["actor", "target_user"]))
    for entry in account_qs:
        rows.append(
            _row(
                entry.created_at,
                "account",
                entry.get_action_display(),
                entry.actor,
                entry.target_user,
                entry.details,
            )
        )

    score_qs = ScoreChangeLog.objects.select_related(
        "changed_by", "score__roster_entry__student", "score__item"
    )
    if user is not None:
        score_qs = score_qs.filter(
            models_q_user(user, ["changed_by", "score__roster_entry__student"])
        )
    for entry in score_qs:
        rows.append(
            _row(
                entry.changed_at,
                "score",
                "Score changed",
                entry.changed_by,
                entry.score.roster_entry.student,
                {
                    "item": str(entry.score.item),
                    "old_value": entry.old_value,
                    "new_value": entry.new_value,
                },
            )
        )

    component_qs = SchemeComponentChangeLog.objects.select_related(
        "changed_by", "scheme__class_offering"
    )
    if user is not None:
        component_qs = component_qs.filter(models_q_user(user, ["changed_by"]))
    for entry in component_qs:
        rows.append(
            _row(
                entry.changed_at,
                "grading_component",
                f"Component {entry.action.lower()}",
                entry.changed_by,
                None,
                {
                    "class": str(entry.scheme.class_offering),
                    "component": entry.component_name,
                    "before": entry.before,
                    "after": entry.after,
                },
            )
        )

    transition_qs = GradeSheetTransition.objects.select_related("actor", "sheet__class_offering")
    if user is not None:
        transition_qs = transition_qs.filter(models_q_user(user, ["actor"]))
    for entry in transition_qs:
        rows.append(
            _row(
                entry.created_at,
                "grade_sheet",
                f"Grade sheet {entry.from_status} → {entry.to_status}",
                entry.actor,
                None,
                {"class": str(entry.sheet.class_offering), "remarks": entry.remarks},
            )
        )

    correction_qs = GradeCorrection.objects.select_related(
        "corrected_by", "entry__roster_entry__student"
    )
    if user is not None:
        correction_qs = correction_qs.filter(
            models_q_user(user, ["corrected_by", "entry__roster_entry__student"])
        )
    for entry in correction_qs:
        rows.append(
            _row(
                entry.created_at,
                "grade_correction",
                "Grade corrected",
                entry.corrected_by,
                entry.entry.roster_entry.student,
                {
                    "old_grade": str(entry.old_grade) if entry.old_grade is not None else None,
                    "new_grade": str(entry.new_grade) if entry.new_grade is not None else None,
                    "reason": entry.reason,
                },
            )
        )

    assignment_qs = TeachingAssignmentLog.objects.select_related(
        "old_instructor", "new_instructor", "changed_by", "class_offering__subject"
    )
    if user is not None:
        assignment_qs = assignment_qs.filter(models_q_user(user, ["changed_by", "old_instructor", "new_instructor"]))
    for entry in assignment_qs:
        rows.append(
            _row(
                entry.created_at,
                "teaching_assignment",
                "Instructor assigned (admin override)" if entry.is_admin_override else "Instructor assigned",
                entry.changed_by,
                entry.new_instructor,
                {
                    "class": str(entry.class_offering),
                    "old_instructor": entry.old_instructor.full_name if entry.old_instructor else None,
                    "new_instructor": entry.new_instructor.full_name if entry.new_instructor else None,
                    "is_admin_override": entry.is_admin_override,
                    "reason": entry.reason,
                },
            )
        )

    setup_qs = AcademicSetupChangeLog.objects.select_related("actor", "program", "major")
    if user is not None:
        setup_qs = setup_qs.filter(models_q_user(user, ["actor"]))
    for entry in setup_qs:
        label = f"{entry.get_model_name_display()} {entry.get_action_display().lower()}"
        if entry.is_admin_override:
            label += " (admin override)"
        rows.append(
            _row(
                entry.created_at,
                "academic_setup",
                label,
                entry.actor,
                None,
                {
                    "object": entry.object_repr,
                    "program": entry.program.code if entry.program else None,
                    "major": entry.major.code if entry.major else None,
                    "is_admin_override": entry.is_admin_override,
                    **entry.details,
                },
            )
        )

    if source:
        rows = [r for r in rows if r["source"] == source]
    if date_from:
        rows = [r for r in rows if r["timestamp"].date() >= date_from]
    if date_to:
        rows = [r for r in rows if r["timestamp"].date() <= date_to]

    rows.sort(key=lambda r: r["timestamp"], reverse=True)
    return rows


def models_q_user(user, field_names):
    from django.db.models import Q

    q = Q()
    for name in field_names:
        q |= Q(**{name: user})
    return q


SOURCES = [
    ("account", "Account changes"),
    ("score", "Score changes"),
    ("grading_component", "Grading component changes"),
    ("grade_sheet", "Grade sheet transitions"),
    ("grade_correction", "Grade corrections"),
    ("teaching_assignment", "Teaching assignments"),
    ("academic_setup", "Sections / Subjects / Classes"),
]
