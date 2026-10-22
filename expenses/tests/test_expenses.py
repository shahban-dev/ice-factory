"""Expense rules: future dates, positive amounts, the Salaries category,
and payroll-linked read-only protection."""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from core.tests.helpers import make_admin, make_employee
from employees.services import generate_payroll, mark_paid
from employees.models import Payroll
from expenses.models import ExpenseCategory
from expenses.services import (
    create_expense, delete_expense, update_expense,
)


class ExpenseRuleTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.category = ExpenseCategory.objects.get(name="Electricity")
        self.salaries = ExpenseCategory.objects.get(name="Salaries")

    def test_future_expense_blocked(self):
        with self.assertRaises(ValidationError):
            create_expense(self.admin, date(2099, 1, 1), self.category,
                           Decimal("100"), "", "cash")

    def test_zero_expense_blocked(self):
        with self.assertRaises(ValidationError):
            create_expense(self.admin, date(2026, 10, 10), self.category,
                           Decimal("0"), "", "cash")

    def test_manual_salaries_blocked(self):
        with self.assertRaises(ValidationError):
            create_expense(self.admin, date(2026, 10, 10), self.salaries,
                           Decimal("100"), "", "cash")

    def test_system_category_cannot_be_deactivated_via_view(self):
        self.client.force_login(self.admin)
        from django.urls import reverse
        response = self.client.post(
            reverse("expenses:category_toggle", args=[self.salaries.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            ExpenseCategory.objects.get(pk=self.salaries.pk).is_active)

    def test_payroll_linked_expense_is_read_only(self):
        employee = make_employee()
        generate_payroll(self.admin, 2026, 10)
        row = Payroll.objects.get(employee=employee, year=2026, month=10)
        paid = mark_paid(row, self.admin, date(2026, 10, 20))
        expense = paid.linked_expense
        self.assertTrue(expense.is_payroll_linked)
        with self.assertRaises(ValidationError):
            update_expense(expense, self.admin, date(2026, 10, 20),
                           self.category, Decimal("1"), "", "cash", "x", 1)
        with self.assertRaises(ValidationError):
            delete_expense(expense, self.admin)
