from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from academics.models import ClassOffering, ClassRosterEntry, Program, Semester
from accounts.decorators import role_required
from accounts.models import User

from .models import Notification


@login_required
def home(request):
    user = request.user
    if user.is_admin_role:
        return _admin_dashboard(request)
    if user.is_program_head:
        return render(request, "dashboard/program_head_dashboard.html")
    if user.is_instructor:
        return _instructor_dashboard(request)
    return _student_dashboard(request)


def _active_semester():
    return Semester.objects.filter(is_active=True).first()


def _admin_dashboard(request):
    active = _active_semester()
    context = {
        "total_students": User.objects.filter(role=User.Role.STUDENT, is_active=True).count(),
        "total_instructors": User.objects.filter(role=User.Role.INSTRUCTOR, is_active=True).count(),
        "active_classes": ClassOffering.objects.filter(semester=active).count() if active else 0,
        "total_programs": Program.objects.count(),
    }
    return render(request, "dashboard/admin_dashboard.html", context)


def _instructor_dashboard(request):
    active = _active_semester()
    classes = ClassOffering.objects.filter(instructor=request.user, semester=active) if active else ClassOffering.objects.none()
    total_students = (
        ClassRosterEntry.objects.filter(class_offering__in=classes, status=ClassRosterEntry.Status.ACTIVE)
        .values("student")
        .distinct()
        .count()
    )
    context = {"my_classes_count": classes.count(), "total_students": total_students}
    return render(request, "dashboard/instructor_dashboard.html", context)


def _student_dashboard(request):
    from approvals.services import compute_gwa
    from grading.models import AssessmentItem, Score
    from grading.services import compute_student, released_entry_for, show_unofficial_scores_to_students, subject_status_chip

    student = request.user
    active = _active_semester()
    show_unofficial = show_unofficial_scores_to_students()

    roster_entries = (
        ClassRosterEntry.objects.filter(student=student, class_offering__semester=active)
        .exclude(status=ClassRosterEntry.Status.DROPPED)
        .select_related("class_offering__subject", "class_offering__instructor")
        .order_by("class_offering__subject__code")
        if active
        else ClassRosterEntry.objects.none()
    )

    cards = []
    warnings_count = 0 if show_unofficial else None
    for entry in roster_entries:
        released_entry = released_entry_for(entry)
        status_label, status_key = subject_status_chip(entry, released_entry)

        total_items = AssessmentItem.objects.filter(class_offering=entry.class_offering).count()
        encoded_items = Score.objects.filter(roster_entry=entry, score__isnull=False).count()
        progress_pct = int(encoded_items / total_items * 100) if total_items else 0

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
            running_grade = compute_student(entry).running_grade
            card["unofficial_grade"] = running_grade
            if running_grade is not None and running_grade > 3:
                warnings_count += 1
        cards.append(card)

    gwa = compute_gwa(student, active) if active else None
    released_display = f"{gwa['released_count']}/{gwa['total_count']}" if gwa else "0/0"
    notifications = request.user.notifications.all()[:5]

    context = {
        "cards": cards,
        "subjects_count": roster_entries.count(),
        "gwa": gwa,
        "released_display": released_display,
        "warnings_count": warnings_count,
        "notifications": notifications,
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
