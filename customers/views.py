"""Customer views: list, ledger, create, edit, delete, import, exports."""

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import format_html
from django.views import View
from django.views.generic import ListView

from core.params import parse_date
from core.permissions import PermissionRequiredMixin
from core.services import ConcurrentEditError, save_form_with_version, soft_delete_objects
from customers.forms import CustomerForm, CustomerImportUploadForm
from customers.models import Customer, normalize_phone
from customers.services import parse_import_file, save_import_rows
from sales.services import (
    allocate_customer,
    annotate_customer_balances,
    customer_ledger_entries,
)


class CustomerListView(PermissionRequiredMixin, ListView):
    permission_code = "customers.view"
    model = Customer
    template_name = "customers/list.html"
    context_object_name = "customers"
    paginate_by = 25

    def get_queryset(self):
        qs = annotate_customer_balances(Customer.objects.all())
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q))
        status = self.request.GET.get("status", "")
        if status == "active":
            qs = qs.filter(is_active=True)
        elif status == "inactive":
            qs = qs.filter(is_active=False)
        elif status == "dues":
            qs = qs.filter(balance__gt=0)
        return qs.order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.request.GET.get("q", "")
        context["status"] = self.request.GET.get("status", "")
        return context


class CustomerDetailView(PermissionRequiredMixin, View):
    permission_code = "customers.view"

    def get(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)
        date_from = parse_date(request.GET.get("from"))
        date_to = parse_date(request.GET.get("to"))
        rows = customer_ledger_entries(customer, date_from, date_to)
        allocation = allocate_customer(customer)
        return render(request, "customers/detail.html", {
            "customer": customer,
            "rows": rows,
            "allocation": allocation,
            "date_from": request.GET.get("from", ""),
            "date_to": request.GET.get("to", ""),
        })



class CustomerCreateView(PermissionRequiredMixin, View):
    permission_code = "customers.create"

    def get(self, request):
        return render(request, "customers/form.html", {
            "form": CustomerForm(), "title": "Add customer",
        })

    def post(self, request):
        form = CustomerForm(request.POST)
        if form.is_valid():
            customer = form.save(commit=False)
            customer.created_by = request.user
            customer.updated_by = request.user
            customer._change_reason = "Created"
            customer.save()
            _warn_duplicates(request, customer)
            messages.success(request, f"Customer '{customer.name}' added.")
            return redirect("customers:detail", pk=customer.pk)
        return render(request, "customers/form.html", {
            "form": form, "title": "Add customer",
        })


class CustomerUpdateView(PermissionRequiredMixin, View):
    permission_code = "customers.edit"

    def get(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)
        form = CustomerForm(instance=customer, require_reason=True)
        return render(request, "customers/form.html", {
            "form": form, "title": f"Edit {customer.name}", "customer": customer,
        })

    def post(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)
        form = CustomerForm(request.POST, instance=customer, require_reason=True)
        if form.is_valid():
            try:
                saved = save_form_with_version(
                    form, request.user, form.cleaned_data["reason"]
                )
            except ConcurrentEditError as exc:
                form.add_error(None, str(exc))
            else:
                _warn_duplicates(request, saved)
                messages.success(request, f"Customer '{saved.name}' updated.")
                return redirect("customers:detail", pk=saved.pk)
        return render(request, "customers/form.html", {
            "form": form, "title": f"Edit {customer.name}", "customer": customer,
        })


def _warn_duplicates(request, customer):
    duplicates = customer.duplicate_phone_customers()
    for other in duplicates:
        url = reverse("customers:detail", args=[other.pk])
        # format_html escapes the customer name (user input) while
        # keeping the link itself as markup; the message template renders
        # SafeString unescaped, so the link is clickable.
        messages.warning(
            request,
            format_html(
                "Same phone as existing customer: <a href='{}'>{}</a>.",
                url, other.name,
            ),
        )


class CustomerDeleteView(PermissionRequiredMixin, View):
    permission_code = "customers.delete"

    def get(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)
        block_reason = _delete_block_reason(customer)
        return render(request, "customers/delete.html", {
            "customer": customer, "block_reason": block_reason,
        })

    def post(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)
        if request.POST.get("action") == "deactivate":
            customer.is_active = False
            customer.updated_by = request.user
            customer._change_reason = "Deactivated instead of deleting"
            customer.save()
            messages.success(request, f"Customer '{customer.name}' deactivated.")
            return redirect("customers:list")
        block_reason = _delete_block_reason(customer)
        if block_reason:
            messages.error(request, block_reason)
            return redirect("customers:detail", pk=pk)
        soft_delete_objects([customer], request.user,
                            request.POST.get("reason", ""))
        messages.success(request, f"Customer '{customer.name}' deleted.")
        return redirect("customers:list")


