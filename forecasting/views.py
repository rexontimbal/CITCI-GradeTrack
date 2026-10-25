from accounts.decorators import role_required
from accounts.models import User
from accounts.utils import coming_soon

ADMIN = User.Role.ADMIN
PROGRAM_HEAD = User.Role.PROGRAM_HEAD
INSTRUCTOR = User.Role.INSTRUCTOR


@role_required(ADMIN)
def model(request):
    return coming_soon(request, "Forecast Model")


@role_required(PROGRAM_HEAD, INSTRUCTOR)
def at_risk(request):
    return coming_soon(request, "At-Risk Students")
