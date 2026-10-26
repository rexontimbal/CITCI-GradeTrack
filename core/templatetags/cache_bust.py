import os

from django import template
from django.contrib.staticfiles import finders

register = template.Library()


@register.simple_tag
def static_mtime(path):
    """On-disk mtime (int, seconds) of a static file, for use as a ?v=
    cache-busting query string in DEBUG. Django's dev static server sends no
    Cache-Control header, so a browser can silently keep serving a stale
    cached copy of e.g. tailwind.css after it's rebuilt, since the URL never
    changes — see templates/tailwind_cli/tailwind_css.html."""
    found = finders.find(path)
    if not found:
        return ""
    try:
        return int(os.path.getmtime(found))
    except OSError:
        return ""
