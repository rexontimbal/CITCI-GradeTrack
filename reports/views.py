from accounts.decorators import role_required
from accounts.models import User
from accounts.utils import coming_soon


@role_required(User.Role.ADMIN, User.Role.PROGRAM_HEAD, User.Role.INSTRUCTOR)
def index(request):
    return coming_soon(request, "Reports")
