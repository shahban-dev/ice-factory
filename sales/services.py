"""Sales services: invoice numbers, the allocation function, and all
multi-step sale/payment operations. Every operation runs in a transaction
and computes totals on the server from stored rows, never from the browser.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import DecimalField, F, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from core.models import InvoiceCounter, get_settings
from core.services import check_version, soft_delete_objects
from sales.models import Payment, Sale, SaleItem


def not_future_date(value, field_name="Date"):
    if value and value > timezone.localdate():
        raise ValidationError(f"{field_name} cannot be in the future.")


def generate_invoice_number(sale_date):
    """INV-YYYY-0001. Call inside a transaction: the counter row for the
    year is locked with select_for_update, so concurrent saves cannot
    collide. Numbers of deleted sales are never reused."""
    prefix = get_settings().invoice_prefix or "INV"
    year = sale_date.year
    counter, _ = InvoiceCounter.objects.select_for_update().get_or_create(
        year=year
    )
    counter.last_number += 1
    counter.save(update_fields=["last_number"])
    return f"{prefix}-{year}-{counter.last_number:04d}"


def annotate_sale_totals(qs):
    """Annotate a Sale queryset with subtotal and total, computed from
    stored items (never trusted from the browser)."""
    items_sum = (
        SaleItem.objects.filter(sale=OuterRef("pk"))
        .values("sale")
        .annotate(s=Sum(F("quantity") * F("unit_price"), output_field=DecimalField()))
        .values("s")
    )
    return qs.annotate(
        subtotal_annotated=Coalesce(
            Subquery(items_sum, output_field=DecimalField()), Decimal("0")
        )
    ).annotate(total_annotated=F("subtotal_annotated") - F("discount"))


def annotate_customer_balances(qs):
    """Annotate a Customer queryset with billed, paid and balance, using
    aggregate queries (no per-row queries, no join multiplication)."""
    items_sum = (
        SaleItem.objects.filter(sale=OuterRef("pk"))
        .values("sale")
        .annotate(s=Sum(F("quantity") * F("unit_price"), output_field=DecimalField()))
        .values("s")
    )
    billed_sq = (
        Sale.objects.filter(customer=OuterRef("pk"), is_deleted=False)
        .annotate(st=Subquery(items_sum, output_field=DecimalField()))
        .values("customer")
        .annotate(b=Sum(F("st") - F("discount"), output_field=DecimalField()))
        .values("b")
    )
    paid_sq = (
        Payment.objects.filter(customer=OuterRef("pk"), is_deleted=False)
        .values("customer")
        .annotate(p=Sum("amount"))
        .values("p")
    )
    return qs.annotate(
        billed=Coalesce(Subquery(billed_sq, output_field=DecimalField()), Decimal("0")),
        paid=Coalesce(Subquery(paid_sq, output_field=DecimalField()), Decimal("0")),
    ).annotate(balance=F("opening_balance") + F("billed") - F("paid"))


def allocate_customer(customer):
    """THE allocation function. Used by the ledger, invoice, customer list
    and reports — nowhere else computes invoice status.

    Pool all of the customer's non-deleted payments and apply them to the
    oldest debt first: the opening balance first, then sales ordered by
    (date, id). A negative opening balance counts as extra payment. Money
    left over is advance credit.

    Returns balance, credit, billed, paid and per-sale allocation/status.
    """
    sales = list(
        customer.sales.all()
        .prefetch_related("items", "payments")
        .order_by("date", "id")
    )
    payments_total = (
        customer.payments.aggregate(t=Sum("amount"))["t"] or Decimal("0")
    )
    opening = customer.opening_balance
    available = payments_total + max(Decimal("0"), -opening)

    debts = []
    if opening > 0:
        debts.append(("opening", opening))
    for sale in sales:
        debts.append((sale, sale.total))

    allocated_by_sale = {}
    opening_allocated = Decimal("0")
    remaining = available
    for kind, amount in debts:
        take = min(amount, remaining)
        if kind == "opening":
            opening_allocated = take
        else:
            allocated_by_sale[kind.id] = take
        remaining -= take
    credit = remaining

    per_sale = []
    for sale in sales:
        allocated = allocated_by_sale.get(sale.id, Decimal("0"))
        total = sale.total
        if allocated >= total:
            status = "paid"
        elif allocated > 0:
            status = "partial"
        else:
            status = "unpaid"
        per_sale.append(
            {
                "sale": sale,
                "allocated": allocated,
                "remaining": total - allocated,
                "status": status,
            }
        )

    billed = sum((s.total for s in sales), Decimal("0"))
    balance = opening + billed - payments_total
    return {
        "balance": balance,
        "credit": credit,
        "billed": billed,
        "paid": payments_total,
        "opening": opening,
        "opening_allocated": opening_allocated,
        "opening_remaining": max(Decimal("0"), opening) - opening_allocated,
        "sales": per_sale,
    }


def _validate_items(items_data):
    if not items_data:
        raise ValidationError("A sale needs at least one item.")
    subtotal = Decimal("0")
    for item in items_data:
        product = item["product"]
        if not product.is_active:
            raise ValidationError(f"Product '{product}' is deactivated.")
        if item["quantity"] <= 0:
            raise ValidationError("Quantity must be more than zero.")
        if item["unit_price"] < 0:
            raise ValidationError("Price cannot be negative.")
        subtotal += item["quantity"] * item["unit_price"]
    return subtotal


def create_sale(user, date, customer, discount, items_data, paid_now,
                paid_method, notes="", change_reason="Created"):
    """Create a sale with items and an optional paid-now payment, in one
    transaction. Walk-in sales must be fully paid at the time of sale."""
    not_future_date(date, "Sale date")
    subtotal = _validate_items(items_data)
    if discount < 0 or discount > subtotal:
        raise ValidationError("Discount must be between 0 and the subtotal.")
    total = subtotal - discount
    if total <= 0:
        raise ValidationError("Sale total must be more than zero.")
    if paid_now < 0 or paid_now > total:
        raise ValidationError("Paid-now amount cannot exceed the sale total.")
    if customer is None and paid_now != total:
        raise ValidationError("A walk-in sale must be fully paid at the time of sale.")

    with transaction.atomic():
        sale = Sale(
            invoice_number=generate_invoice_number(date),
            date=date, customer=customer, discount=discount, notes=notes,
            created_by=user, updated_by=user,
        )
        sale._change_reason = change_reason
        sale.save()
        for item in items_data:
            sale_item = SaleItem(
                sale=sale, product=item["product"],
                quantity=item["quantity"], unit_price=item["unit_price"],
                created_by=user, updated_by=user,
            )
            sale_item._change_reason = change_reason
            sale_item.save()
        if paid_now > 0:
            payment = Payment(
                customer=customer, sale=sale, date=date,
                amount=paid_now, method=paid_method,
                reference="Paid with sale",
                created_by=user, updated_by=user,
            )
            payment._change_reason = change_reason
            payment.save()
    return sale


def update_sale(sale, user, date, customer, discount, items_data, notes,
                reason, form_version):
    """Edit a sale: items are replaced in one transaction. Returns
    (sale, balance_negative_warning). Raises ValidationError on bad data
    and ConcurrentEditError on a stale version."""
    not_future_date(date, "Sale date")
    subtotal = _validate_items(items_data)
    if discount < 0 or discount > subtotal:
        raise ValidationError("Discount must be between 0 and the subtotal.")
    total = subtotal - discount
    if total <= 0:
        raise ValidationError("Sale total must be more than zero.")

    with transaction.atomic():
        locked = Sale.all_objects.select_for_update().get(pk=sale.pk)
        check_version(locked, form_version)
        old_customer = locked.customer
        old_is_walk_in = locked.customer_id is None
        linked = list(locked.payments.all())
        linked_sum = sum((p.amount for p in linked), Decimal("0"))

        if customer is None and not old_is_walk_in:
            # Converting a customer sale to walk-in: it must already be
            # fully paid by its own linked payments, exactly — any excess
            # would have nowhere to go (no customer to hold credit).
            if linked_sum != total:
                raise ValidationError(
                    "Cannot make this a walk-in sale unless it is fully paid: "
                    "its linked payments do not equal the new total."
                )

        locked.date = date
        locked.customer = customer
        locked.discount = discount
        locked.notes = notes
        locked.updated_by = user
        locked._change_reason = reason
        locked.save()

        # Replace items (SaleItem has no soft delete; history tracks this).
        locked.items.all().delete()
        for item in items_data:
            sale_item = SaleItem(
                sale=locked, product=item["product"],
                quantity=item["quantity"], unit_price=item["unit_price"],
                created_by=user, updated_by=user,
            )
            sale_item._change_reason = reason
            sale_item.save()

        if customer is None:
            if old_is_walk_in:
                # Staying walk-in: the single linked payment follows the total.
                if len(linked) == 1:
                    payment = linked[0]
                    payment.amount = total
                    payment.customer = None
                    payment.updated_by = user
                    payment._change_reason = reason
                    payment.save()
                elif len(linked) == 0:
                    raise ValidationError(
                        "This walk-in sale has no linked payment. Restore "
                        "its payment from the recycle bin first."
                    )
                else:
                    raise ValidationError(
                        "This walk-in sale has more than one linked payment "
                        "and cannot be adjusted automatically."
                    )
            else:
                # Converting to walk-in: detach the linked payments from
                # the customer (their sum already equals the total).
                for payment in linked:
                    payment.customer = None
                    payment.updated_by = user
                    payment._change_reason = reason
                    payment.save()
        elif old_customer != customer:
            # Changing the customer moves its linked payments along.
            for payment in linked:
                payment.customer = customer
                payment.updated_by = user
                payment._change_reason = reason
                payment.save()

        warning = False
        if customer is not None:
            allocation = allocate_customer(customer)
            warning = allocation["balance"] < 0
    return locked, warning


def delete_sale(sale, user, reason=""):
    """Soft-delete a sale and the payments entered with it, sharing one
    delete_batch. Payments recorded later on the customer's account are
    never deleted by this. Returns (batch, linked_payments_total)."""
    with transaction.atomic():
        payments = list(sale.payments.all())
        total = sum((p.amount for p in payments), Decimal("0"))
        batch = soft_delete_objects([sale] + payments, user, reason)
    return batch, total


def create_payment(user, customer, date, amount, method, reference="",
                   change_reason="Created"):
    not_future_date(date, "Payment date")
    if amount <= 0:
        raise ValidationError("Payment amount must be more than zero.")
    payment = Payment(
        customer=customer, date=date, amount=amount,
        method=method, reference=reference,
        created_by=user, updated_by=user,
    )
    payment._change_reason = change_reason
    payment.save()
    return payment


def update_payment(payment, user, date, amount, method, reference, reason,
                   form_version):
    not_future_date(date, "Payment date")
    if amount <= 0:
        raise ValidationError("Payment amount must be more than zero.")
    with transaction.atomic():
        locked = Payment.all_objects.select_for_update().get(pk=payment.pk)
        check_version(locked, form_version)
        locked.date = date
        locked.amount = amount
        locked.method = method
        locked.reference = reference
        locked.updated_by = user
        locked._change_reason = reason
        locked.save()
    return locked


def delete_payment(payment, user, reason=""):
    return soft_delete_objects([payment], user, reason)


def customer_ledger_entries(customer, date_from=None, date_to=None):
    """Opening balance, then every sale and payment in date order
    (tie-break by created_at) with a running balance. With a date filter,
    the first row is the balance at the start of the period (opening plus
    everything before it), so the running balance stays correct."""
    all_sales = customer.sales.all()
    all_payments = customer.payments.all()

    start = customer.opening_balance
    if date_from:
        for sale in all_sales.filter(date__lt=date_from).prefetch_related("items"):
            start += sale.total
        paid_before = (
            all_payments.filter(date__lt=date_from).aggregate(t=Sum("amount"))["t"]
            or Decimal("0")
        )
        start -= paid_before

    sales = all_sales
    payments = all_payments
    if date_from:
        sales = sales.filter(date__gte=date_from)
        payments = payments.filter(date__gte=date_from)
    if date_to:
        sales = sales.filter(date__lte=date_to)
        payments = payments.filter(date__lte=date_to)

    entries = []
    for sale in sales.prefetch_related("items"):
        entries.append(
            {"kind": "sale", "date": sale.date, "created_at": sale.created_at,
             "ref": sale.invoice_number, "sale": sale, "amount": sale.total}
        )
    for payment in payments:
        entries.append(
            {"kind": "payment", "date": payment.date,
             "created_at": payment.created_at, "ref": "Payment",
             "payment": payment, "amount": -payment.amount}
        )
    entries.sort(key=lambda e: (e["date"], e["created_at"]))
    running = start
    label = "Opening balance" if not date_from else "Balance at start of period"
    rows = [{"kind": "opening", "date": None, "ref": label,
             "amount": None, "balance": running}]
    for entry in entries:
        running += entry["amount"]
        entry["balance"] = running
        rows.append(entry)
    return rows
