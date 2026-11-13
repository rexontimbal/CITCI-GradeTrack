"""Shared date-validation rules for a semester's start/end dates — used by
both `SemesterForm` (admin's Semester create/edit modal) and the New
Academic Year wizard's step 1 (which also lets the admin set each new
semester's dates up front). Pure functions, no DB/session/HTTP concerns,
so both call sites can apply identical rules without duplicating them.

Blocking vs. warning, per CITCI's confirmed rule: a backwards range or a
range outside the academic year's two calendar years is rejected outright;
an unusually long semester (or summer term) is only a warning — it's
sometimes legitimate (e.g. an extended term) and must never block saving.
"""

from datetime import date

from .models import Term

SEMESTER_WARNING_DAYS = 183  # ~6 months
SUMMER_WARNING_DAYS = 93  # ~3 months


def validate_date_range(start_date, end_date, ay_start_year, ay_end_year):
    """Returns a dict of {field_name: error_message} — empty if the range
    is valid. Only checks what's actually provided; blank dates are
    allowed (Semester.start_date/end_date are both nullable)."""
    errors = {}
    if start_date and end_date and end_date <= start_date:
        errors["end_date"] = "End date must be after the start date."

    ay_start = date(ay_start_year, 1, 1)
    ay_end = date(ay_end_year, 12, 31)
    ay_label = f"A.Y. {ay_start_year}–{ay_end_year}"
    if start_date and not (ay_start <= start_date <= ay_end):
        errors["start_date"] = f"Start date must fall within {ay_label}."
    if end_date and not (ay_start <= end_date <= ay_end):
        errors["end_date"] = f"End date must fall within {ay_label}."
    return errors


def duration_warning(term, start_date, end_date):
    """Non-blocking: a plain-language warning string, or None. Summer
    gets a shorter threshold (3 months) than a regular semester (6)."""
    if not start_date or not end_date:
        return None
    days = (end_date - start_date).days
    if term == Term.SUMMER:
        if days > SUMMER_WARNING_DAYS:
            return "This summer term is longer than 3 months. Double check the dates."
    elif days > SEMESTER_WARNING_DAYS:
        return "This semester is longer than 6 months. Double check the dates."
    return None


def ranges_overlap(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end
