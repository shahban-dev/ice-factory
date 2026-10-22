"""Report computations. The definitions below are printed on every report:

- Billed = sum of sale totals by sale date (opening balances NOT billed).
- Collected = sum of payments by payment date (incl. toward opening balances).
- Expenses = sum of expenses by expense date incl. salary payments.
- Sales profit = Billed - Expenses.
- Cash profit = Collected - Expenses.
- Customer balance = opening_balance + sale totals - payments
  (positive = owes, negative = advance credit).
"""

import calendar
from datetime import date
from decimal import Decimal

from django.db.models import DecimalField, F, Max, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from customers.models import Customer
from core.params import parse_int
from employees.models import Payroll
from expenses.models import Expense
from sales.models import Payment, Sale, SaleItem
from sales.services import (
    allocate_customer,
    annotate_customer_balances,
    annotate_sale_totals,
)


def billed_between(start, end):
    """ONE source of truth for billed in a date range: the sum of
    NON-deleted sale totals (items minus discount). Sale.objects is the
    default manager, which hides soft-deleted sales, so a deleted sale's
    lines can never leak in — SaleItem itself carries no soft-delete
    flag, which is exactly how the old item-sum code went wrong."""
    total = (
        annotate_sale_totals(
            Sale.objects.filter(date__gte=start, date__lte=end)
        ).aggregate(
            total=Sum("total_annotated", output_field=DecimalField())
        )["total"]
    )
    return total or Decimal("0")


def balances_at(at_date=None):
    """Customers with balance as of a date (or today if None), from the
    same logic as annotate_customer_balances. The billed_to_date /
    paid_to_date / balance_at names are kept for callers that use them;
    they are the same values as billed / paid / balance."""
    qs = annotate_customer_balances(Customer.objects.all(), at_date=at_date)
    for customer in qs:
        customer.balance_at = customer.balance
        customer.billed_to_date = customer.billed
        customer.paid_to_date = customer.paid
    return qs


def total_outstanding(at_date=None):
    """Sum of positive customer balances (dues owed to the factory)."""
    total = Decimal("0")
    for customer in balances_at(at_date):
        if customer.balance_at > 0:
            total += customer.balance_at
    return total


def _sum_payments_between(start, end):
    totals = Payment.objects.filter(date__gte=start, date__lte=end).aggregate(
        total=Sum("amount")
    )
    return totals["total"] or Decimal("0")


def _sum_expenses_between(start, end):
    totals = Expense.objects.filter(date__gte=start, date__lte=end).aggregate(
        total=Sum("amount")
    )
    return totals["total"] or Decimal("0")


def month_figures(year, month):
    """Billed, collected, expenses, profits for one calendar month."""
    first, last = date(year, month, 1), date(
        year, month, calendar.monthrange(year, month)[1]
    )
    billed = billed_between(first, last)
    collected = _sum_payments_between(first, last)
    expenses = _sum_expenses_between(first, last)
    return {
        "billed": billed,
        "collected": collected,
        "expenses": expenses,
        "sales_profit": billed - expenses,
        "cash_profit": collected - expenses,
        "first": first,
        "last": last,
    }


def dashboard_data():
    """Everything the dashboard needs, in one place."""
    today = timezone.localdate()
    month = month_figures(today.year, today.month)
    # Last 6 months including the current one, oldest first.
    chart_months = []
    chart_billed, chart_collected, chart_expenses = [], [], []
    y, m = today.year, today.month
    for _ in range(6):
        figures = month_figures(y, m)
        chart_months.append(f"{calendar.month_abbr[m]} {y}")
        chart_billed.append(str(figures["billed"]))
        chart_collected.append(str(figures["collected"]))
        chart_expenses.append(str(figures["expenses"]))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    chart_months.reverse()
    chart_billed.reverse()
    chart_collected.reverse()
    chart_expenses.reverse()
    # Top 5 debtors.
    debtors = [
        c for c in annotate_customer_balances(Customer.objects.all())
        if c.balance > 0
    ]
    debtors.sort(key=lambda c: c.balance, reverse=True)
    return {
        "today": today,
        "today_billed": billed_between(today, today),
        "today_collected": _sum_payments_between(today, today),
        "total_outstanding": total_outstanding(),
        "month": month,
        "chart_months": chart_months,
        "chart_billed": chart_billed,
        "chart_collected": chart_collected,
        "chart_expenses": chart_expenses,
        "top_debtors": debtors[:5],
        "activity": today_activity(),
    }


