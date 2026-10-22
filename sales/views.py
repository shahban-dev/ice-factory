"""Product, sale, payment and invoice views."""

import uuid
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import DecimalField, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import ListView

from core.permissions import PermissionRequiredMixin
from core.params import parse_int
from core.models import get_settings
from core.services import (
    ConcurrentEditError,
    check_version,
    claim_form_token,
    finish_form_token,
)
from core.whatsapp import invoice_message, whatsapp_url
from customers.models import Customer
from sales.forms import PaymentForm, ProductForm, SaleForm, SaleItemFormSet
from sales.models import Payment, Product, Sale
from sales.services import (
    allocate_customer,
    annotate_sale_totals,
    create_payment,
    create_sale,
    delete_payment,
    delete_sale,
    update_payment,
    update_sale,
)


def _formset_items_data(formset):
    items = []
    for form in formset.forms:
        cleaned = form.cleaned_data
        if cleaned.get("DELETE"):
            continue
        product = cleaned.get("product")
        quantity = cleaned.get("quantity")
        price = cleaned.get("unit_price")
        if product and quantity and price is not None:
            items.append({
                "product": product, "quantity": quantity, "unit_price": price,
            })
    return items


class ProductListView(PermissionRequiredMixin, ListView):
    permission_code = "products.manage"
    model = Product
    template_name = "sales/product_list.html"
    context_object_name = "products"
    paginate_by = 25

    def get_queryset(self):
        qs = Product.objects.all()
        status = self.request.GET.get("status", "")
        if status == "active":
            qs = qs.filter(is_active=True)
        elif status == "inactive":
            qs = qs.filter(is_active=False)
        return qs.order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status"] = self.request.GET.get("status", "")
        return context


class ProductCreateView(PermissionRequiredMixin, View):
    permission_code = "products.manage"

    def get(self, request):
        return render(request, "sales/product_form.html", {
            "form": ProductForm(), "title": "Add product",
        })

    def post(self, request):
        form = ProductForm(request.POST)
        if form.is_valid():
            product = form.save(commit=False)
            product.created_by = request.user
            product.updated_by = request.user
            product._change_reason = "Created"
            product.save()
            messages.success(request, f"Product '{product.name}' added.")
            return redirect("sales:product_list")
        return render(request, "sales/product_form.html", {
            "form": form, "title": "Add product",
        })


