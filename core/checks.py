"""Dev-only system checks -- never run in production (prod serves
whatever was built at deploy time; staleness there is a deploy-process
concern, not a thing to warn about on every request/management command)."""

from pathlib import Path

from django.conf import settings
from django.core.checks import Warning, register


@register()
def tailwind_css_freshness_check(app_configs, **kwargs):
    """Warns when static/css/tailwind.css is older than any template --
    a stale build silently drops new utility classes (the class just
    doesn't render, no error anywhere), which is exactly the kind of bug
    that burns time in a "why is my new layout broken" session. Caught
    this for real: a modal redesign used new width/flex classes that
    were invisible until a `tailwind build` picked them up."""
    if settings.SETTINGS_MODULE.endswith(".prod"):
        return []

    css_path = Path(settings.BASE_DIR) / "static" / "css" / "tailwind.css"
    if not css_path.exists():
        return []
    css_mtime = css_path.stat().st_mtime

    templates_dir = Path(settings.BASE_DIR) / "templates"
    if not templates_dir.exists():
        return []

    newest_template = None
    newest_mtime = 0.0
    for path in templates_dir.rglob("*.html"):
        mtime = path.stat().st_mtime
        if mtime > newest_mtime:
            newest_mtime = mtime
            newest_template = path

    if newest_template is not None and newest_mtime > css_mtime:
        return [
            Warning(
                f"static/css/tailwind.css is older than {newest_template.relative_to(settings.BASE_DIR)} -- "
                "new Tailwind utility classes used there may not be compiled in yet.",
                hint="Run `python manage.py tailwind build` once, or keep `python manage.py tailwind "
                "runserver` running while you work, so the stylesheet rebuilds as templates change.",
                id="core.W001",
            )
        ]
    return []
