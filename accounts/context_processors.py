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
    }
