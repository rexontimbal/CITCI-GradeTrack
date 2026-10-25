from django.shortcuts import redirect
from django.urls import Resolver404, resolve

# URL names reachable even while a forced step is pending.
_EXEMPT_URL_NAMES = {
    "accounts:login",
    "accounts:logout",
    "accounts:force_password_change",
    "accounts:privacy_consent",
}


class ForceFirstLoginStepsMiddleware:
    """Redirects an authenticated user to the password-change / privacy-
    consent screens until both are completed, before they can reach any
    other page (login itself and static/admin media are exempt).

    Uses `resolve()` directly rather than `request.resolver_match`, because
    that attribute is only populated once URL resolution happens further
    down the middleware chain — too late for a check made before calling
    `get_response`.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated and not request.path.startswith("/static/"):
            try:
                match = resolve(request.path_info)
                full_name = f"{match.namespace}:{match.url_name}" if match.namespace else match.url_name
            except Resolver404:
                full_name = None
            if full_name not in _EXEMPT_URL_NAMES:
                if user.must_change_password:
                    return redirect("accounts:force_password_change")
                if not user.privacy_consent_at:
                    return redirect("accounts:privacy_consent")
        return self.get_response(request)
