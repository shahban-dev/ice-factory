"""Payroll services: proration, generation, paying and reopening.

A salary is an expense only when the row is marked PAID, on the paid
date, for net_salary, via the linked Expense. Payroll rows themselves are
never summed into profit, so nothing is counted twice.
"""

import calendar
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from core.money import q2
from core.services import check_version, soft_delete_objects
from employees.models import Employee, Loan, Payroll
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


def compute_net(base_salary, bonus, deductions, loan_deduction=Decimal("0")):
    net = q2(base_salary + bonus - deductions - loan_deduction)
    if net < 0:
        raise ValidationError(
            "Net salary cannot be negative. Reduce the deductions or "
            "increase the bonus."
        )
    return net


# ---------------------------------------------------------------- loans

def loan_repaid(loan):
    """Total repaid: loan_deduction summed over PAID, non-deleted rows.
    Draft rows do not count — only marking paid records a repayment,
    and reopening reverses it."""
    total = (
        Payroll.objects.filter(loan=loan, status=Payroll.STATUS_PAID)
        .aggregate(total=models.Sum("loan_deduction"))["total"]
    )
    return total or Decimal("0")


def loan_remaining(loan):
    return q2(loan.amount - loan_repaid(loan))


def refresh_loan_status(loan):
    """Settled exactly when nothing remains; back to active otherwise.
    Returns the loan (saved only when the status changed)."""
    wanted = (
        Loan.STATUS_SETTLED if loan_remaining(loan) <= 0
        else Loan.STATUS_ACTIVE
    )
    if loan.status != wanted:
        loan.status = wanted
        loan.save()
    return loan


def oldest_active_loan(employee):
    """The loan payroll deducts from: oldest active loan first."""
    return (
        Loan.objects.filter(employee=employee, status=Loan.STATUS_ACTIVE)
        .order_by("date", "id")
        .first()
    )


def propose_loan_deduction(employee, base_salary, bonus, deductions):
    """(loan, amount) proposed for a new payroll row: min(installment,
    remaining, base + bonus - other deductions), never below zero and
    never pushing net below zero. (None, 0) when there is nothing to
    deduct."""
    loan = oldest_active_loan(employee)
    if loan is None:
        return None, Decimal("0")
    cap = base_salary + bonus - deductions
    if cap < 0:
        cap = Decimal("0")
    proposed = min(loan.monthly_installment, loan_remaining(loan), cap)
    if proposed <= 0:
        return None, Decimal("0")
    return loan, q2(proposed)


def create_loan(user, employee, date, amount, installment, notes=""):
    if date and date > timezone.localdate():
        raise ValidationError("Loan date cannot be in the future.")
    loan = Loan(
        employee=employee, date=date, amount=q2(amount),
        monthly_installment=q2(installment), notes=notes,
        created_by=user, updated_by=user,
    )
    loan.full_clean()
    loan._change_reason = "Created"
    loan.save()
    return loan


def update_loan(loan, user, date, amount, installment, notes, reason,
                form_version=None):
    if date and date > timezone.localdate():
        raise ValidationError("Loan date cannot be in the future.")
    repaid = loan_repaid(loan)
    if q2(amount) < repaid:
        raise ValidationError(
            f"Loan amount cannot be less than the Rs {repaid} already repaid."
        )
    with transaction.atomic():
        locked = Loan.objects.select_for_update().get(pk=loan.pk)
        if form_version is not None:
            check_version(locked, form_version)
        locked.date = date
        locked.amount = q2(amount)
        locked.monthly_installment = q2(installment)
        locked.notes = notes
        locked.updated_by = user
        locked._change_reason = reason
        locked.full_clean()
        locked.save()
        refresh_loan_status(locked)
    return locked


def delete_loan(loan, user, reason):
    """Blocked when any repayment exists. Draft rows that reference the
    loan have their deduction cleared (they are uncommitted plans, not
    repayments); the cleared rows are returned for the message."""
    repaid = loan_repaid(loan)
    if repaid > 0:
        raise ValidationError(
            f"This loan cannot be deleted: Rs {repaid} has already been "
            "repaid through payroll."
        )
    cleared = []
    with transaction.atomic():
        locked = Loan.objects.select_for_update().get(pk=loan.pk)
        for row in Payroll.objects.filter(
            loan=locked, status=Payroll.STATUS_DRAFT
        ):
            row.loan = None
            row.loan_deduction = Decimal("0")
            row.net_salary = compute_net(
                row.base_salary, row.bonus, row.deductions
            )
            row.updated_by = user
            row._change_reason = "Loan deleted; deduction cleared"
            row.save()
            cleared.append(row)
        soft_delete_objects([locked], user, reason)
    return cleared


