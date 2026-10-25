from accounts.decorators import role_required
from accounts.models import User
from accounts.utils import coming_soon


@role_required(User.Role.PROGRAM_HEAD)
def index(request):
    return coming_soon(request, "Grade Approvals")
