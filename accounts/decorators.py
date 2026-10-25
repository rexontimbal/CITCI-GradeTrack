from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def role_required(*roles):
    """View decorator restricting access to the given User.Role values.

    Usage: @role_required(User.Role.ADMIN, User.Role.PROGRAM_HEAD)
    Unauthenticated users are sent to login; wrong-role users get a 403.
    """

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapped(request, *args, **kwargs):
            if request.user.role not in roles:
                raise PermissionDenied("You do not have access to this page.")
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