def generate_payroll(user, year, month):
    """Create draft rows for every eligible employee in one action.
    Skips employees who already have a row that month and employees not
    employed that month. Returns counts plus warnings.

    Eligibility is decided by DATES, not by is_active: an employee who
    left mid-month and was deactivated before payroll ran still gets
    their last partial month. Inactive employees with NO leaving date
    cannot be placed in any month, so they are excluded and listed in
    warnings — set their leaving date and generate again."""
    today = timezone.localdate()
    if (year, month) > (today.year, today.month):
        raise ValidationError("Payroll cannot be generated for a future month.")
    created = skipped_existing = skipped_ineligible = 0
    warnings = []
    with transaction.atomic():
        for employee in Employee.objects.all().order_by("name"):
            if not employee.is_active and employee.leaving_date is None:
                skipped_ineligible += 1
                warnings.append(employee.name)
                continue
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
            loan, loan_deduction = propose_loan_deduction(
                employee, base, Decimal("0"), Decimal("0")
            )
            row = Payroll(
                employee=employee, year=year, month=month,
                base_salary=base, days_employed=days_employed,
                bonus=Decimal("0"), deductions=Decimal("0"),
                loan=loan, loan_deduction=loan_deduction,
                net_salary=base - loan_deduction, status=Payroll.STATUS_DRAFT,
                created_by=user, updated_by=user,
            )
            row._change_reason = "Generated"
            row.save()
            created += 1
    return {
        "created": created,
        "skipped_existing": skipped_existing,
        "skipped_ineligible": skipped_ineligible,
        "warnings": warnings,
    }


def update_payroll_draft(payroll, user, bonus, deductions, deduction_note,
                         reason, form_version, loan=None, loan_deduction=None):
    """Edit a draft row. Paid rows must be reopened first. Net is
    recomputed on the server and must stay >= 0 (never clamped). A loan
    deduction may never exceed the loan's remaining balance, and a
    deduction without a loan is rejected."""
    if payroll.status != Payroll.STATUS_DRAFT:
        raise ValidationError(
            "This payroll row is already paid. Reopen it first, then edit."
        )
    if loan_deduction is None:
        loan_deduction = Decimal("0")
    loan_deduction = q2(loan_deduction)
    if loan_deduction > 0 and loan is None:
        raise ValidationError(
            "Pick the loan this deduction repays, or set the loan "
            "deduction to zero."
        )
    if loan is not None and loan.employee_id != payroll.employee_id:
        raise ValidationError("That loan belongs to another employee.")
    if loan is not None and loan_deduction > loan_remaining(loan):
        raise ValidationError(
            f"Loan deduction cannot exceed the Rs {loan_remaining(loan)} "
            "still owed on this loan."
        )
    if loan is None:
        loan_deduction = Decimal("0")
    net = compute_net(payroll.base_salary, bonus, deductions, loan_deduction)
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
        locked.loan = loan
        locked.loan_deduction = loan_deduction
        locked.net_salary = net
        locked.updated_by = user
        locked._change_reason = reason
        locked.save()
    return locked


def mark_paid(payroll, user, paid_date, paid_amount=None, paid_note=""):
    """Mark a draft row paid and create its linked Salaries expense in
    the same transaction. The salary counts in the month it is PAID.

    paid_amount is the cash actually handed over: it defaults to
    net_salary, and an override requires a note. The expense is
    paid_amount + loan_deduction — the salary expense (base + bonus -
    other deductions), so a loan repayment never reduces it. The row's
    loan_deduction is what repays the loan: once paid, it counts toward
    the loan's repaid total, and reopening reverses it."""
    if paid_date and paid_date > timezone.localdate():
        raise ValidationError("Paid date cannot be in the future.")
    if not paid_date:
        raise ValidationError("Paid date is required.")
    if paid_amount is not None:
        paid_amount = q2(paid_amount)
        if paid_amount < 0:
            raise ValidationError("Amount paid cannot be negative.")
    with transaction.atomic():
        locked = Payroll.all_objects.select_for_update().get(pk=payroll.pk)
        if locked.status != Payroll.STATUS_DRAFT:
            raise ValidationError("This payroll row is already paid.")
        if paid_amount is None:
            paid_amount = locked.net_salary
        if paid_amount != locked.net_salary and not (paid_note or "").strip():
            raise ValidationError(
                "Amount paid differs from net salary — a note is required."
            )
        if paid_amount <= 0 and locked.loan_deduction <= 0:
            raise ValidationError(
                "Nothing to pay: net salary is zero and there is no loan "
                "deduction on this row."
            )
        if locked.linked_expense_id is not None:
            raise ValidationError("This payroll row already has an expense.")
        month_name = calendar.month_name[locked.month]
        expense = Expense(
            date=paid_date,
            category=get_salaries_category(),
            amount=q2(paid_amount + locked.loan_deduction),
            description=f"Salary {month_name} {locked.year} - {locked.employee.name}",
            method=Expense.METHOD_CASH,
            created_by=user, updated_by=user,
        )
        expense._change_reason = f"Salary paid for {month_name} {locked.year}"
        expense.save()
        locked.status = Payroll.STATUS_PAID
        locked.paid_date = paid_date
        locked.paid_amount = paid_amount
        locked.paid_note = paid_note
        locked.linked_expense = expense
        locked.updated_by = user
        locked._change_reason = "Marked paid"
        locked.save()
        if locked.loan_id is not None:
            refresh_loan_status(Loan.objects.get(pk=locked.loan_id))
    return locked


def reopen_payroll(payroll, user):
    """Paid -> draft: the linked expense is soft-deleted, and any loan
    repayment on the row is reversed (the row no longer counts as
    repaid, so a settled loan goes back to active). The row can then
    be edited and marked paid again (creating a new expense)."""
    with transaction.atomic():
        locked = Payroll.all_objects.select_for_update().get(pk=payroll.pk)
        if locked.status != Payroll.STATUS_PAID:
            raise ValidationError("Only a paid row can be reopened.")
        loan_id = locked.loan_id
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
        if loan_id is not None:
            refresh_loan_status(Loan.objects.get(pk=loan_id))
    return locked
