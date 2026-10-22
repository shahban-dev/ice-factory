"""Audit log and recycle bin services.

The audit log merges simple-history records across every business table.
The recycle bin lists soft-deleted rows and restores them, with two guards:
restoring a sale restores its whole delete batch, and restoring a
payroll-linked expense is blocked when the payroll already has a
different live expense (that would double-count the salary).
"""

import datetime as _datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.params import parse_int
from core.services import restore_delete_batch
from customers.models import Customer
from employees.models import Employee, Loan, Payroll
from expenses.models import Expense, ExpenseCategory
from sales.models import Payment, Product, Sale, SaleItem

AUDIT_MODELS = [
    (Customer, "Customer"),
    (Product, "Product"),
    (Sale, "Sale"),
    (SaleItem, "Sale item"),
    (Payment, "Payment"),
    (ExpenseCategory, "Expense category"),
    (Expense, "Expense"),
    (Employee, "Employee"),
    (Payroll, "Payroll"),
    (Loan, "Loan"),
]

# BaseModel subclasses shown in the recycle bin.
BIN_MODELS = [
    (Customer, "Customer"),
    (Sale, "Sale"),
    (Payment, "Payment"),
    (Expense, "Expense"),
    (Employee, "Employee"),
    (Payroll, "Payroll"),
    (Loan, "Loan"),
]

HISTORY_TYPE_LABELS = {"+": "Created", "~": "Changed", "-": "Deleted"}

# Sort fallback for rows without a deleted timestamp (never expected, but
# sorting must not crash on None).
_MIN_DATE = _datetime.datetime.min.replace(tzinfo=_datetime.timezone.utc)

# Fields that are history bookkeeping, not business data.
_HISTORY_FIELDS = {
    "history_id", "history_date", "history_change_reason",
    "history_type", "history_user", "history_user_id",
}


def audit_entries(user_id=None, model_name=None, date_from=None,
                  date_to=None, object_text="", limit=500):
    """Merged history records across all business tables, newest first.
    The object-text filter matches the historical object's display name.
    Returns a list of dicts (already sorted); callers paginate in Python.

    Performance: history users are select_related (one query per model,
    not one per row), and each row's predecessor is paired in memory
    from the fetched window — the old code ran one prev_record query
    per changed row, which is thousands of queries on a busy log. Only
    a "~" row whose predecessor fell outside the fetched window still
    costs one query, via prev_record. The pairing matches prev_record
    exactly: the latest row for the same object with a strictly earlier
    history_date, so rows sharing one date are never predecessors.
    """
    entries = []
    for model, label in AUDIT_MODELS:
        history = model.history.all().select_related("history_user")
        if user_id:
            # A hand-edited ?user=abc is ignored, never a 500.
            user_id = parse_int(user_id)
        if user_id:
            history = history.filter(history_user_id=user_id)
        if model_name and model_name != label:
            continue
        if date_from:
            history = history.filter(history_date__date__gte=date_from)
        if date_to:
            history = history.filter(history_date__date__lte=date_to)
        records = list(
            history.order_by("-history_date", "-history_id")[:limit])
        prev_map = {}
        by_object = {}
        for record in records:
            by_object.setdefault(record.id, []).append(record)
        for rows in by_object.values():
            rows.sort(key=lambda r: (r.history_date, r.history_id))
            prev_group_last = None
            current_date = None
            current_group_last = None
            for record in rows:
                if record.history_date != current_date:
                    if current_date is not None:
                        prev_group_last = current_group_last
                    current_date = record.history_date
                    current_group_last = record
                else:
                    current_group_last = record
                prev_map[record.history_id] = prev_group_last
        for record in records:
            try:
                obj_text = str(record.instance)
            except Exception:
                obj_text = f"ID {record.pk}"
            if object_text and object_text.lower() not in obj_text.lower():
                continue
            changes = []
            if record.history_type == "~":
                prev = prev_map.get(record.history_id)
                if prev is None:
                    # Predecessor outside the fetched window, if any.
                    prev = record.prev_record
                if prev is not None:
                    diff = record.diff_against(prev)
                    for field in diff.changed_fields:
                        if field in _HISTORY_FIELDS:
                            continue
                        old = getattr(diff.old_record, field, "")
                        new = getattr(diff.new_record, field, "")
                        changes.append(f"{field}: {old} → {new}")
            entries.append({
                "date": record.history_date,
                "user": record.history_user,
                "model": label,
                "object": obj_text,
                "type": HISTORY_TYPE_LABELS.get(record.history_type, "?"),
                "reason": record.history_change_reason or "",
                "changes": changes,
            })
    entries.sort(key=lambda e: e["date"], reverse=True)
    return entries[:limit]


