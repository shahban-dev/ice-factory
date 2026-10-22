"""Expense services. Manual expenses can never use the system Salaries
category, and payroll-linked expenses can only change through payroll.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.services import check_version, soft_delete_objects
from expenses.models import Expense, ExpenseCategory


def get_salaries_category():
    """The system Salaries category, created if the seed migration never ran."""
    category, _ = ExpenseCategory.objects.get_or_create(
        name="Salaries", defaults={"is_system": True}
    )
    if not category.is_system:
        category.is_system = True
        category.save(update_fields=["is_system"])
    return category


def create_expense(user, date, category, amount, description, method,
                   change_reason="Created"):
    if date and date > timezone.localdate():
        raise ValidationError("Expense date cannot be in the future.")
    if amount <= 0:
        raise ValidationError("Expense amount must be more than zero.")
    if category.is_system:
        raise ValidationError(
            "The Salaries category is used only by payroll, not manually."
        )
    expense = Expense(
        date=date, category=category, amount=amount,
        description=description, method=method,
        created_by=user, updated_by=user,
    )
    expense._change_reason = change_reason
    expense.save()
    return expense


def update_expense(expense, user, date, category, amount, description, method,
                   reason, form_version):
    if expense.is_payroll_linked:
        raise ValidationError(
            "This expense was created by payroll and can only change "
            "through payroll. Reopen the payroll row first."
        )
    if date and date > timezone.localdate():
        raise ValidationError("Expense date cannot be in the future.")
    if amount <= 0:
        raise ValidationError("Expense amount must be more than zero.")
    if category.is_system:
        raise ValidationError(
            "The Salaries category is used only by payroll, not manually."
        )
    with transaction.atomic():
        locked = Expense.all_objects.select_for_update().get(pk=expense.pk)
        check_version(locked, form_version)
        locked.date = date
        locked.category = category
        locked.amount = amount
        locked.description = description
        locked.method = method
        locked.updated_by = user
        locked._change_reason = reason
        locked.save()
    return locked


def delete_expense(expense, user, reason=""):
    if expense.is_payroll_linked:
        raise ValidationError(
            "This expense was created by payroll. Reopen the payroll row "
            "first; that removes this expense."
        )
    return soft_delete_objects([expense], user, reason)
