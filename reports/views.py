"""Phase 4 views: reports, audit log, recycle bin, settings, backups."""

import calendar

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from core.models import BackupLog, get_settings
from core.params import parse_date, parse_int
from core.permissions import PermissionRequiredMixin
from customers.models import Customer
from expenses.models import ExpenseCategory
from reports import exports
from reports.forms import BackupDownloadForm, SettingsForm
from reports.services import (
    dues_report,
    expense_report,
    monthly_report,
    sales_register,
)
from reports.system_services import (
    AUDIT_MODELS,
    audit_entries,
    recycle_bin_entries,
    restore_from_bin,
)
from sales.models import Product


class ReportsIndexView(PermissionRequiredMixin, View):
    permission_code = "reports.view"

    def get(self, request):
        return render(request, "reports/index.html")


def _month_params(request):
    """Year/month from the query string, falling back to today for
    anything invalid (letters, month 13, a 30-digit year)."""
    today = timezone.localdate()
    year = parse_int(request.GET.get("year"), today.year)
    month = parse_int(request.GET.get("month"), today.month)
    if year is None or not 1 <= year <= 9999:
        year = today.year
    if month is None or not 1 <= month <= 12:
        month = today.month
    return year, month


class MonthlyReportView(PermissionRequiredMixin, View):
    permission_code = "reports.view"

    def get(self, request):
        year, month = _month_params(request)
        data = monthly_report(year, month)
        fmt = request.GET.get("format", "")
        if fmt == "pdf":
            return exports.monthly_pdf(data)
        if fmt == "excel":
            return exports.monthly_excel(data)
        return render(request, "reports/monthly.html", {
            "data": data, "year": year, "month": month,
            "months": [(i, calendar.month_name[i]) for i in range(1, 13)],
        })


class DuesReportView(PermissionRequiredMixin, View):
    permission_code = "reports.view"

    def get(self, request):
        rows = dues_report()
        fmt = request.GET.get("format", "")
        if fmt == "pdf":
            return exports.dues_pdf(rows)
        if fmt == "excel":
            return exports.dues_excel(rows)
        return render(request, "reports/dues.html", {"rows": rows})


class SalesRegisterView(PermissionRequiredMixin, View):
    permission_code = "reports.view"

    def get(self, request):
        today = timezone.localdate()
        first = today.replace(day=1)
        date_from = parse_date(request.GET.get("from"), first)
        date_to = parse_date(request.GET.get("to"), today)
        customer_id = request.GET.get("customer", "")
        product_id = request.GET.get("product", "")
        sales = sales_register(date_from, date_to, customer_id, product_id)
        fmt = request.GET.get("format", "")
        if fmt == "pdf":
            return exports.register_pdf(sales, date_from, date_to)
        if fmt == "excel":
            return exports.register_excel(sales, date_from, date_to)
        return render(request, "reports/register.html", {
            "sales": sales, "date_from": date_from, "date_to": date_to,
            "customers": Customer.objects.order_by("name"),
            "products": Product.objects.filter(is_active=True).order_by("name"),
            "selected_customer": customer_id, "selected_product": product_id,
        })


class ExpenseReportView(PermissionRequiredMixin, View):
    permission_code = "reports.view"

    def get(self, request):
        today = timezone.localdate()
        first = today.replace(day=1)
        date_from = parse_date(request.GET.get("from"), first)
        date_to = parse_date(request.GET.get("to"), today)
        category_id = request.GET.get("category", "")
        data = expense_report(date_from, date_to, category_id)
        fmt = request.GET.get("format", "")
        if fmt == "pdf":
            return exports.expense_pdf(data, date_from, date_to)
        if fmt == "excel":
            return exports.expense_excel(data, date_from, date_to)
        return render(request, "reports/expense_report.html", {
            "data": data, "date_from": date_from, "date_to": date_to,
            "categories": ExpenseCategory.objects.filter(
                is_active=True).order_by("name"),
            "selected_category": category_id,
        })


class AuditLogView(PermissionRequiredMixin, View):
    permission_code = "audit.view"

    def get(self, request):
        user_id = request.GET.get("user", "")
        model_name = request.GET.get("model", "")
        date_from = request.GET.get("from", "")
        date_to = request.GET.get("to", "")
        object_text = request.GET.get("object", "")
        entries = audit_entries(
            user_id=user_id or None,
            model_name=model_name or None,
            date_from=parse_date(date_from),
            date_to=parse_date(date_to),
            object_text=object_text,
        )
        paginator = Paginator(entries, 25)
        page = paginator.get_page(request.GET.get("page"))
        User = get_user_model()
        users = User.objects.filter(
            pk__in=set(
                e["user"].pk for e in entries if e["user"] is not None
            )
        ).order_by("username") if entries else User.objects.none()
        return render(request, "reports/audit.html", {
            "page": page, "users": users,
            "models": [label for _, label in AUDIT_MODELS],
            "selected_user": user_id, "selected_model": model_name,
            "date_from": date_from, "date_to": date_to,
            "object_text": object_text,
        })


class RecycleBinView(PermissionRequiredMixin, View):
    permission_code = "recycle.view"

    def get(self, request):
        return render(request, "reports/recycle.html", {
            "entries": recycle_bin_entries(),
        })


class RecycleRestoreView(PermissionRequiredMixin, View):
    permission_code = "recycle.restore"

    def post(self, request):
        try:
            message = restore_from_bin(
                request.POST.get("model", ""),
                request.POST.get("pk", ""),
                request.user,
            )
        except ValidationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, message)
        return redirect("reports:recycle")


class SettingsView(PermissionRequiredMixin, View):
    permission_code = "settings.edit"

    def get(self, request):
        settings_obj = get_settings()
        last_backup = BackupLog.objects.filter(
            status=BackupLog.STATUS_SUCCESS
        ).first()
        return render(request, "reports/settings.html", {
            "form": SettingsForm(instance=settings_obj),
            "last_backup": last_backup,
            "backup_form": BackupDownloadForm(),
        })

    def post(self, request):
        settings_obj = get_settings()
        form = SettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            saved = form.save(commit=False)
            saved.updated_by = request.user
            saved._change_reason = "Settings updated"
            saved.save()
            messages.success(request, "Settings saved.")
            return redirect("reports:settings")
        last_backup = BackupLog.objects.filter(
            status=BackupLog.STATUS_SUCCESS
        ).first()
        return render(request, "reports/settings.html", {
            "form": form, "last_backup": last_backup,
            "backup_form": BackupDownloadForm(),
        })


class BackupDownloadView(PermissionRequiredMixin, View):
    permission_code = "settings.edit"

    def post(self, request):
        form = BackupDownloadForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Enter your password to download a backup.")
            return redirect("reports:settings")
        if not request.user.check_password(form.cleaned_data["password"]):
            messages.error(request, "That password is not correct.")
            return redirect("reports:settings")
        from reports.backup import make_database_dump

        try:
            data, filename = make_database_dump()
        except Exception as exc:
            BackupLog.objects.create(
                kind=BackupLog.KIND_MANUAL, status=BackupLog.STATUS_FAILURE,
                message=str(exc), user=request.user,
            )
            messages.error(request, f"Backup failed: {exc}")
            return redirect("reports:settings")
        BackupLog.objects.create(
            kind=BackupLog.KIND_MANUAL, status=BackupLog.STATUS_SUCCESS,
            filename=filename, size_bytes=len(data), user=request.user,
        )
        from django.http import HttpResponse

        response = HttpResponse(data, content_type="application/gzip")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