def recycle_bin_entries():
    """All soft-deleted rows across the business tables, newest first."""
    entries = []
    for model, label in BIN_MODELS:
        for obj in model.all_objects.filter(is_deleted=True).order_by("-deleted_at"):
            entries.append({
                "model": label,
                "model_key": model._meta.model_name,
                "pk": obj.pk,
                "object": str(obj),
                "deleted_at": obj.deleted_at,
                "deleted_by": obj.deleted_by,
            })
    entries.sort(
        key=lambda e: e["deleted_at"] or _MIN_DATE,
        reverse=True,
    )
    return entries


def _ensure_sale_customers_live(sales):
    """Refuse to restore sales whose customer is deleted: a live sale
    for a deleted customer would be invisible everywhere yet still
    counted nowhere — worse than staying in the bin."""
    for sale in sales:
        if sale.customer_id is None:
            continue
        customer = Customer.all_objects.filter(
            pk=sale.customer_id).first()
        if customer is not None and customer.is_deleted:
            raise ValidationError(
                f"Cannot restore sale {sale}: its customer is deleted. "
                "Restore the customer first."
            )


def restore_from_bin(model_key, pk, user):
    """Restore one bin entry, applying the batch and payroll guards.
    Returns a message describing what was restored."""
    model_map = {m._meta.model_name: m for m, _ in BIN_MODELS}
    model = model_map.get(model_key)
    if model is None:
        raise ValidationError("Unknown record type.")
    pk = parse_int(pk)
    if pk is None:
        raise ValidationError("That record is not in the recycle bin.")
    obj = model.all_objects.filter(pk=pk, is_deleted=True).first()
    if obj is None:
        raise ValidationError("That record is not in the recycle bin.")
    try:
        # Own savepoint: a constraint failure here must roll back only
        # this restore, not poison the caller's transaction (in tests,
        # and under ATOMIC_REQUESTS, a bare IntegrityError would make
        # every later query in the request fail).
        with transaction.atomic():
            return _restore_from_bin(model, obj, user)
    except IntegrityError:
        # Unique conflicts the bin cannot resolve on its own: a live
        # payroll row for the same employee and month, or a live
        # employee already using the same CNIC.
        if model is Payroll:
            raise ValidationError(
                "Cannot restore: a live payroll row already exists for "
                "this employee and month."
            )
        if model is Employee:
            raise ValidationError(
                "Cannot restore: another active employee already uses "
                "this CNIC."
            )
        raise ValidationError(
            "Cannot restore this record: it conflicts with a live record."
        )


def _restore_from_bin(model, obj, user):
    if model is Sale and obj.delete_batch is not None:
        _ensure_sale_customers_live([obj])
        restored = restore_delete_batch(
            obj.delete_batch, user, [Sale, Payment]
        )
        return f"Restored sale {obj} and {len(restored) - 1} linked payment(s)."
    if model is Payment and obj.delete_batch:
        # A payment deleted with its sale cannot live without the sale:
        # restore the whole batch (sale + its payments).
        batch_sales = list(Sale.all_objects.filter(
            delete_batch=obj.delete_batch, is_deleted=True))
        if batch_sales:
            _ensure_sale_customers_live(batch_sales)
            restored = restore_delete_batch(
                obj.delete_batch, user, [Sale, Payment]
            )
            return f"Restored {len(restored)} record(s) from the sale's batch."
    if model is Expense:
        # Payroll guard: if a payroll row ever pointed at this expense and
        # now points at a different live expense, restoring would
        # double-count the salary.
        payroll_ids = (
            Payroll.history.filter(linked_expense_id=obj.pk)
            .values_list("id", flat=True).distinct()
        )
        for payroll in Payroll.objects.filter(id__in=list(payroll_ids)):
            if (payroll.linked_expense_id is not None
                    and payroll.linked_expense_id != obj.pk
                    and Expense.objects.filter(
                        pk=payroll.linked_expense_id).exists()):
                raise ValidationError(
                    "Cannot restore this expense: its payroll row already "
                    "has a different live expense. Restoring would count "
                    "the salary twice."
                )
    if model is Loan and Employee.all_objects.filter(
            pk=obj.employee_id, is_deleted=True).exists():
        raise ValidationError(
            "Cannot restore this loan: the employee is deleted. "
            "Restore the employee first."
        )
    obj.is_deleted = False
    obj.deleted_at = None
    obj.deleted_by = None
    obj.delete_batch = None
    obj._change_reason = "Restored from recycle bin"
    obj.save()
    return f"Restored {obj}."