def _delete_block_reason(customer):
    if customer.sales.exists() or customer.payments.exists():
        return ("This customer has sales or payments on record and cannot be "
                "deleted. Deactivate them instead.")
    allocation = allocate_customer(customer)
    if allocation["balance"] != 0:
        return ("This customer has a non-zero balance and cannot be deleted. "
                "Deactivate them instead.")
    return None


class CustomerSearchFragmentView(PermissionRequiredMixin, View):
    """HTMX: search-as-you-type for the sale form's customer picker."""
    permission_code = "customers.view"

    def get(self, request):
        q = request.GET.get("q", "").strip()
        customers = []
        if q:
            customers = Customer.objects.filter(
                Q(name__icontains=q) | Q(phone__icontains=q)
                | Q(phone__icontains=normalize_phone(q)),
                is_active=True,
            ).order_by("name")[:10]
        return render(request, "customers/_search_results.html", {
            "customers": customers, "q": q,
        })


class CustomerBalanceFragmentView(PermissionRequiredMixin, View):
    """HTMX: current balance for the payment form's customer picker."""
    permission_code = "payments.create"

    def get(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)
        allocation = allocate_customer(customer)
        return render(request, "customers/_balance.html", {
            "customer": customer, "balance": allocation["balance"],
        })


class CustomerImportUploadView(PermissionRequiredMixin, View):
    permission_code = "customers.import"

    def get(self, request):
        return render(request, "customers/import_upload.html", {
            "form": CustomerImportUploadForm(),
        })

    def post(self, request):
        form = CustomerImportUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(request, "customers/import_upload.html", {"form": form})
        try:
            rows = parse_import_file(form.cleaned_data["file"])
        except ValidationError as exc:
            form.add_error("file", exc)
            return render(request, "customers/import_upload.html", {"form": form})
        serializable = [
            {**row, "opening_balance": str(row["opening_balance"])}
            for row in rows
        ]
        request.session["customer_import_rows"] = serializable
        return redirect("customers:import_preview")


class CustomerImportPreviewView(PermissionRequiredMixin, View):
    permission_code = "customers.import"

    def get(self, request):
        rows = request.session.get("customer_import_rows")
        if rows is None:
            messages.error(request, "No import in progress. Upload a file first.")
            return redirect("customers:import_upload")
        savable = sum(1 for row in rows if not row.get("error"))
        errored = len(rows) - savable
        return render(request, "customers/import_preview.html", {
            "rows": rows, "savable": savable, "errored": errored,
        })

    def post(self, request):
        rows = request.session.pop("customer_import_rows", None)
        if rows is None:
            messages.error(request, "No import in progress. Upload a file first.")
            return redirect("customers:import_upload")
        parsed = [
            {**row, "opening_balance": Decimal(str(row["opening_balance"]))}
            for row in rows
        ]
        try:
            saved = save_import_rows(parsed, request.user)
        except (IntegrityError, InvalidOperation, ValidationError) as exc:
            # The save runs in one transaction, so a failure here means
            # nothing was saved. Say so plainly instead of a 500 page.
            messages.error(
                request,
                f"The import could not be saved ({exc}). No customers "
                "were added. Fix the file and try again.")
            return redirect("customers:import_upload")
        errored = sum(1 for row in rows if row.get("error"))
        return render(request, "customers/import_result.html", {
            "saved": saved, "errored": errored,
        })


class CustomerLedgerPdfView(PermissionRequiredMixin, View):
    permission_code = "customers.view"

    def get(self, request, pk):
        from customers.exports import ledger_pdf_response

        customer = get_object_or_404(Customer, pk=pk)
        date_from = parse_date(request.GET.get("from"))
        date_to = parse_date(request.GET.get("to"))
        rows = customer_ledger_entries(customer, date_from, date_to)
        return ledger_pdf_response(customer, rows, date_from, date_to)


class CustomerLedgerExcelView(PermissionRequiredMixin, View):
    permission_code = "customers.view"

    def get(self, request, pk):
        from customers.exports import ledger_excel_response

        customer = get_object_or_404(Customer, pk=pk)
        date_from = parse_date(request.GET.get("from"))
        date_to = parse_date(request.GET.get("to"))
        rows = customer_ledger_entries(customer, date_from, date_to)
        return ledger_excel_response(customer, rows, date_from, date_to)
