"""Inline line-style SVG icons used by the sidebar (no icon CDN, per spec).
Each is a 24x24 stroke-based outline that inherits currentColor."""

from django import template
from django.utils.safestring import mark_safe

register = template.Library()

_STROKE = 'fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"'

_PATHS = {
    "home": '<path d="M3 11.5 12 4l9 7.5"/><path d="M5 10v9a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1v-9"/>',
    "calendar": '<rect x="3.5" y="5" width="17" height="16" rx="2"/><path d="M8 3v4M16 3v4M3.5 10h17"/>',
    "folder": '<path d="M3.5 7a1 1 0 0 1 1-1h4.5l2 2h8a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-14.5a1 1 0 0 1-1-1z"/>',
    "grid": '<rect x="3.5" y="3.5" width="7" height="7" rx="1"/><rect x="13.5" y="3.5" width="7" height="7" rx="1"/><rect x="3.5" y="13.5" width="7" height="7" rx="1"/><rect x="13.5" y="13.5" width="7" height="7" rx="1"/>',
    "book": '<path d="M4 4.5h8a3 3 0 0 1 3 3V20H7a3 3 0 0 1-3-3z"/><path d="M20 4.5h-5v15.5h5z"/>',
    "chalkboard": '<rect x="3" y="4" width="18" height="12" rx="1.5"/><path d="M9 20h6M12 16v4"/>',
    "clipboard": '<rect x="5" y="4.5" width="14" height="16" rx="2"/><rect x="8.5" y="3" width="7" height="3" rx="1"/><path d="M8.5 11h7M8.5 15h7"/>',
    "users": '<circle cx="9" cy="8" r="3"/><path d="M3.5 20a5.5 5.5 0 0 1 11 0"/><circle cx="17.5" cy="9" r="2.5"/><path d="M15.5 20a4.5 4.5 0 0 1 6.5-4"/>',
    "sliders": '<path d="M4 6h10M17 6h3M4 12h3M8 12h12M4 18h7M14 18h6"/><circle cx="14" cy="6" r="2"/><circle cx="6" cy="12" r="2"/><circle cx="11" cy="18" r="2"/>',
    "chart": '<path d="M4 20V10M10 20V4M16 20v-7M20 20V13"/><path d="M3 20h18"/>',
    "document": '<path d="M7 3.5h7l4 4V20a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1z"/><path d="M14 3.5V8h4M9 12h6M9 16h6"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 13.5a7.5 7.5 0 0 0 0-3l1.9-1.3-2-3.4-2.2.7a7.6 7.6 0 0 0-2.6-1.5L14 2.5h-4l-.5 2.5a7.6 7.6 0 0 0-2.6 1.5l-2.2-.7-2 3.4L4.6 10.5a7.5 7.5 0 0 0 0 3L2.7 14.8l2 3.4 2.2-.7a7.6 7.6 0 0 0 2.6 1.5l.5 2.5h4l.5-2.5a7.6 7.6 0 0 0 2.6-1.5l2.2.7 2-3.4z"/>',
    "check-circle": '<circle cx="12" cy="12" r="8.5"/><path d="M8.5 12.5l2.3 2.3 4.7-5.1"/>',
    "alert": '<path d="M12 3.5 2.5 20h19z"/><path d="M12 9.5v4.5M12 17h.01"/>',
    "bell": '<path d="M6 10a6 6 0 1 1 12 0c0 4 1.5 5.5 1.5 5.5H4.5S6 14 6 10z"/><path d="M10 19a2 2 0 0 0 4 0"/>',
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "chevron-left": '<path d="M15 5 8 12l7 7"/>',
    "profile": '<circle cx="12" cy="8" r="3.5"/><path d="M4.5 20a7.5 7.5 0 0 1 15 0"/>',
    "help": '<circle cx="12" cy="12" r="8.5"/><path d="M9.5 9.2a2.5 2.5 0 0 1 4.8 1c0 1.7-2.3 2-2.3 3.6"/><path d="M12 17h.01"/>',
    "logout": '<path d="M9 4.5H6a1.5 1.5 0 0 0-1.5 1.5v12A1.5 1.5 0 0 0 6 19.5h3"/><path d="M15 16l4.5-4-4.5-4"/><path d="M19 12H9"/>',
    "close": '<path d="M6 6l12 12M18 6 6 18"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "trash": '<path d="M5 7h14M9 7V4.5h6V7M7 7l1 13h8l1-13"/><path d="M10 11v6M14 11v6"/>',
    "pencil": '<path d="M4 20l.8-4L16 4.8a1.5 1.5 0 0 1 2.1 0l1.1 1.1a1.5 1.5 0 0 1 0 2.1L8 19.2 4 20z"/><path d="M14.5 6.5l3 3"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4.3-4.3"/>',
    "chevron-right": '<path d="M9 5l7 7-7 7"/>',
    "eye": '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
    "eye-off": '<path d="M3 3l18 18"/><path d="M10.6 5.6A10.6 10.6 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a14.6 14.6 0 0 1-3.1 3.9M6.1 6.1C3.4 7.9 2.5 12 2.5 12s3.5 6.5 9.5 6.5a9.9 9.9 0 0 0 3.4-.6"/><path d="M9.9 10a3 3 0 0 0 4.2 4.2"/>',
    "lock": '<rect x="5" y="10.5" width="14" height="9.5" rx="2"/><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/>',
}


@register.simple_tag
def sidebar_icon(name, css_class="w-5 h-5"):
    body = _PATHS.get(name, _PATHS["document"])
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" class="{css_class}" {_STROKE}>{body}</svg>'
    return mark_safe(svg)
