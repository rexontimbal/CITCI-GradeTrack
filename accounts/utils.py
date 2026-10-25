from django.shortcuts import render


def coming_soon(request, title):
    """Renders the shared placeholder page for a not-yet-built module."""
    return render(request, "partials/coming_soon_page.html", {"page_title": title})
