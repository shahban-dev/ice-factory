"""Reports match hand calculation, and a salary is never double counted."""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from core.tests.helpers import (
    make_admin, make_customer, make_employee, make_product, make_sale,
    make_payment,
)
from employees.models import Payroll
from employees.services import generate_payroll, mark_paid
from expenses.models import ExpenseCategory
from reports.services import (
    dues_report, expense_report, monthly_report, sales_register,
)
from reports.system_services import audit_entries, recycle_bin_entries


class ReportMathTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_admin()
        p_full = make_product("Full Block", "500")
        p_half = make_product("Half Block", "300")
        a = make_customer(opening="1000")
        b = make_customer(name="Bilal Traders", phone="0300-2222222")
        make_sale(cls.admin, date(2026, 10, 10), a, [
            {"product": p_full, "quantity": 10, "unit_price": Decimal("500")},
        ], paid_now="2000")
        make_sale(cls.admin, date(2026, 10, 15), a, [
            {"product": p_half, "quantity": 5, "unit_price": Decimal("300")},
        ])
        make_sale(cls.admin, date(2026, 10, 5), b, [
            {"product": p_full, "quantity": 4, "unit_price": Decimal("500")},
        ], paid_now="2000")
        make_payment(cls.admin, a, date(2026, 10, 12), "2000")
        cat_e = ExpenseCategory.objects.get(name="Electricity")
        from expenses.models import Expense
        Expense.objects.create(
            date=date(2026, 10, 11), category=cat_e, amount=Decimal("12000"),
            method="bank", created_by=cls.admin, updated_by=cls.admin)
        employee = make_employee()
        generate_payroll(cls.admin, 2026, 10)
        row = Payroll.objects.get(employee=employee, year=2026, month=10)
        mark_paid(row, cls.admin, date(2026, 10, 20))
        # September salary paid in October counts in October, not September.
        sep = Payroll.objects.create(
            employee=employee, year=2026, month=9,
            base_salary=Decimal("30000"), days_employed=30,
            net_salary=Decimal("30000"),
            created_by=cls.admin, updated_by=cls.admin)
        mark_paid(sep, cls.admin, date(2026, 10, 5))

    def test_monthly_report_matches_hand_calculation(self):
        m = monthly_report(2026, 10)
        self.assertEqual(m["billed"], Decimal("8500"))    # 5000+1500+2000
        self.assertEqual(m["collected"], Decimal("6000"))  # 2000+2000+2000
        self.assertEqual(m["expenses"], Decimal("72000"))  # 12000+30000+30000
        self.assertEqual(m["salaries_paid"], Decimal("60000"))
        self.assertEqual(m["sales_profit"], Decimal("-63500"))
        self.assertEqual(m["cash_profit"], Decimal("-66000"))
        self.assertEqual(m["outstanding_at_month_end"], Decimal("3500"))
        blocks = {r["product__name"]: r["qty"] for r in m["blocks"]}
        self.assertEqual(blocks, {"Full Block": 14, "Half Block": 5})

    def test_salary_never_double_counted(self):
        # Expenses for October contain exactly two Salaries expenses.
        from expenses.models import Expense
        salaries = Expense.objects.filter(
            date__year=2026, date__month=10, category__is_system=True)
        self.assertEqual(salaries.count(), 2)
        # The payroll rows themselves are not summed into the report.
        m = monthly_report(2026, 10)
        self.assertEqual(m["expenses"], Decimal("72000"))

    def test_dues_report(self):
        dues = dues_report()
        self.assertEqual(len(dues), 1)
        self.assertEqual(dues[0]["balance"], Decimal("3500"))
        self.assertEqual(dues[0]["oldest_unpaid"], date(2026, 10, 10))
        self.assertEqual(dues[0]["last_payment"], date(2026, 10, 12))

    def test_register_and_expense_report(self):
        reg = sales_register(date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(reg.count(), 3)
        er = expense_report(date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(er["grand"], Decimal("72000"))

    def test_report_pages_and_exports_return_200(self):
        self.client.force_login(self.admin)
        for url in [
            reverse("reports:monthly") + "?year=2026&month=10",
            reverse("reports:monthly") + "?year=2026&month=10&format=pdf",
            reverse("reports:monthly") + "?year=2026&month=10&format=excel",
            reverse("reports:dues"),
            reverse("reports:dues") + "?format=pdf",
            reverse("reports:register"),
            reverse("reports:expense_report"),
            reverse("reports:audit"),
            reverse("reports:recycle"),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_audit_and_bin_see_history(self):
        entries = audit_entries(model_name="Customer")
        self.assertTrue(len(entries) >= 2)
        self.assertTrue(len(recycle_bin_entries()) == 0)
