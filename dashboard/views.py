from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from accounts.decorators import role_required
from accounts.models import User
from accounts.utils import coming_soon

_TEMPLATE_BY_ROLE = {
    User.Role.ADMIN: "dashboard/admin_dashboard.html",
    User.Role.PROGRAM_HEAD: "dashboard/program_head_dashboard.html",
    User.Role.INSTRUCTOR: "dashboard/instructor_dashboard.html",
    User.Role.STUDENT: "dashboard/student_dashboard.html",
}


@login_required
def home(request):
    template = _TEMPLATE_BY_ROLE.get(request.user.role, "dashboard/admin_dashboard.html")
    return render(request, template)


@role_required(User.Role.STUDENT)
def notifications(request):
    return coming_soon(request, "Notifications")