def today_activity():
    """Sales, payments and expenses dated today, newest first."""
    today = timezone.localdate()
    items = []
    for sale in Sale.objects.filter(date=today).select_related("customer"):
        items.append({
            "kind": "Sale", "when": sale.date, "text":
            f"{sale.invoice_number} — "
            f"{sale.customer.name if sale.customer else 'Walk-in'}",
            "amount": sale.total, "url": f"/sales/{sale.pk}/",
        })
    for payment in Payment.objects.filter(date=today).select_related("customer"):
        items.append({
            "kind": "Payment", "when": payment.date, "text":
            f"{payment.customer.name if payment.customer else 'Walk-in'} — "
            f"{payment.get_method_display()}",
            "amount": payment.amount, "url": "/sales/payments/",
        })
    for expense in Expense.objects.filter(date=today).select_related("category"):
        items.append({
            "kind": "Expense", "when": expense.date, "text":
            f"{expense.category.name} — {expense.description or '—'}",
            "amount": -expense.amount, "url": "/expenses/",
        })
    items.sort(key=lambda i: str(i["when"]), reverse=True)
    return items[:20]


def monthly_report(year, month):
    """Full monthly report, with the definitions printed on the page."""
    figures = month_figures(year, month)
    first, last = figures["first"], figures["last"]
    # Expenses by category.
    by_category = (
        Expense.objects.filter(date__gte=first, date__lte=last)
        .values("category__name")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )
    salaries_paid = (
        Expense.objects.filter(
            date__gte=first, date__lte=last, category__is_system=True
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    )
    # Blocks sold per product. SaleItem has no soft-delete flag, so the
    # sale itself must be filtered: a deleted sale's lines must not count.
    blocks = (
        SaleItem.objects.filter(
            sale__date__gte=first, sale__date__lte=last,
            sale__is_deleted=False,
        )
        .values("product__name")
        .annotate(qty=Sum("quantity"))
        .order_by("-qty")
    )
    # Top 10 customers by billed. Billed is per-sale totals (items minus
    # discount) over non-deleted sales — the same definition as
    # billed_between — so it is grouped from sales, not from item lines.
    _items_sum = (
        SaleItem.objects.filter(sale=OuterRef("pk"))
        .values("sale")
        .annotate(s=Sum(
            F("quantity") * F("unit_price"), output_field=DecimalField()))
        .values("s")
    )
    billed_by_customer = (
        Sale.objects.filter(
            date__gte=first, date__lte=last, customer__isnull=False)
        .annotate(st=Subquery(_items_sum, output_field=DecimalField()))
        .values("customer__id", "customer__name")
        .annotate(total=Sum(
            F("st") - F("discount"), output_field=DecimalField()))
        .order_by("-total")[:10]
    )
    outstanding = total_outstanding(at_date=last)
    return {
        **figures,
        "year": year,
        "month": month,
        "month_name": calendar.month_name[month],
        "by_category": list(by_category),
        "salaries_paid": salaries_paid,
        "blocks": list(blocks),
        "top_customers": list(billed_by_customer),
        "outstanding_at_month_end": outstanding,
    }


def dues_report():
    """Customers who owe, with oldest unpaid invoice and last payment date."""
    rows = []
    for customer in annotate_customer_balances(Customer.objects.all()):
        if customer.balance <= 0:
            continue
        allocation = allocate_customer(customer)
        unpaid_dates = [
            s["sale"].date for s in allocation["sales"] if s["remaining"] > 0
        ]
        last_payment = Payment.objects.filter(customer=customer).aggregate(
            latest=Max("date")
        )["latest"]
        rows.append({
            "customer": customer,
            "balance": customer.balance,
            "oldest_unpaid": min(unpaid_dates) if unpaid_dates else None,
            "last_payment": last_payment,
        })
    rows.sort(key=lambda r: r["balance"], reverse=True)
    return rows


def sales_register(date_from, date_to, customer_id=None, product_id=None):
    """Sales in a date range, optionally filtered by customer or product.
    Raw query-string values are parsed safely: an invalid id is ignored,
    never a 500."""
    qs = Sale.objects.select_related("customer").prefetch_related(
        "items__product"
    ).filter(date__gte=date_from, date__lte=date_to)
    customer_id = parse_int(customer_id)
    product_id = parse_int(product_id)
    if customer_id:
        qs = qs.filter(customer_id=customer_id)
    if product_id:
        qs = qs.filter(items__product_id=product_id).distinct()
    return qs.order_by("date", "id")


def expense_report(date_from, date_to, category_id=None):
    """Expenses in a range, optionally filtered by category, with totals.
    An invalid category id is ignored, never a 500."""
    qs = Expense.objects.select_related("category").filter(
        date__gte=date_from, date__lte=date_to
    )
    category_id = parse_int(category_id)
    if category_id:
        qs = qs.filter(category_id=category_id)
    qs = qs.order_by("date", "id")
    by_category = (
        qs.values("category__name")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )
    grand = qs.aggregate(total=Sum("amount"))["total"] or Decimal("0")
    return {"expenses": qs, "by_category": list(by_category), "grand": grand}
