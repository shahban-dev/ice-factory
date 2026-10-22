"""Reports match hand calculation, and a salary is never double counted."""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.services import soft_delete_objects
from core.tests.helpers import (
    make_admin, make_customer, make_employee, make_product, make_sale,
    make_payment,
)
from customers.models import Customer
from employees.models import Employee, Payroll
from employees.services import generate_payroll, mark_paid
from expenses.models import ExpenseCategory
from reports.services import (
    billed_between, dashboard_data, dues_report, expense_report,
    month_figures, monthly_report, sales_register, total_outstanding,
)
from reports.system_services import (
    audit_entries, recycle_bin_entries, restore_from_bin,
)
from sales.models import Sale
from sales.services import (
    allocate_customer, annotate_customer_balances, customer_ledger_entries,
    delete_sale,
)


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


class ReportDiscountAndDeleteTests(TestCase):
    """A1: billed/outstanding must use sale totals (items minus
    discount) over non-deleted sales, everywhere at once."""

    def setUp(self):
        self.admin = make_admin()
        self.product = make_product()
        self.customer = make_customer(opening="0")

    def test_discount_counted_in_every_surface(self):
        # 10 x Rs 500, discount 500, nothing paid -> 4,500 everywhere.
        make_sale(self.admin, date(2026, 10, 10), self.customer, [
            {"product": self.product, "quantity": 10,
             "unit_price": Decimal("500")},
        ], discount="500")
        self.assertEqual(month_figures(2026, 10)["billed"], Decimal("4500"))
        monthly = monthly_report(2026, 10)
        self.assertEqual(monthly["billed"], Decimal("4500"))
        self.assertEqual(monthly["outstanding_at_month_end"], Decimal("4500"))
        top = {r["customer__name"]: r["total"]
               for r in monthly["top_customers"]}
        self.assertEqual(top, {"Ahmed Store": Decimal("4500")})
        self.assertEqual(total_outstanding(), Decimal("4500"))
        # Dashboard (current month is October 2026) uses the same code.
        self.assertEqual(
            dashboard_data()["month"]["billed"], Decimal("4500"))
        listed = annotate_customer_balances(
            Customer.objects.all()).get(pk=self.customer.pk)
        self.assertEqual(listed.balance, Decimal("4500"))
        ledger = customer_ledger_entries(self.customer)
        self.assertEqual(ledger[-1]["balance"], Decimal("4500"))

    def test_deleted_sales_excluded_then_restored(self):
        credit = make_sale(self.admin, date(2026, 10, 10), self.customer, [
            {"product": self.product, "quantity": 10,
             "unit_price": Decimal("500")},
        ], paid_now="2000")
        walkin = make_sale(self.admin, date(2026, 10, 11), None, [
            {"product": self.product, "quantity": 2,
             "unit_price": Decimal("500")},
        ], paid_now="1000")
        october = (date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(billed_between(*october), Decimal("6000"))
        delete_sale(Sale.objects.get(pk=credit.pk), self.admin, "test")
        delete_sale(Sale.objects.get(pk=walkin.pk), self.admin, "test")
        self.assertEqual(billed_between(*october), Decimal("0"))
        self.assertEqual(total_outstanding(), Decimal("0"))
        monthly = monthly_report(2026, 10)
        self.assertEqual(monthly["billed"], Decimal("0"))
        self.assertEqual(monthly["collected"], Decimal("0"))
        self.assertEqual(monthly["blocks"], [])
        self.assertEqual(monthly["top_customers"], [])
        restore_from_bin("sale", str(credit.pk), self.admin)
        restore_from_bin("sale", str(walkin.pk), self.admin)
        self.assertEqual(billed_between(*october), Decimal("6000"))
        self.assertEqual(monthly_report(2026, 10)["collected"],
                         Decimal("3000"))
        self.assertEqual(total_outstanding(), Decimal("3000"))


class RecycleRestoreGuardTests(TestCase):
    """A8: restore refuses conflicts instead of a 500 page."""

    def setUp(self):
        self.admin = make_admin()

    def test_restore_payroll_conflict(self):
        employee = make_employee()
        generate_payroll(self.admin, 2026, 10)
        old = Payroll.objects.get(employee=employee, year=2026, month=10)
        old.is_deleted = True
        old.deleted_at = timezone.now()
        old.save()
        generate_payroll(self.admin, 2026, 10)  # replacement live row
        with self.assertRaises(ValidationError) as ctx:
            restore_from_bin("payroll", str(old.pk), self.admin)
        self.assertIn("already exists", str(ctx.exception))
        self.assertTrue(Payroll.all_objects.get(pk=old.pk).is_deleted)

    def test_restore_employee_cnic_conflict(self):
        first = Employee.objects.create(
            name="First", cnic="12345-1234567-1",
            monthly_salary=Decimal("30000"), joining_date=date(2025, 1, 1),
            created_by=None, updated_by=None)
        soft_delete_objects([first], self.admin, "test")
        Employee.objects.create(
            name="Second", cnic="12345-1234567-1",
            monthly_salary=Decimal("30000"), joining_date=date(2025, 1, 1),
            created_by=None, updated_by=None)
        with self.assertRaises(ValidationError) as ctx:
            restore_from_bin("employee", str(first.pk), self.admin)
        self.assertIn("CNIC", str(ctx.exception))
        self.assertTrue(Employee.all_objects.get(pk=first.pk).is_deleted)

    def test_restore_sale_with_deleted_customer_refused(self):
        customer = make_customer()
        sale = make_sale(self.admin, date(2026, 10, 10), customer, [
            {"product": make_product(), "quantity": 2,
             "unit_price": Decimal("500")},
        ])
        delete_sale(Sale.objects.get(pk=sale.pk), self.admin, "test")
        soft_delete_objects([customer], self.admin, "test")
        with self.assertRaises(ValidationError) as ctx:
            restore_from_bin("sale", str(sale.pk), self.admin)
        self.assertIn("customer is deleted", str(ctx.exception))
        self.assertTrue(Sale.all_objects.get(pk=sale.pk).is_deleted)


class QueryStringFuzzTests(TestCase):
    """A8: hand-edited query strings never return 5xx."""

    def setUp(self):
        self.admin = make_admin()
        self.client.force_login(self.admin)
        customer = make_customer()
        product = make_product()
        make_sale(self.admin, date(2026, 10, 10), customer, [
            {"product": product, "quantity": 2,
             "unit_price": Decimal("500")},
        ], paid_now="200")
        make_payment(self.admin, customer, date(2026, 10, 11), "100")

    def test_bad_params_never_500(self):
        bad = ["", "abc", "-5", "9" * 30, "2026-13-45", "' OR 1=1"]
        templates = [
            reverse("sales:sale_list") + "?customer={}",
            reverse("sales:payment_list") + "?customer={}",
            reverse("reports:register") + "?customer={}&product={}&from={}",
            reverse("reports:expense_report") + "?category={}&from={}",
            reverse("expenses:expense_list") + "?category={}&from={}",
            reverse("reports:audit") + "?user={}&from={}",
            reverse("reports:monthly") + "?year={}&month={}",
            reverse("employees:payroll_list") + "?year={}&employee={}",
        ]
        for template in templates:
            for value in bad:
                url = template.format(*([value] * template.count("{}")))
                with self.subTest(url=url):
                    response = self.client.get(url)
                    self.assertNotEqual(response.status_code, 500)
                    self.assertEqual(response.status_code, 200)
