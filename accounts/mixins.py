from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied


class RoleRequiredMixin(LoginRequiredMixin):
    """Class-based-view counterpart to accounts.decorators.role_required.

    Set `allowed_roles = (User.Role.ADMIN, ...)` on the view.
    """

    allowed_roles = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if self.allowed_roles and request.user.role not in self.allowed_roles:
            raise PermissionDenied("You do not have access to this page.")
        return super().dispatch(request, *args, **kwargs)
