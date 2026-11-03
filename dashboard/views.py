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
    active = _active_semester()
    roster_entries = (
        ClassRosterEntry.objects.filter(
            student=request.user, status=ClassRosterEntry.Status.ACTIVE, class_offering__semester=active
        ).select_related("class_offering__subject", "class_offering__instructor")
        if active
        else ClassRosterEntry.objects.none()
    )
    context = {"roster_entries": roster_entries, "subjects_count": roster_entries.count()}
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
