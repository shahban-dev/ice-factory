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


def annotate_customer_balances(qs, at_date=None):
    """Annotate a Customer queryset with billed, paid and balance, using
    aggregate queries (no per-row queries, no join multiplication).
    Billed is the sum of NON-deleted sale totals (items minus discount);
    paid is the sum of non-deleted payments. With at_date, only sales
    and payments dated on or before it count, giving the balance as of
    that date. This is the single balance implementation: reports build
    on it (see reports/services.py) instead of recomputing balances."""
    items_sum = (
        SaleItem.objects.filter(sale=OuterRef("pk"))
        .values("sale")
        .annotate(s=Sum(F("quantity") * F("unit_price"), output_field=DecimalField()))
        .values("s")
    )
    sales = Sale.objects.filter(customer=OuterRef("pk"), is_deleted=False)
    payments = Payment.objects.filter(customer=OuterRef("pk"), is_deleted=False)
    if at_date is not None:
        sales = sales.filter(date__lte=at_date)
        payments = payments.filter(date__lte=at_date)
    billed_sq = (
        sales
        .annotate(st=Subquery(items_sum, output_field=DecimalField()))
        .values("customer")
        .annotate(b=Sum(F("st") - F("discount"), output_field=DecimalField()))
        .values("b")
    )
    paid_sq = (
        payments
        .values("customer")
        .annotate(p=Sum("amount"))
        .values("p")
    )
    return qs.annotate(
        billed=Coalesce(Subquery(billed_sq, output_field=DecimalField()), Decimal("0")),
        paid=Coalesce(Subquery(paid_sq, output_field=DecimalField()), Decimal("0")),
    ).annotate(balance=F("opening_balance") + F("billed") - F("paid"))


def allocate_customer(customer, sales=None, payments=None):
    """THE allocation function. Used by the ledger, invoice, customer list
    and reports — nowhere else computes invoice status.

    Two steps, in this order:

    1. Each sale's OWN linked payments (entered on that sale's form)
       apply to that sale first, capped at its total. Any overflow joins
       the pool. So a sale paid in full in cash shows "Paid" even when
       the customer has an older balance.
    2. The pool — general payments, plus overflow from step 1 — pays
       the oldest debt first: the opening balance first, then sales
       ordered by (date, id). A negative opening balance counts as
       extra payment. Money left over is advance credit.

    Customer balance totals never change: balance is always
    opening + billed - paid, whatever the allocation order.
    Returns balance, credit, billed, paid and per-sale allocation/status.

    Callers may pass pre-fetched ``sales`` (with items prefetched,
    ordered by (date, id)) and ``payments`` to avoid one query pair per
    customer — the dues report does this for all debtors at once. The
    computation is identical either way; the lists only skip queries.
    """
    if sales is None:
        sales = list(
            customer.sales.all()
            .prefetch_related("items")
            .order_by("date", "id")
        )
    else:
        sales = sorted(sales, key=lambda s: (s.date, s.id))
    sale_ids = {sale.id for sale in sales}
    # Partition the customer's non-deleted payments: linked to one of
    # this customer's own sales, or general pool money. (A payment whose
    # sale belongs to another customer is pool money here; A3 stops
    # such mismatches from being created.)
    linked_by_sale = {}
    pool = Decimal("0")
    if payments is None:
        payments = list(customer.payments.all())
    for payment in payments:
        if payment.sale_id in sale_ids:
            linked_by_sale[payment.sale_id] = (
                linked_by_sale.get(payment.sale_id, Decimal("0"))
                + payment.amount
            )
        else:
            pool += payment.amount

    opening = customer.opening_balance
    allocated_by_sale = {}
    for sale in sales:
        linked = linked_by_sale.get(sale.id, Decimal("0"))
        take = min(linked, sale.total)
        allocated_by_sale[sale.id] = take
        pool += linked - take

    available = pool + max(Decimal("0"), -opening)
    opening_allocated = Decimal("0")
    if opening > 0:
        opening_allocated = min(opening, available)
        available -= opening_allocated
    for sale in sales:
        room = sale.total - allocated_by_sale[sale.id]
        take = min(room, available)
        allocated_by_sale[sale.id] += take
        available -= take
    credit = available

    per_sale = []
    for sale in sales:
        allocated = allocated_by_sale[sale.id]
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
    payments_total = sum((p.amount for p in payments), Decimal("0"))
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
    if not isinstance(discount, Decimal):
        discount = Decimal(str(discount))
    if not isinstance(paid_now, Decimal):
        paid_now = Decimal(str(paid_now))
    if discount != discount.quantize(Decimal("0.01")):
        raise ValidationError("Discount must have at most 2 decimal places.")
    if paid_now != paid_now.quantize(Decimal("0.01")):
        raise ValidationError(
            "Paid-now amount must have at most 2 decimal places.")
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
    if not isinstance(discount, Decimal):
        discount = Decimal(str(discount))
    if discount != discount.quantize(Decimal("0.01")):
        raise ValidationError("Discount must have at most 2 decimal places.")
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
                    payment.date = date
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

        # A sale's date moves its linked payments to the same date, so
        # daily cash stays on the right day. (The walk-in branch above
        # already set the date on its payment.)
        for payment in linked:
            if payment.date != date:
                payment.date = date
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
                   change_reason="Created", sale=None):
    not_future_date(date, "Payment date")
    if amount <= 0:
        raise ValidationError("Payment amount must be more than zero.")
    if customer is None and sale is None:
        raise ValidationError(
            "A standalone payment needs a customer. A payment with no "
            "customer is only possible on a walk-in sale, recorded on "
            "the sale form."
        )
    payment = Payment(
        customer=customer, sale=sale, date=date, amount=amount,
        method=method, reference=reference,
        created_by=user, updated_by=user,
    )
    payment._change_reason = change_reason
    payment.save()
    return payment


def update_payment(payment, user, date, amount, method, reference, reason,
                   form_version):
    """Edit a payment. The customer can never change here (delete and
    re-enter instead) — update_payment takes no customer argument at all,
    so a payment can never drift away from its sale's customer. A
    payment linked to a walk-in sale has its amount locked: it follows
    the sale total through sale edit. A payment linked to a credit sale
    may change amount, with a reason (the edit form requires one)."""
    not_future_date(date, "Payment date")
    if amount <= 0:
        raise ValidationError("Payment amount must be more than zero.")
    with transaction.atomic():
        locked = Payment.all_objects.select_for_update().get(pk=payment.pk)
        check_version(locked, form_version)
        if locked.sale_id is not None:
            sale = Sale.all_objects.select_for_update().get(pk=locked.sale_id)
            if sale.customer_id is None and amount != locked.amount:
                raise ValidationError(
                    "This payment belongs to a walk-in sale and its amount "
                    "cannot be changed here. Edit the sale instead — the "
                    "payment follows the sale total."
                )
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
