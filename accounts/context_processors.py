from .menu import menu_for


def sidebar(request):
    """Makes the role-appropriate sidebar menu and the active url_name
    available in every template."""
    if not request.user.is_authenticated:
        return {}
    active_url_name = (
        f"{request.resolver_match.namespace}:{request.resolver_match.url_name}"
        if request.resolver_match and request.resolver_match.namespace
        else (request.resolver_match.url_name if request.resolver_match else None)
    )
    return {
        "sidebar_menu": menu_for(request.user),
        "active_url_name": active_url_name,
        "sidebar_badges": _sidebar_badges(request.user),
    }


def _sidebar_badges(user):
    """{url_name: count} shown as a small badge next to that sidebar item —
    local import (accounts loads before approvals) to avoid a module-level
    import cycle."""
    if user.is_program_head:
        from approvals.models import GradeSheet, GradeSheetStatus

        count = (
            GradeSheet.objects.filter(
                status=GradeSheetStatus.SUBMITTED, class_offering__sections__program__program_head=user
            )
            .distinct()
            .count()
        )
        if count:
            return {"approvals:index": count}
    return {}
