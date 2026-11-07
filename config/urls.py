from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from django.views.generic import RedirectView

from config.admin import site as admin_site
from core.views import healthz

# Superuser-only, at a non-default path in production via DJANGO_ADMIN_URL
# (config/settings/prod.py) — day-to-day work uses the app's own pages
# (validations + audit log), not Django Admin. See CLAUDE.md section 11.
_ADMIN_URL = getattr(settings, "ADMIN_URL", "admin/")

urlpatterns = [
    path("", RedirectView.as_view(url="/dashboard/", permanent=False)),
    path("healthz", healthz, name="healthz"),
    path(_ADMIN_URL, admin_site.urls),
    path("accounts/", include("accounts.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("academics/", include("academics.urls")),
    path("grading/", include("grading.urls")),
    path("approvals/", include("approvals.urls")),
    path("forecasting/", include("forecasting.urls")),
    path("reports/", include("reports.urls")),
]

if settings.DEBUG:
    # Uploaded files (e.g. InstitutionSettings.logo) — production serves
    # these via the web server/storage backend, not Django itself.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

    if "debug_toolbar" in settings.INSTALLED_APPS:
        urlpatterns += [path("__debug__/", include("debug_toolbar.urls"))]

handler403 = "accounts.views.permission_denied_view"
handler404 = "accounts.views.not_found_view"
handler500 = "accounts.views.server_error_view"
