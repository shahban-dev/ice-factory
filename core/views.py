"""Core views: home shell, global search, friendly error pages, service worker."""

from pathlib import Path

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import FileResponse, HttpResponse
from django.shortcuts import render
from django.views import View
from django.views.generic import TemplateView

from core.permissions import PermissionRequiredMixin
from customers.models import Customer, normalize_phone
from sales.models import Sale


class HomeView(LoginRequiredMixin, TemplateView):
    """The dashboard: today's and this month's money, top debtors, today's
    activity (auto-refreshing), and quick-add shortcuts."""

    template_name = "core/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from reports.services import dashboard_data

        context.update(dashboard_data())
        return context


class DashboardActivityFragment(LoginRequiredMixin, View):
    """Today's activity list, polled by the dashboard every 30 seconds."""

    def get(self, request):
        from reports.services import today_activity

        return render(request, "core/_activity.html", {
            "activity": today_activity(),
        })


class GlobalSearchView(PermissionRequiredMixin, View):
    """Global search: customer name or phone, invoice number."""
    permission_code = "customers.view"

    def get(self, request):
        q = request.GET.get("q", "").strip()
        customers = []
        sales = []
        if q:
            customers = Customer.objects.filter(
                Q(name__icontains=q) | Q(phone__icontains=q)
                | Q(phone__icontains=normalize_phone(q))
            ).order_by("name")[:25]
            sales = Sale.objects.select_related("customer").filter(
                invoice_number__icontains=q
            ).order_by("-date", "-id")[:25]
        return render(request, "core/search.html", {
            "q": q, "customers": customers, "sales": sales,
        })


def service_worker(request):
    """Serve /sw.js from the static directory (root scope is required for
    the service worker to handle app navigations)."""
    path = Path(settings.BASE_DIR) / "static" / "sw.js"
    return FileResponse(open(path, "rb"), content_type="application/javascript")


def error_403(request, exception=None):
    return render(request, "403.html", status=403)


def error_404(request, exception=None):
    return render(request, "404.html", status=404)


def error_500(request):
    return render(request, "500.html", status=500)
