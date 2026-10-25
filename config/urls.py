from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("academics/", include("academics.urls")),
    path("grading/", include("grading.urls")),
    path("approvals/", include("approvals.urls")),
    path("forecasting/", include("forecasting.urls")),
    path("reports/", include("reports.urls")),
]

handler403 = "accounts.views.permission_denied_view"