class ProductUpdateView(PermissionRequiredMixin, View):
    permission_code = "products.manage"

    def get(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        return render(request, "sales/product_form.html", {
            "form": ProductForm(instance=product),
            "title": f"Edit {product.name}", "product": product,
        })

    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        form = ProductForm(request.POST, instance=product)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.updated_by = request.user
            updated._change_reason = request.POST.get("reason", "") or "Edited"
            updated.save()
            messages.success(request, f"Product '{updated.name}' updated.")
            return redirect("sales:product_list")
        return render(request, "sales/product_form.html", {
            "form": form, "title": f"Edit {product.name}", "product": product,
        })


class ProductToggleActiveView(PermissionRequiredMixin, View):
    permission_code = "products.manage"

    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        product.is_active = not product.is_active
        product.updated_by = request.user
        product._change_reason = (
            "Deactivated" if not product.is_active else "Reactivated"
        )
        product.save()
        state = "deactivated" if not product.is_active else "reactivated"
        messages.success(request, f"Product '{product.name}' {state}.")
        return redirect("sales:product_list")


class SaleListView(PermissionRequiredMixin, ListView):
    permission_code = "sales.view"
    model = Sale
    template_name = "sales/sale_list.html"
    context_object_name = "sales"
    paginate_by = 25

    def get_queryset(self):
        qs = Sale.objects.select_related("customer").prefetch_related("items")
        qs = annotate_sale_totals(qs)
        received_sq = (
            Payment.objects.filter(sale=OuterRef("pk"), is_deleted=False)
            .values("sale")
            .annotate(s=Sum("amount"))
            .values("s")
        )
        qs = qs.annotate(
            received=Coalesce(
                Subquery(received_sq, output_field=DecimalField()), Decimal("0")
            )
        )
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(invoice_number__icontains=q) | Q(customer__name__icontains=q)
            )
        customer_id = parse_int(self.request.GET.get("customer", ""))
        if customer_id:
            qs = qs.filter(customer_id=customer_id)
        return qs.order_by("-date", "-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.request.GET.get("q", "")
        context["customers"] = Customer.objects.filter(is_active=True).order_by("name")
        context["selected_customer"] = self.request.GET.get("customer", "")
        return context


def _sale_form_context(form, formset, preselected_customer=None):
    products = Product.objects.filter(is_active=True).order_by("name")
    return {
        "form": form,
        "formset": formset,
        "product_prices": {str(p.pk): str(p.default_price) for p in products},
        "preselected_customer": preselected_customer,
    }


def _preselected_customer(request, form=None):
    customer_id = request.GET.get("customer") or request.POST.get("customer")
    if not customer_id:
        if form is not None and getattr(form.instance, "customer_id", None):
            return form.instance.customer
        return None
    try:
        return Customer.objects.get(pk=customer_id)
    except (Customer.DoesNotExist, ValueError):
        return None


class SaleCreateView(PermissionRequiredMixin, View):
    permission_code = "sales.create"

    def get(self, request):
        preselected = _preselected_customer(request)
        initial = {"form_token": str(uuid.uuid4())}
        if preselected:
            initial["customer"] = preselected.pk
        context = _sale_form_context(
            SaleForm(initial=initial), SaleItemFormSet(instance=Sale()),
            preselected_customer=preselected,
        )
        context["title"] = "New sale"
        return render(request, "sales/sale_form.html", context)

    def post(self, request):
        form = SaleForm(request.POST)
        formset = SaleItemFormSet(request.POST, instance=Sale())
        if form.is_valid() and formset.is_valid():
            try:
                with transaction.atomic():
                    record, is_new = claim_form_token(
                        request.user, form.cleaned_data.get("form_token", ""))
                    if not is_new and record.success_url:
                        messages.info(
                            request,
                            "This sale was already saved — showing the "
                            "original instead of saving it twice.")
                        return redirect(record.success_url)
                    sale = create_sale(
                        user=request.user,
                        date=form.cleaned_data["date"],
                        customer=form.cleaned_data["customer"],
                        discount=form.cleaned_data["discount"] or 0,
                        items_data=_formset_items_data(formset),
                        paid_now=form.cleaned_data["paid_now"] or 0,
                        paid_method=form.cleaned_data["paid_method"],
                        notes=form.cleaned_data["notes"],
                    )
                    action = request.POST.get("action", "save")
                    if action == "save_and_print":
                        url = (f"{reverse('sales:invoice', args=[sale.pk])}"
                               "?autoprint=1")
                    elif action == "save_and_new":
                        url = reverse("sales:sale_create")
                    else:
                        url = reverse("sales:sale_detail", args=[sale.pk])
                    finish_form_token(record, url)
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(
                    request, f"Sale {sale.invoice_number} saved.")
                return redirect(url)
        context = _sale_form_context(
            form, formset, preselected_customer=_preselected_customer(request))
        context["title"] = "New sale"
        return render(request, "sales/sale_form.html", context)


class SaleUpdateView(PermissionRequiredMixin, View):
    permission_code = "sales.edit"

    def get(self, request, pk):
        sale = get_object_or_404(Sale, pk=pk)
        form = SaleForm(instance=sale, require_reason=True)
        formset = SaleItemFormSet(instance=sale)
        context = _sale_form_context(
            form, formset, preselected_customer=sale.customer)
        context["title"] = f"Edit {sale.invoice_number}"
        context["sale"] = sale
        return render(request, "sales/sale_form.html", context)

    def post(self, request, pk):
        sale = get_object_or_404(Sale, pk=pk)
        form = SaleForm(request.POST, instance=sale, require_reason=True)
        formset = SaleItemFormSet(request.POST, instance=sale)
        if form.is_valid():
            try:
                # Check the version BEFORE the formset: saving a sale
                # replaces its items with new rows, so a second admin's
                # form always carries dead item ids and would fail
                # formset validation first — hiding the stale-version
                # message behind an error the template never renders.
                # The locked check inside update_sale still guards the
                # actual save; this early check only surfaces the
                # friendly message.
                check_version(sale, form.cleaned_data.get("version"))
            except ConcurrentEditError as exc:
                form.add_error(None, str(exc))
            else:
                if formset.is_valid():
                    try:
                        updated, warning = update_sale(
                            sale=sale,
                            user=request.user,
                            date=form.cleaned_data["date"],
                            customer=form.cleaned_data["customer"],
                            discount=form.cleaned_data["discount"] or 0,
                            items_data=_formset_items_data(formset),
                            notes=form.cleaned_data["notes"],
                            reason=form.cleaned_data["reason"],
                            form_version=form.cleaned_data.get("version"),
                        )
                    except (ValidationError, ConcurrentEditError) as exc:
                        form.add_error(None, str(exc) if isinstance(exc, ConcurrentEditError) else exc)
                    else:
                        if warning:
                            messages.warning(
                                request,
                                "Warning: this edit makes the customer's balance "
                                "negative (advance credit).")
                        messages.success(request, f"Sale {updated.invoice_number} updated.")
                        if request.POST.get("action") == "save_and_print":
                            return redirect(f"{reverse('sales:invoice', args=[updated.pk])}?autoprint=1")
                        return redirect("sales:sale_detail", pk=updated.pk)
        context = _sale_form_context(
            form, formset, preselected_customer=_preselected_customer(request, form))
        context["title"] = f"Edit {sale.invoice_number}"
        context["sale"] = sale
        return render(request, "sales/sale_form.html", context)


class SaleDetailView(PermissionRequiredMixin, View):
    permission_code = "sales.view"

    def get(self, request, pk):
        sale = get_object_or_404(
            Sale.all_objects.select_related("customer").prefetch_related(
                "items__product", "payments"
            ),
            pk=pk,
        )
        allocation = None
        remaining = None
        status = None
        whatsapp_invoice_url = None
        if sale.customer is not None:
            allocation = allocate_customer(sale.customer)
            for entry in allocation["sales"]:
                if entry["sale"].id == sale.id:
                    remaining = entry["remaining"]
                    status = entry["status"]
            whatsapp_invoice_url = whatsapp_url(
                sale.customer.phone,
                invoice_message(
                    get_settings().factory_name, sale, remaining))
        return render(request, "sales/sale_detail.html", {
            "sale": sale,
            "allocation": allocation,
            "remaining": remaining,
            "status": status,
            "whatsapp_invoice_url": whatsapp_invoice_url,
        })


class SaleDeleteView(PermissionRequiredMixin, View):
    permission_code = "sales.delete"

    def get(self, request, pk):
        sale = get_object_or_404(Sale, pk=pk)
        linked_total = sum(
            (p.amount for p in sale.payments.all()), start=0
        )
        return render(request, "sales/sale_delete.html", {
            "sale": sale, "linked_total": linked_total,
        })

    def post(self, request, pk):
        sale = get_object_or_404(Sale, pk=pk)
        _, linked_total = delete_sale(
            sale, request.user, request.POST.get("reason", "")
        )
        messages.success(
            request,
            f"Sale {sale.invoice_number} deleted "
            f"(linked payments of Rs {linked_total} also removed).")
        return redirect("sales:sale_list")


class InvoiceView(PermissionRequiredMixin, View):
    permission_code = "sales.view"

    def get(self, request, pk):
        sale = get_object_or_404(
            Sale.all_objects.select_related("customer").prefetch_related(
                "items__product", "payments"
            ),
            pk=pk,
        )
        remaining = None
        outstanding = None
        whatsapp_invoice_url = None
        if sale.customer is not None:
            allocation = allocate_customer(sale.customer)
            outstanding = allocation["balance"]
            for entry in allocation["sales"]:
                if entry["sale"].id == sale.id:
                    remaining = entry["remaining"]
            whatsapp_invoice_url = whatsapp_url(
                sale.customer.phone,
                invoice_message(
                    get_settings().factory_name, sale, remaining))
        return render(request, "sales/invoice.html", {
            "sale": sale,
            "remaining": remaining,
            "outstanding": outstanding,
            "autoprint": request.GET.get("autoprint") == "1",
            "whatsapp_invoice_url": whatsapp_invoice_url,
        })


class InvoicePdfView(PermissionRequiredMixin, View):
    permission_code = "sales.view"

    def get(self, request, pk):
        from sales.invoice_pdf import invoice_pdf_response

        sale = get_object_or_404(
            Sale.all_objects.select_related("customer").prefetch_related(
                "items__product", "payments"
            ),
            pk=pk,
        )
        remaining = None
        outstanding = None
        if sale.customer is not None:
            allocation = allocate_customer(sale.customer)
            outstanding = allocation["balance"]
            for entry in allocation["sales"]:
                if entry["sale"].id == sale.id:
                    remaining = entry["remaining"]
        return invoice_pdf_response(sale, remaining, outstanding)


class PaymentListView(PermissionRequiredMixin, ListView):
    permission_code = "payments.view"
    model = Payment
    template_name = "sales/payment_list.html"
    context_object_name = "payments"
    paginate_by = 25

    def get_queryset(self):
        qs = Payment.objects.select_related("customer", "sale")
        customer_id = parse_int(self.request.GET.get("customer", ""))
        if customer_id:
            qs = qs.filter(customer_id=customer_id)
        return qs.order_by("-date", "-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["customers"] = Customer.objects.filter(is_active=True).order_by("name")
        context["selected_customer"] = self.request.GET.get("customer", "")
        return context


class PaymentCreateView(PermissionRequiredMixin, View):
    permission_code = "payments.create"

    def get(self, request):
        initial = {"form_token": str(uuid.uuid4())}
        customer_id = request.GET.get("customer")
        if customer_id:
            try:
                initial["customer"] = Customer.objects.get(pk=customer_id).pk
            except (Customer.DoesNotExist, ValueError):
                pass
        return render(request, "sales/payment_form.html", {
            "form": PaymentForm(initial=initial), "title": "Record payment",
        })

    def post(self, request):
        form = PaymentForm(request.POST)
        if form.is_valid():
            customer = form.cleaned_data["customer"]
            if customer is None:
                # A standalone payment with no customer used to save and
                # then crash on the redirect, leaving an orphan payment
                # counted as collected cash. Refuse it here instead.
                form.add_error(
                    "customer",
                    "Choose a customer. A payment with no customer is "
                    "only possible on a walk-in sale, recorded on the "
                    "sale form.",
                )
            else:
                try:
                    with transaction.atomic():
                        record, is_new = claim_form_token(
                            request.user,
                            form.cleaned_data.get("form_token", ""))
                        if not is_new and record.success_url:
                            messages.info(
                                request,
                                "This payment was already recorded — "
                                "showing the original instead of recording "
                                "it twice.")
                            return redirect(record.success_url)
                        payment = create_payment(
                            user=request.user,
                            customer=customer,
                            date=form.cleaned_data["date"],
                            amount=form.cleaned_data["amount"],
                            method=form.cleaned_data["method"],
                            reference=form.cleaned_data["reference"],
                        )
                        url = reverse(
                            "customers:detail", args=[payment.customer.pk])
                        finish_form_token(record, url)
                except ValidationError as exc:
                    form.add_error(None, exc)
                else:
                    allocation = allocate_customer(payment.customer)
                    if allocation["balance"] < 0:
                        messages.warning(
                            request,
                            "This payment is more than the balance. The excess "
                            "is kept as advance credit.")
                    messages.success(request, "Payment recorded.")
                    return redirect(url)
        return render(request, "sales/payment_form.html", {
            "form": form, "title": "Record payment",
        })


def _lock_payment_fields(form, payment):
    """A3: the customer of a payment can never change on edit (delete
    and re-enter instead), so the field is disabled. A walk-in sale's
    payment amount is locked too — it follows the sale total through
    sale edit. The service enforces both rules as well, so a crafted
    request cannot bypass the disabled fields."""
    form.fields["customer"].disabled = True
    if (payment.sale_id is not None and payment.sale is not None
            and payment.sale.customer_id is None):
        form.fields["amount"].disabled = True


class PaymentUpdateView(PermissionRequiredMixin, View):
    permission_code = "payments.edit"

    def get(self, request, pk):
        payment = get_object_or_404(Payment, pk=pk)
        form = PaymentForm(instance=payment, require_reason=True)
        _lock_payment_fields(form, payment)
        return render(request, "sales/payment_form.html", {
            "form": form, "title": "Edit payment", "payment": payment,
        })

    def post(self, request, pk):
        payment = get_object_or_404(Payment, pk=pk)
        form = PaymentForm(request.POST, instance=payment, require_reason=True)
        _lock_payment_fields(form, payment)
        if form.is_valid():
            try:
                saved = update_payment(
                    payment, request.user,
                    form.cleaned_data["date"],
                    form.cleaned_data["amount"],
                    form.cleaned_data["method"],
                    form.cleaned_data["reference"],
                    form.cleaned_data["reason"],
                    form.cleaned_data.get("version"),
                )
            except (ValidationError, ConcurrentEditError) as exc:
                form.add_error(
                    None,
                    str(exc) if isinstance(exc, ConcurrentEditError) else exc,
                )
            else:
                messages.success(request, "Payment updated.")
                target = (
                    saved.customer.pk if saved.customer
                    else saved.sale.customer.pk if saved.sale and saved.sale.customer
                    else None
                )
                if target:
                    return redirect("customers:detail", pk=target)
                return redirect("sales:payment_list")
        return render(request, "sales/payment_form.html", {
            "form": form, "title": "Edit payment", "payment": payment,
        })


class PaymentDeleteView(PermissionRequiredMixin, View):
    permission_code = "payments.delete"

    def get(self, request, pk):
        payment = get_object_or_404(Payment, pk=pk)
        return render(request, "sales/payment_delete.html", {"payment": payment})

    def post(self, request, pk):
        payment = get_object_or_404(Payment, pk=pk)
        delete_payment(payment, request.user, request.POST.get("reason", ""))
        messages.success(request, "Payment deleted.")
        return redirect("sales:payment_list")
