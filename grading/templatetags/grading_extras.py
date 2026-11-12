from decimal import Decimal

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


@register.simple_tag
def component_breakdown(result, component):
    """Find a StudentGradeResult's ComponentBreakdown for a given (scheme)
    component — used wherever a table's columns are the *visible* (set-up)
    components but a result's `.components` list still covers every
    component, so a plain zip()/index lookup would misalign."""
    return next((b for b in result.components if b.component.id == component.id), None)


@register.filter
def trim_decimal(value):
    """Strip unnecessary trailing zeros from a weight/score/max-score Decimal
    for display — 20.00 -> "20", 12.50 -> "12.5", 0.50 -> "0.5". These values
    never carry more than 2 decimal places (model field definitions), so a
    fixed-point format + strip is exact (no float rounding surprises)."""
    if value is None:
        return "—"
    text = f"{Decimal(value):.2f}".rstrip("0").rstrip(".")
    return text or "0"


@register.filter
def weight_decimal(value):
    """A whole-number percent weight as a 0-1 decimal fraction, 2 places
    -- the Class Record grid's header-row-3 label under each component's
    weight column (e.g. 5% -> "0.05", 30% -> "0.30"), matching the CITCI
    class record's own header row exactly."""
    if value is None:
        return "—"
    return f"{(Decimal(value) / Decimal('100')):.2f}"
