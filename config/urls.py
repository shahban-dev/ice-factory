"""Root URL configuration."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from core import views as core_views

urlpatterns = [
    path("", include("core.urls")),
    path("customers/", include("customers.urls")),
    path("sales/", include("sales.urls")),
    path("expenses/", include("expenses.urls")),
    path("employees/", include("employees.urls")),
    path("reports/", include("reports.urls")),
    path("accounts/", include("accounts.urls")),
    path("sw.js", core_views.service_worker, name="service-worker"),
    path(settings.ADMIN_URL, admin.site.urls),
]

handler403 = "core.views.error_403"
handler404 = "core.views.error_404"
handler500 = "core.views.error_500"
