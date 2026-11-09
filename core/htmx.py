from django.http import HttpResponse
from django.shortcuts import redirect


def is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def htmx_aware_redirect(request, url):
    """A normal redirect for a normal request; for an HTMX request, an
    empty 200 carrying `HX-Redirect` instead, so the browser does a real
    full-page navigation rather than htmx swapping the redirect target's
    full-page HTML into whatever small fragment (e.g. the polled
    notification bell) triggered the request — which is what produces a
    nested sidebar/topbar layout inside the page."""
    if is_htmx(request):
        response = HttpResponse(status=204)
        response["HX-Redirect"] = url
        return response
    return redirect(url)
