from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("", RedirectView.as_view(url="/dashboard/", permanent=False)),
    path("admin/", admin.site.urls),
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

handler403 = "accounts.views.permission_denied_view"
