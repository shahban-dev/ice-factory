"""Payroll services: proration, generation, paying and reopening.

A salary is an expense only when the row is marked PAID, on the paid
date, for net_salary, via the linked Expense. Payroll rows themselves are
never summed into profit, so nothing is counted twice.
"""

import calendar
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.money import q2
from core.services import check_version, soft_delete_objects
from employees.models import Employee, Payroll
from expenses.models import Expense
from expenses.services import get_salaries_category


def month_bounds(year, month):
    """First day, last day and number of days of a calendar month."""
    days_in_month = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, days_in_month), days_in_month


def compute_proration(employee, year, month):
    """Return (days_employed, base_salary) for the month, or None when the
    employee was not employed that month. A full month is exactly the
    monthly salary."""
    first, last, days_in_month = month_bounds(year, month)
    start = max(employee.joining_date, first)
    end = min(employee.leaving_date or last, last)
    if end < start:
        return None
    days_employed = (end - start).days + 1
    if days_employed >= days_in_month:
        base = employee.monthly_salary
    else:
        base = q2(
            employee.monthly_salary * Decimal(days_employed) / Decimal(days_in_month)
        )
    return days_employed, base


def compute_net(base_salary, bonus, deductions):
    net = q2(base_salary + bonus - deductions)
    if net < 0:
        raise ValidationError(
            "Net salary cannot be negative. Reduce the deductions or "
            "increase the bonus."
        )
    return net


def generate_payroll(user, year, month):
    """Create draft rows for every eligible employee in one action.
    Skips employees who already have a row that month and employees not
    employed that month. Returns counts. Only current and past months."""
    today = timezone.localdate()
    if (year, month) > (today.year, today.month):
        raise ValidationError("Payroll cannot be generated for a future month.")
    created = skipped_existing = skipped_ineligible = 0
    with transaction.atomic():
        for employee in Employee.objects.filter(is_active=True).order_by("name"):
            proration = compute_proration(employee, year, month)
            if proration is None:
                skipped_ineligible += 1
                continue
            if Payroll.objects.filter(
                employee=employee, year=year, month=month
            ).exists():
                skipped_existing += 1
                continue
            days_employed, base = proration
            row = Payroll(
                employee=employee, year=year, month=month,
                base_salary=base, days_employed=days_employed,
                bonus=Decimal("0"), deductions=Decimal("0"),
                net_salary=base, status=Payroll.STATUS_DRAFT,
                created_by=user, updated_by=user,
            )
            row._change_reason = "Generated"
            row.save()
            created += 1
    return {
        "created": created,
        "skipped_existing": skipped_existing,
        "skipped_ineligible": skipped_ineligible,
    }


def update_payroll_draft(payroll, user, bonus, deductions, deduction_note,
                         reason, form_version):
    """Edit a draft row. Paid rows must be reopened first. Net is
    recomputed on the server and must stay >= 0 (never clamped)."""
    if payroll.status != Payroll.STATUS_DRAFT:
        raise ValidationError(
            "This payroll row is already paid. Reopen it first, then edit."
        )
    net = compute_net(payroll.base_salary, bonus, deductions)
    with transaction.atomic():
        locked = Payroll.all_objects.select_for_update().get(pk=payroll.pk)
        check_version(locked, form_version)
        if locked.status != Payroll.STATUS_DRAFT:
            raise ValidationError(
                "This payroll row is already paid. Reopen it first, then edit."
            )
        locked.bonus = bonus
        locked.deductions = deductions
        locked.deduction_note = deduction_note
        locked.net_salary = net
        locked.updated_by = user
        locked._change_reason = reason
        locked.save()
    return locked


def mark_paid(payroll, user, paid_date):
    """Mark a draft row paid and create its linked Salaries expense in
    the same transaction. The salary counts in the month it is PAID."""
    if paid_date and paid_date > timezone.localdate():
        raise ValidationError("Paid date cannot be in the future.")
    if not paid_date:
        raise ValidationError("Paid date is required.")
    with transaction.atomic():
        locked = Payroll.all_objects.select_for_update().get(pk=payroll.pk)
        if locked.status != Payroll.STATUS_DRAFT:
            raise ValidationError("This payroll row is already paid.")
        if locked.net_salary <= 0:
            raise ValidationError(
                "Net salary must be more than zero to mark it paid."
            )
        if locked.linked_expense_id is not None:
            raise ValidationError("This payroll row already has an expense.")
        month_name = calendar.month_name[locked.month]
        expense = Expense(
            date=paid_date,
            category=get_salaries_category(),
            amount=locked.net_salary,
            description=f"Salary {month_name} {locked.year} - {locked.employee.name}",
            method=Expense.METHOD_CASH,
            created_by=user, updated_by=user,
        )
        expense._change_reason = f"Salary paid for {month_name} {locked.year}"
        expense.save()
        locked.status = Payroll.STATUS_PAID
        locked.paid_date = paid_date
        locked.linked_expense = expense
        locked.updated_by = user
        locked._change_reason = "Marked paid"
        locked.save()
    return locked


def reopen_payroll(payroll, user):
    """Paid -> draft: the linked expense is soft-deleted. The row can
    then be edited and marked paid again (creating a new expense)."""
    with transaction.atomic():
        locked = Payroll.all_objects.select_for_update().get(pk=payroll.pk)
        if locked.status != Payroll.STATUS_PAID:
            raise ValidationError("Only a paid row can be reopened.")
        if locked.linked_expense is not None:
            soft_delete_objects(
                [locked.linked_expense], user, "Payroll reopened"
            )
        locked.status = Payroll.STATUS_DRAFT
        locked.paid_date = None
        locked.linked_expense = None
        locked.updated_by = user
        locked._change_reason = "Reopened"
        locked.save()
    return locked
