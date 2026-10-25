from django.contrib.auth import update_session_auth_hash, views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils import timezone

from .decorators import role_required
from .forms import ForcedPasswordChangeForm
from .models import User
from .utils import coming_soon


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True


class LogoutView(auth_views.LogoutView):
    """Logout only via POST (template uses a form, not a link)."""


@login_required
def profile(request):
    return render(request, "accounts/profile.html")


@login_required
def help_page(request):
    return render(request, "accounts/help.html")


@login_required
def force_password_change(request):
    """Doubles as the forced first-login screen (must_change_password=True)
    and a voluntary "Change Password" page reachable from the sidebar user
    menu at any time."""
    if request.method == "POST":
        form = ForcedPasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            user.must_change_password = False
            user.save(update_fields=["must_change_password"])
            update_session_auth_hash(request, user)
            messages.success(request, "Password updated.")
            if not user.privacy_consent_at:
                return redirect("accounts:privacy_consent")
            return redirect("dashboard:home")
    else:
        form = ForcedPasswordChangeForm(request.user)
    return render(request, "accounts/force_password_change.html", {"form": form})


@login_required
def privacy_consent(request):
    if request.user.privacy_consent_at:
        return redirect("dashboard:home")
    if request.method == "POST":
        request.user.privacy_consent_at = timezone.now()
        request.user.save(update_fields=["privacy_consent_at"])
        return redirect("dashboard:home")
    return render(request, "accounts/privacy_consent.html")


def permission_denied_view(request, exception=None):
    return render(request, "accounts/403.html", status=403)


@role_required(User.Role.ADMIN)
def users(request):
    return coming_soon(request, "Users")
