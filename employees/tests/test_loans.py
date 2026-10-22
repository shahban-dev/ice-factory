"""B1: employee loans repaid through payroll, on the approved
accounting: a loan is a receivable, not an expense; salary expense =
base + bonus - other deductions = net paid + loan deduction."""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from core.tests.helpers import make_admin, make_employee
from employees.models import Loan, Payroll
from employees.services import (
    create_loan,
    delete_loan,
    generate_payroll,
    loan_remaining,
    mark_paid,
    reopen_payroll,
    update_payroll_draft,
)
from expenses.models import Expense


def make_loan(admin, employee, amount="20000", installment="5000",
              loan_date=date(2026, 9, 1)):
    return create_loan(
        admin, employee, loan_date, Decimal(amount), Decimal(installment)
    )


class LoanPayrollTests(TestCase):
    """C7: loan 20,000, installment 5,000, salary 30,000."""

    def setUp(self):
        self.admin = make_admin()
        self.employee = make_employee(salary="30000")

    def test_generation_proposes_deduction_and_net(self):
        make_loan(self.admin, self.employee)
        generate_payroll(self.admin, 2026, 10)
        row = Payroll.objects.get(employee=self.employee, year=2026, month=10)
        self.assertEqual(row.loan_deduction, Decimal("5000"))
        self.assertEqual(row.net_salary, Decimal("25000"))
        self.assertIsNotNone(row.loan)

    def test_pay_records_repayment_and_expense_is_net_plus_deduction(self):
        loan = make_loan(self.admin, self.employee)
        generate_payroll(self.admin, 2026, 10)
        row = Payroll.objects.get(employee=self.employee, year=2026, month=10)
        mark_paid(row, self.admin, date(2026, 10, 22))
        self.assertEqual(loan_remaining(Loan.objects.get(pk=loan.pk)), Decimal("15000"))
        expense = Expense.objects.get(pk=Payroll.objects.get(pk=row.pk).linked_expense_id)
        # Salary expense is 30,000 (base + bonus - other), NOT the 25,000
        # cash handed over: the 5,000 repayment never reduces it.
        self.assertEqual(expense.amount, Decimal("30000"))
        self.assertEqual(
            Payroll.objects.get(pk=row.pk).paid_amount, Decimal("25000"))

    def test_reopen_reverses_repayment(self):
        loan = make_loan(self.admin, self.employee)
        generate_payroll(self.admin, 2026, 10)
        row = Payroll.objects.get(employee=self.employee, year=2026, month=10)
        mark_paid(row, self.admin, date(2026, 10, 22))
        self.assertEqual(loan_remaining(Loan.objects.get(pk=loan.pk)), Decimal("15000"))
        reopen_payroll(Payroll.objects.get(pk=row.pk), self.admin)
        self.assertEqual(loan_remaining(Loan.objects.get(pk=loan.pk)), Decimal("20000"))
        self.assertEqual(
            Loan.objects.get(pk=loan.pk).status, Loan.STATUS_ACTIVE)

    def test_last_installment_capped_and_loan_settles(self):
        loan = make_loan(self.admin, self.employee, amount="12000",
                         loan_date=date(2026, 7, 1))
        generate_payroll(self.admin, 2026, 7)
        row = Payroll.objects.get(employee=self.employee, year=2026, month=7)
        self.assertEqual(row.loan_deduction, Decimal("5000"))
        mark_paid(row, self.admin, date(2026, 7, 31))
        generate_payroll(self.admin, 2026, 8)
        row = Payroll.objects.get(employee=self.employee, year=2026, month=8)
        self.assertEqual(row.loan_deduction, Decimal("5000"))
        mark_paid(row, self.admin, date(2026, 8, 31))
        # 2,000 left: September's proposal is capped at the remainder.
        generate_payroll(self.admin, 2026, 9)
        row = Payroll.objects.get(employee=self.employee, year=2026, month=9)
        self.assertEqual(row.loan_deduction, Decimal("2000"))
        mark_paid(row, self.admin, date(2026, 9, 30))
        settled = Loan.objects.get(pk=loan.pk)
        self.assertEqual(settled.status, Loan.STATUS_SETTLED)
        self.assertEqual(loan_remaining(settled), Decimal("0"))

    def test_deduction_never_pushes_net_below_zero(self):
        make_loan(self.admin, self.employee)
        generate_payroll(self.admin, 2026, 10)
        row = Payroll.objects.get(employee=self.employee, year=2026, month=10)
        # Other deductions of 28,000 leave only 2,000 of headroom.
        with self.assertRaises(ValidationError):
            update_payroll_draft(
                row, self.admin, Decimal("0"), Decimal("28000"), "",
                "too much", row.version,
                loan=row.loan, loan_deduction=Decimal("5000"))
        updated = update_payroll_draft(
            row, self.admin, Decimal("0"), Decimal("28000"), "",
            "capped", row.version,
            loan=row.loan, loan_deduction=Decimal("2000"))
        self.assertEqual(updated.net_salary, Decimal("0"))

    def test_over_repayment_blocked(self):
        loan = make_loan(self.admin, self.employee, amount="3000")
        generate_payroll(self.admin, 2026, 10)
        row = Payroll.objects.get(employee=self.employee, year=2026, month=10)
        # Proposal is already capped at 3,000; forcing 3,001 must fail.
        with self.assertRaises(ValidationError):
            update_payroll_draft(
                row, self.admin, Decimal("0"), Decimal("0"), "",
                "overpay", row.version,
                loan=loan, loan_deduction=Decimal("3001"))

    def test_delete_blocked_with_repayments(self):
        loan = make_loan(self.admin, self.employee)
        generate_payroll(self.admin, 2026, 10)
        row = Payroll.objects.get(employee=self.employee, year=2026, month=10)
        mark_paid(row, self.admin, date(2026, 10, 22))
        with self.assertRaises(ValidationError):
            delete_loan(Loan.objects.get(pk=loan.pk), self.admin, "nope")
        self.assertTrue(Loan.objects.filter(pk=loan.pk).exists())

    def test_delete_allowed_without_repayments_clears_drafts(self):
        loan = make_loan(self.admin, self.employee)
        generate_payroll(self.admin, 2026, 10)
        row = Payroll.objects.get(employee=self.employee, year=2026, month=10)
        self.assertEqual(row.loan_deduction, Decimal("5000"))
        cleared = delete_loan(Loan.objects.get(pk=loan.pk), self.admin, "mistake")
        self.assertEqual(len(cleared), 1)
        row.refresh_from_db()
        self.assertIsNone(row.loan)
        self.assertEqual(row.loan_deduction, Decimal("0"))
        self.assertEqual(row.net_salary, Decimal("30000"))
        self.assertFalse(Loan.objects.filter(pk=loan.pk).exists())

    def test_mark_paid_override_requires_note_and_sets_expense(self):
        make_loan(self.admin, self.employee)
        generate_payroll(self.admin, 2026, 10)
        row = Payroll.objects.get(employee=self.employee, year=2026, month=10)
        with self.assertRaises(ValidationError):
            mark_paid(row, self.admin, date(2026, 10, 22),
                      paid_amount=Decimal("24000"))
        mark_paid(row, self.admin, date(2026, 10, 22),
                  paid_amount=Decimal("24000"), paid_note="Short-paid Rs 1,000")
        paid = Payroll.objects.get(pk=row.pk)
        self.assertEqual(paid.paid_amount, Decimal("24000"))
        expense = Expense.objects.get(pk=paid.linked_expense_id)
        # Expense = amount actually paid + loan deduction.
        self.assertEqual(expense.amount, Decimal("29000"))

    def test_employee_detail_shows_loan_balance(self):
        make_loan(self.admin, self.employee)
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("employees:detail", args=[self.employee.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["loans_outstanding"], Decimal("20000"))
        self.assertContains(response, "New loan")

    def test_monthly_report_loans_and_earned_vs_paid(self):
        from reports.services import monthly_report
        loan = make_loan(self.admin, self.employee)
        generate_payroll(self.admin, 2026, 9)
        row = Payroll.objects.get(employee=self.employee, year=2026, month=9)
        mark_paid(row, self.admin, date(2026, 9, 30))
        report = monthly_report(2026, 9)
        # Outstanding at September end: 20,000 - 5,000 repaid.
        self.assertEqual(report["loans_outstanding"], Decimal("15000"))
        # Earned in September: net 25,000 + loan deduction 5,000.
        self.assertEqual(report["salary_earned"], Decimal("30000"))
        # Paid in September: the Salaries expense dated in September.
        self.assertEqual(report["salaries_paid"], Decimal("30000"))
        # October: no new rows, no payments — earned 0, outstanding
        # still 15,000 (repayment happened in September).
        october = monthly_report(2026, 10)
        self.assertEqual(october["salary_earned"], Decimal("0"))
        self.assertEqual(october["loans_outstanding"], Decimal("15000"))
