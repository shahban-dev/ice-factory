"""Payroll rules: proration, net math, paying, reopening, and guards."""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from core.tests.helpers import make_admin, make_employee
from employees.models import Employee, Payroll
from employees.services import (
    compute_proration, generate_payroll, mark_paid, reopen_payroll,
    update_payroll_draft,
)
from expenses.models import Expense


class ProrationTests(TestCase):
    def test_full_month_exact(self):
        e = make_employee(salary="30000")
        self.assertEqual(compute_proration(e, 2026, 10), (31, Decimal("30000")))

    def test_mid_month_joiner(self):
        e = make_employee(salary="31000", joined=date(2026, 10, 16))
        self.assertEqual(compute_proration(e, 2026, 10), (16, Decimal("16000")))

    def test_mid_month_leaver(self):
        e = make_employee(salary="30000", left=date(2026, 10, 10))
        self.assertEqual(compute_proration(e, 2026, 10), (10, Decimal("9677.42")))

    def test_february_28_and_29(self):
        e = make_employee(salary="28000")
        self.assertEqual(compute_proration(e, 2026, 2), (28, Decimal("28000")))
        self.assertEqual(compute_proration(e, 2028, 2), (29, Decimal("28000")))

    def test_31_day_month(self):
        e = make_employee(salary="31000", joined=date(2026, 10, 31))
        self.assertEqual(compute_proration(e, 2026, 10), (1, Decimal("1000")))

    def test_not_employed_that_month(self):
        e = make_employee(joined=date(2026, 11, 1))
        self.assertIsNone(compute_proration(e, 2026, 10))
        e2 = make_employee(name="Gone", left=date(2026, 9, 30))
        self.assertIsNone(compute_proration(e2, 2026, 10))


class PayrollFlowTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.employee = make_employee()

    def test_generate_skips_existing_and_ineligible(self):
        make_employee(name="Not Yet", joined=date(2026, 11, 1))
        result = generate_payroll(self.admin, 2026, 10)
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["skipped_ineligible"], 1)
        result2 = generate_payroll(self.admin, 2026, 10)
        self.assertEqual(result2["created"], 0)
        self.assertEqual(result2["skipped_existing"], 1)

    def test_future_month_blocked(self):
        with self.assertRaises(ValidationError):
            generate_payroll(self.admin, 2099, 1)

    def test_bonus_deduction_net(self):
        generate_payroll(self.admin, 2026, 10)
        row = Payroll.objects.get(employee=self.employee, year=2026, month=10)
        updated = update_payroll_draft(
            row, self.admin, Decimal("2000"), Decimal("500"), "2 days absent",
            "test", row.version)
        self.assertEqual(updated.net_salary, Decimal("31500"))

    def test_negative_net_rejected_never_clamped(self):
        generate_payroll(self.admin, 2026, 10)
        row = Payroll.objects.get(employee=self.employee, year=2026, month=10)
        with self.assertRaises(ValidationError):
            update_payroll_draft(
                row, self.admin, Decimal("0"), Decimal("99999"), "",
                "test", row.version)
        # The row is unchanged.
        self.assertEqual(
            Payroll.objects.get(pk=row.pk).net_salary, Decimal("30000"))

    def test_duplicate_month_blocked(self):
        generate_payroll(self.admin, 2026, 10)
        with self.assertRaises(IntegrityError):
            Payroll.objects.create(
                employee=self.employee, year=2026, month=10,
                base_salary=Decimal("1"), days_employed=1,
                net_salary=Decimal("1"),
                created_by=self.admin, updated_by=self.admin)

    def test_mark_paid_creates_exactly_one_expense(self):
        generate_payroll(self.admin, 2026, 10)
        row = Payroll.objects.get(employee=self.employee, year=2026, month=10)
        paid = mark_paid(row, self.admin, date(2026, 10, 20))
        expenses = Expense.objects.filter(payroll_rows__pk=row.pk)
        self.assertEqual(expenses.count(), 1)
        expense = expenses.get()
        self.assertEqual(expense.amount, Decimal("30000"))
        self.assertEqual(expense.date, date(2026, 10, 20))
        self.assertEqual(expense.category.name, "Salaries")
        self.assertEqual(paid.status, "paid")

    def test_reopen_removes_expense(self):
        generate_payroll(self.admin, 2026, 10)
        row = Payroll.objects.get(employee=self.employee, year=2026, month=10)
        paid = mark_paid(row, self.admin, date(2026, 10, 20))
        expense_id = paid.linked_expense_id
        reopened = reopen_payroll(Payroll.objects.get(pk=row.pk), self.admin)
        self.assertEqual(reopened.status, "draft")
        self.assertIsNone(reopened.linked_expense)
        self.assertTrue(Expense.all_objects.get(pk=expense_id).is_deleted)

    def test_salary_change_does_not_alter_past_rows(self):
        generate_payroll(self.admin, 2026, 10)
        self.employee.monthly_salary = Decimal("40000")
        self.employee.save()
        row = Payroll.objects.get(employee=self.employee, year=2026, month=10)
        self.assertEqual(row.base_salary, Decimal("30000"))

    def test_salary_paid_next_month_counts_in_month_paid(self):
        row = Payroll.objects.create(
            employee=self.employee, year=2026, month=9,
            base_salary=Decimal("30000"), days_employed=30,
            net_salary=Decimal("30000"),
            created_by=self.admin, updated_by=self.admin)
        mark_paid(row, self.admin, date(2026, 10, 5))
        expense = Expense.objects.get(payroll_rows__pk=row.pk)
        self.assertEqual(expense.date, date(2026, 10, 5))

    def test_zero_net_cannot_be_paid(self):
        generate_payroll(self.admin, 2026, 10)
        row = Payroll.objects.get(employee=self.employee, year=2026, month=10)
        update_payroll_draft(row, self.admin, Decimal("0"), Decimal("30000"),
                             "full deduction", "test", row.version)
        with self.assertRaises(ValidationError):
            mark_paid(Payroll.objects.get(pk=row.pk), self.admin,
                      date(2026, 10, 20))

    def test_paid_row_edit_requires_reopen(self):
        generate_payroll(self.admin, 2026, 10)
        row = Payroll.objects.get(employee=self.employee, year=2026, month=10)
        mark_paid(row, self.admin, date(2026, 10, 20))
        with self.assertRaises(ValidationError):
            update_payroll_draft(
                Payroll.objects.get(pk=row.pk), self.admin,
                Decimal("1000"), Decimal("0"), "", "test",
                Payroll.objects.get(pk=row.pk).version)


