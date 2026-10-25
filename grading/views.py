from accounts.decorators import role_required
from accounts.models import User
from accounts.utils import coming_soon

ADMIN = User.Role.ADMIN
INSTRUCTOR = User.Role.INSTRUCTOR
STUDENT = User.Role.STUDENT


@role_required(ADMIN)
def templates(request):
    return coming_soon(request, "Grading Templates")


@role_required(INSTRUCTOR)
def submitted(request):
    return coming_soon(request, "Submitted Grades")


@role_required(STUDENT)
def my_grades(request):
    return coming_soon(request, "My Grades")


@role_required(STUDENT)
def my_progress(request):
    return coming_soon(request, "My Progress")
