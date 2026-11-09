from urllib.parse import urlparse

from django.http import HttpResponse
from django.urls import Resolver404, resolve, reverse

from core.htmx import htmx_aware_redirect, is_htmx

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

    Redirects via `htmx_aware_redirect` — the topbar's notification bell
    polls `dashboard:bell` every 60s via HTMX, so a bare 302 here (which
    htmx would follow and swap the *target* page's full HTML into the
    bell's small fragment) produced a whole nested sidebar/topbar layout
    inside the bell. `HX-Redirect` makes the browser navigate instead.
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
                    return htmx_aware_redirect(request, reverse("accounts:force_password_change"))
                if not user.privacy_consent_at:
                    return htmx_aware_redirect(request, reverse("accounts:privacy_consent"))
        return self.get_response(request)


class HtmxLoginRedirectMiddleware:
    """Converts a login-redirect response (e.g. from `login_required`/
    `role_required` on an expired/anonymous session) into an `HX-Redirect`
    when the request came from HTMX — same nested-layout problem as
    ForceFirstLoginStepsMiddleware above, but for the many views that
    redirect to login via Django's own decorators rather than this app's
    middleware, so it's handled centrally here instead of at each view.

    Prefers `HX-Current-URL` (the actual page the browser has open, which
    htmx sends on every request) over the triggering request's own path
    for `?next=` — the request that got redirected might be a background
    poll hitting its own small endpoint (e.g. `/dashboard/bell/`), not the
    page the user should return to after logging back in.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (
            is_htmx(request)
            and response.status_code in (301, 302)
            and response.get("Location", "").startswith(reverse("accounts:login"))
        ):
            next_path = urlparse(request.headers.get("HX-Current-URL", "")).path
            location = f"{reverse('accounts:login')}?next={next_path}" if next_path else response["Location"]
            htmx_response = HttpResponse(status=204)
            htmx_response["HX-Redirect"] = location
            return htmx_response
        return response
