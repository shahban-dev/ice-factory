"""Audit log and recycle bin services.

The audit log merges simple-history records across every business table.
The recycle bin lists soft-deleted rows and restores them, with two guards:
restoring a sale restores its whole delete batch, and restoring a
payroll-linked expense is blocked when the payroll already has a
different live expense (that would double-count the salary).
"""

import datetime as _datetime

from django.core.exceptions import ValidationError
from django.utils import timezone

from core.services import restore_delete_batch
from customers.models import Customer
from employees.models import Employee, Payroll
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
]

# BaseModel subclasses shown in the recycle bin.
BIN_MODELS = [
    (Customer, "Customer"),
    (Sale, "Sale"),
    (Payment, "Payment"),
    (Expense, "Expense"),
    (Employee, "Employee"),
    (Payroll, "Payroll"),
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
    Returns a list of dicts (already sorted); callers paginate in Python."""
    entries = []
    for model, label in AUDIT_MODELS:
        history = model.history.all()
        if user_id:
            history = history.filter(history_user_id=user_id)
        if model_name and model_name != label:
            continue
        if date_from:
            history = history.filter(history_date__date__gte=date_from)
        if date_to:
            history = history.filter(history_date__date__lte=date_to)
        for record in history.order_by("-history_date")[:limit]:
            try:
                obj_text = str(record.instance)
            except Exception:
                obj_text = f"ID {record.pk}"
            if object_text and object_text.lower() not in obj_text.lower():
                continue
            changes = []
            if record.history_type == "~" and record.prev_record:
                diff = record.diff_against(record.prev_record)
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


def restore_from_bin(model_key, pk, user):
    """Restore one bin entry, applying the batch and payroll guards.
    Returns a message describing what was restored."""
    model_map = {m._meta.model_name: m for m, _ in BIN_MODELS}
    model = model_map.get(model_key)
    if model is None:
        raise ValidationError("Unknown record type.")
    obj = model.all_objects.filter(pk=pk, is_deleted=True).first()
    if obj is None:
        raise ValidationError("That record is not in the recycle bin.")
    if model is Sale and obj.delete_batch is not None:
        restored = restore_delete_batch(
            obj.delete_batch, user, [Sale, Payment]
        )
        return f"Restored sale {obj} and {len(restored) - 1} linked payment(s)."
    if model is Payment and obj.delete_batch:
        # A payment deleted with its sale cannot live without the sale:
        # restore the whole batch (sale + its payments).
        if Sale.all_objects.filter(
            delete_batch=obj.delete_batch, is_deleted=True
        ).exists():
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
    obj.is_deleted = False
    obj.deleted_at = None
    obj.deleted_by = None
    obj.delete_batch = None
    obj._change_reason = "Restored from recycle bin"
    obj.save()
    return f"Restored {obj}."
