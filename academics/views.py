from accounts.decorators import role_required
from accounts.models import User
from accounts.utils import coming_soon

ADMIN = User.Role.ADMIN
PROGRAM_HEAD = User.Role.PROGRAM_HEAD
INSTRUCTOR = User.Role.INSTRUCTOR


@role_required(ADMIN)
def terms(request):
    return coming_soon(request, "Academic Years & Semesters")


@role_required(ADMIN)
def programs(request):
    return coming_soon(request, "Programs")


@role_required(ADMIN)
def sections(request):
    return coming_soon(request, "Sections")


@role_required(ADMIN)
def subjects(request):
    return coming_soon(request, "Subjects")


@role_required(ADMIN, PROGRAM_HEAD)
def classes(request):
    return coming_soon(request, "Classes")


@role_required(INSTRUCTOR)
def my_classes(request):
    return coming_soon(request, "My Classes")


@role_required(ADMIN)
def enrollment(request):
    return coming_soon(request, "Enrollment")