class EmployeeRuleTests(TestCase):
    def test_cnic_validation_and_masking(self):
        from employees.models import mask_cnic
        e = make_employee()
        e.cnic = "1234512345671"
        e.save()
        self.assertEqual(e.cnic, "12345-1234567-1")
        self.assertEqual(mask_cnic(e.cnic), "12345-*******-1")
        e.cnic = "123"
        with self.assertRaises(ValidationError):
            e.full_clean()

    def test_duplicate_cnic_blocked_among_active(self):
        e1 = make_employee()
        e1.cnic = "12345-1234567-1"
        e1.save()
        e2 = make_employee(name="Second")
        e2.cnic = "12345-1234567-1"
        with self.assertRaises(IntegrityError):
            e2.save()

    def test_employee_delete_blocked_with_payroll(self):
        admin = make_admin()
        self.client.force_login(admin)
        employee = make_employee()
        generate_payroll(admin, 2026, 10)
        from django.urls import reverse
        response = self.client.post(
            reverse("employees:delete", args=[employee.pk]),
            {"reason": "test"})
        # Blocked: redirected to the detail page, employee still present.
        self.assertEqual(response.status_code, 302)
        self.assertIn(f"/employees/{employee.pk}/", response["Location"])
        self.assertTrue(Employee.objects.filter(pk=employee.pk).exists())
        # Deactivate instead works — but only once a leaving date is set.
        response = self.client.post(
            reverse("employees:delete", args=[employee.pk]),
            {"action": "deactivate"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(f"/employees/{employee.pk}/edit/", response["Location"])
        self.assertTrue(Employee.objects.get(pk=employee.pk).is_active)
        employee.leaving_date = date(2026, 10, 10)
        employee.save()
        response = self.client.post(
            reverse("employees:delete", args=[employee.pk]),
            {"action": "deactivate"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Employee.objects.get(pk=employee.pk).is_active)


class LeaverPayrollTests(TestCase):
    """A4: eligibility is decided by dates, not by is_active."""

    def test_leaver_gets_last_partial_month(self):
        admin = make_admin()
        employee = make_employee(
            name="Leaver", salary="30000", joined=date(2025, 1, 1),
            left=date(2026, 10, 10))
        employee.is_active = False
        employee.save()
        generate_payroll(admin, 2026, 10)
        row = Payroll.objects.get(employee=employee, year=2026, month=10)
        self.assertEqual(row.days_employed, 10)
        self.assertEqual(row.base_salary, Decimal("9677.42"))
        # November: the employee was not employed at all that month, so
        # proration says None (November itself cannot be generated yet
        # from October — the future-month guard blocks it).
        from employees.services import compute_proration
        self.assertIsNone(compute_proration(employee, 2026, 11))

    def test_inactive_without_leaving_date_excluded_and_warned(self):
        admin = make_admin()
        employee = make_employee(name="NoDate")
        employee.is_active = False
        employee.save()
        result = generate_payroll(admin, 2026, 10)
        self.assertIn("NoDate", result["warnings"])
        self.assertFalse(Payroll.objects.filter(employee=employee).exists())
