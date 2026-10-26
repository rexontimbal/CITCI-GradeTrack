import secrets
import string

from django.shortcuts import render

ADJECTIVES = ["Swift", "Bright", "Calm", "Bold", "Quiet", "Sunny", "Brave", "Clear"]
_TEMP_PASSWORD_ALPHABET = string.ascii_letters + string.digits


def coming_soon(request, title):
    """Renders the shared placeholder page for a not-yet-built module."""
    return render(request, "partials/coming_soon_page.html", {"page_title": title})


def generate_temp_password():
    """A readable-ish one-time password: Word + 4 digits + symbol, e.g.
    'Swift4821!'. Meets Django's default validators (length, not all-numeric,
    not too similar to the username)."""
    word = secrets.choice(ADJECTIVES)
    digits = "".join(secrets.choice(string.digits) for _ in range(4))
    symbol = secrets.choice("!@#$%")
    return f"{word}{digits}{symbol}"
