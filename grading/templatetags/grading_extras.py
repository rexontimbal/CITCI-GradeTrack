from django import template

from grading.services import format_grade

register = template.Library()


@register.filter
def grade_display(value):
    """Format a raw Decimal grade for display (settings.GRADE_DISPLAY_DECIMALS
    places, e.g. 1.77). Returns an em dash for None (not yet computable)."""
    formatted = format_grade(value)
    return formatted if formatted is not None else "—"


@register.filter
def dict_get(d, key):
    return d.get(key)
