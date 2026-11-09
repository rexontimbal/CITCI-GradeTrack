from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from academics.models import ClassOffering, ClassRosterEntry, Program, Semester, StudentProfile
from accounts.decorators import role_required
from accounts.models import User

from .models import Notification


@login_required
def home(request):
    user = request.user
    if user.is_admin_role:
        return _admin_dashboard(request)
    if user.is_program_head:
        return _program_head_dashboard(request)
    if user.is_instructor:
        return _instructor_dashboard(request)
    return _student_dashboard(request)


def _active_semester():
    return Semester.objects.filter(is_active=True).first()


def _admin_dashboard(request):
    from forecasting.services import count_at_risk_watch

    active = _active_semester()
    classes = ClassOffering.objects.filter(semester=active) if active else ClassOffering.objects.none()
    context = {
        "total_students": User.objects.filter(role=User.Role.STUDENT, is_active=True)
        .exclude(student_profile__status=StudentProfile.Status.COMPLETED)
        .count(),
        "total_instructors": User.objects.filter(role=User.Role.INSTRUCTOR, is_active=True).count(),
        "active_classes": classes.count(),
        "total_programs": Program.objects.count(),
        "at_risk_count": count_at_risk_watch(classes)["at_risk"],
    }
    return render(request, "dashboard/admin_dashboard.html", context)


def _program_head_dashboard(request):
    from django.db.models import Count, Q

    from academics.scoping import classes_in_scope, sections_in_scope
    from approvals.models import GradeSheet, GradeSheetStatus
    from forecasting.services import count_at_risk_watch

    active = _active_semester()
    classes = classes_in_scope(request.user, semester=active) if active else ClassOffering.objects.none()

    sections_created = sections_in_scope(request.user).filter(academic_year=active.academic_year).count() if active else 0
    classes_created = classes.count() if active else 0
    classes_without_instructor = classes.filter(instructor__isnull=True).count() if active else 0
    empty_class_lists = (
        classes.annotate(
            roster_size=Count("roster_entries", filter=Q(roster_entries__status=ClassRosterEntry.Status.ACTIVE), distinct=True)
        )
        .filter(roster_size=0)
        .count()
        if active
        else 0
    )
    sheets_submitted = (
        GradeSheet.objects.filter(
            class_offering__in=classes, status__in=[GradeSheetStatus.SUBMITTED, GradeSheetStatus.APPROVED, GradeSheetStatus.RELEASED, GradeSheetStatus.LOCKED]
        )
        .distinct()
        .count()
        if active
        else 0
    )

    context = {
        "at_risk_count": count_at_risk_watch(classes)["at_risk"],
        "unassigned_count": classes_without_instructor,
        "unassigned_classes_url": f"{reverse('academics:program_head_classes')}?unassigned=1",
        "active_semester_set": bool(active),
        "scope_label": request.user.program_head_scope_label,
        "checklist": {
            "sections_created": sections_created,
            "classes_created": classes_created,
            "classes_without_instructor": classes_without_instructor,
            "empty_class_lists": empty_class_lists,
            "sheets_submitted": sheets_submitted,
            "sheets_total": classes_created,
        },
    }
    return render(request, "dashboard/program_head_dashboard.html", context)


def _instructor_dashboard(request):
    from approvals.services import (
        missing_score_counts_for_classes,
        pending_inc_completions_for_classes,
        returned_sheets_for_classes,
        unsubmitted_sheets_for_classes,
    )
    from forecasting.services import at_risk_without_intervention

    active = _active_semester()
    classes = (
        list(ClassOffering.objects.filter(instructor=request.user, semester=active).select_related("subject", "semester"))
        if active
        else []
    )
    total_students = (
        ClassRosterEntry.objects.filter(class_offering__in=classes, status=ClassRosterEntry.Status.ACTIVE)
        .values("student")
        .distinct()
        .count()
        if classes
        else 0
    )

    missing_counts = missing_score_counts_for_classes(classes) if classes else {}
    missing_score_items = [
        {"class_offering": class_offering, "count": count}
        for class_offering in classes
        if (count := missing_counts.get(class_offering.id))
    ]
    returned_sheets = returned_sheets_for_classes(classes) if classes else []
    unsubmitted_sheets = unsubmitted_sheets_for_classes(classes) if classes else []
    at_risk_no_intervention = at_risk_without_intervention(classes) if classes else []
    inc_pending = pending_inc_completions_for_classes(classes) if classes else []

    context = {
        "my_classes_count": len(classes),
        "total_students": total_students,
        "missing_score_items": missing_score_items,
        "returned_sheets": returned_sheets,
        "unsubmitted_sheets": unsubmitted_sheets,
        "at_risk_no_intervention": at_risk_no_intervention,
        "inc_pending": inc_pending,
        "grade_sheets_pending_count": len(returned_sheets) + len(unsubmitted_sheets),
    }
    return render(request, "dashboard/instructor_dashboard.html", context)


def _student_dashboard(request):
    from django.db.models import Count, Q

    from approvals.services import compute_gwa
    from grading.services import compute_students_batch, released_entries_for, show_unofficial_scores_to_students, subject_status_chip

    student = request.user
    active = _active_semester()
    show_unofficial = show_unofficial_scores_to_students()

    # Batched (Phase 8 part B dashboard query-count pass): released_entry,
    # total/encoded item counts, the unofficial running grade, and the
    # forecast card were each computed PER subject — ~10-12 queries x every
    # subject (111 queries measured before this pass for a ~9-subject
    # student). Every one of those is now one query total for the whole
    # page instead of one per subject.
    roster_entries = list(
        ClassRosterEntry.objects.filter(student=student, class_offering__semester=active)
        .exclude(status=ClassRosterEntry.Status.DROPPED)
        .select_related("class_offering__subject", "class_offering__instructor")
        .annotate(
            total_items=Count("class_offering__assessment_items", distinct=True),
            encoded_items=Count("scores", filter=Q(scores__score__isnull=False), distinct=True),
        )
        .order_by("class_offering__subject__code")
        if active
        else []
    )

    released_by_entry = released_entries_for(roster_entries)
    needs_unofficial = [e for e in roster_entries if show_unofficial and released_by_entry.get(e.id) is None]
    unofficial_by_entry = compute_students_batch(needs_unofficial) if needs_unofficial else {}

    cards = []
    warnings_count = 0 if show_unofficial else None
    for entry in roster_entries:
        released_entry = released_by_entry.get(entry.id)
        status_label, status_key = subject_status_chip(entry, released_entry)
        progress_pct = int(entry.encoded_items / entry.total_items * 100) if entry.total_items else 0

        card = {
            "entry": entry,
            "status_label": status_label,
            "status_key": status_key,
            "progress_pct": progress_pct,
            "is_released": released_entry is not None,
            "final_grade": None,
            "remarks": None,
            "unofficial_grade": None,
        }
        if released_entry is not None:
            card["final_grade"] = released_entry.final_grade
            card["remarks"] = released_entry.get_remarks_display()
        elif show_unofficial:
            running_grade = unofficial_by_entry[entry.id].running_grade
            card["unofficial_grade"] = running_grade
            if running_grade is not None and running_grade > 3:
                warnings_count += 1
        cards.append(card)

    gwa = compute_gwa(student, active) if active else None
    released_display = f"{gwa['released_count']}/{gwa['total_count']}" if gwa else "0/0"
    notifications = request.user.notifications.all()[:5]

    from forecasting.services import student_forecast_cards_batch

    forecast_priority = {"AT_RISK": 0, "WATCH": 1, "ON_TRACK": 2}
    forecast_by_entry = student_forecast_cards_batch(roster_entries)
    forecast_cards = [card for card in forecast_by_entry.values() if card is not None]
    forecast_cards.sort(key=lambda c: forecast_priority[c["level"]])
    forecast = forecast_cards[0] if forecast_cards else None

    context = {
        "cards": cards,
        "subjects_count": len(roster_entries),
        "gwa": gwa,
        "released_display": released_display,
        "warnings_count": warnings_count,
        "notifications": notifications,
        "forecast": forecast,
    }
    return render(request, "dashboard/student_dashboard.html", context)


# ---------------------------------------------------------------------------
# Notifications — topbar bell (HTMX-polled dropdown) + full list page
# ---------------------------------------------------------------------------


@login_required
def bell(request):
    notifications = Notification.objects.filter(recipient=request.user)[:10]
    unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
    return render(request, "partials/_notification_bell.html", {"notifications": notifications, "unread_count": unread_count})


@login_required
def mark_read(request, pk):
    """Plain navigation (not HTMX) — marks read, then sends the user on to
    wherever the notification points, so clicking one both acts as "mark
    read" and as the link in a single click."""
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notification.is_read = True
    notification.save(update_fields=["is_read"])
    return redirect(notification.link or reverse("dashboard:home"))


@login_required
def mark_all_read(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return bell(request)


@login_required
def notifications(request):
    notification_list = Notification.objects.filter(recipient=request.user)
    context = {"page_title": "Notifications", "notifications": notification_list}
    return render(request, "dashboard/notifications.html", context)


@login_required
def notifications_mark_all_read(request):
    """Same effect as mark_all_read, but for the full Notifications page —
    a plain POST + redirect back to the list, not an HTMX bell-fragment
    swap (what mark_all_read is for)."""
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return redirect(reverse("dashboard:notifications"))
