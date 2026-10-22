"""Group C: hand-calculated scenarios, each its own test.

Every number below is worked out by hand in the test, not copied from
the implementation: if the implementation drifts, the test fails.
Scenarios C1–C11 run here; C12 (concurrency) lives in
sales/tests/test_group_c_concurrency.py because it needs
TransactionTestCase.
"""

import random
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Sum
from django.test import TestCase
from django.urls import reverse

from core.money import q2
from core.services import restore_delete_batch
from core.tests.helpers import (
    make_admin,
    make_customer,
    make_employee,
    make_payment,
    make_product,
    make_sale,
)
from customers.models import Customer
from customers.services import parse_import_file, save_import_rows
from employees.models import Payroll
from employees.services import (
    compute_proration,
    create_loan,
    generate_payroll,
    loan_remaining,
    mark_paid,
    reopen_payroll,
)
from expenses.models import Expense
from reports.services import (
    dashboard_data,
    month_figures,
    sales_register,
    total_outstanding,
)
from sales.models import Payment, Sale
from sales.services import (
    allocate_customer,
    annotate_customer_balances,
    create_payment,
    delete_payment,
    delete_sale,
    update_payment,
)


def csv_file(content):
    return SimpleUploadedFile(
        "customers.csv", content.encode(), content_type="text/csv")


class C1DiscountEverywhereTests(TestCase):
    def test_rs_5000_sale_with_rs_500_discount_is_4500_everywhere(self):
        admin = make_admin()
        product = make_product()
        customer = make_customer()
        make_sale(admin, date(2026, 10, 10), customer, [
            {"product": product, "quantity": 10, "unit_price": 500},
        ], discount="500")
        # Hand calc: 10 x 500 = 5,000 subtotal, minus 500 discount = 4,500.
        self.assertEqual(month_figures(2026, 10)["billed"], Decimal("4500"))
        register = sales_register(date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(
            sum((s.total for s in register), Decimal("0")), Decimal("4500"))
        annotated = annotate_customer_balances(Customer.objects.all())[0]
        self.assertEqual(annotated.balance, Decimal("4500"))
        self.assertEqual(
            allocate_customer(customer)["balance"], Decimal("4500"))
        self.assertEqual(total_outstanding(), Decimal("4500"))
        self.assertEqual(
            dashboard_data()["month"]["billed"], Decimal("4500"))


class C2DeleteRestoreTests(TestCase):
    def test_delete_goes_to_zero_and_restore_brings_it_back(self):
        admin = make_admin()
        product = make_product()
        customer = make_customer()
        credit = make_sale(admin, date(2026, 10, 5), customer, [
            {"product": product, "quantity": 10, "unit_price": 500},
        ], paid_now="2000")
        walkin = make_sale(admin, date(2026, 10, 6), None, [
            {"product": product, "quantity": 2, "unit_price": 500},
        ], paid_now="1000")
        # Before: billed 5,000 + 1,000 = 6,000; collected 2,000 + 1,000
        # = 3,000; outstanding 6,000 - 3,000 = 3,000.
        self.assertEqual(month_figures(2026, 10)["billed"], Decimal("6000"))
        self.assertEqual(
            month_figures(2026, 10)["collected"], Decimal("3000"))
        self.assertEqual(total_outstanding(), Decimal("3000"))
        batch1, _ = delete_sale(credit, admin, "test delete")
        batch2, _ = delete_sale(walkin, admin, "test delete")
        self.assertEqual(month_figures(2026, 10)["billed"], Decimal("0"))
        self.assertEqual(month_figures(2026, 10)["collected"], Decimal("0"))
        self.assertEqual(total_outstanding(), Decimal("0"))
        restore_delete_batch(batch1, admin, [Sale, Payment])
        restore_delete_batch(batch2, admin, [Sale, Payment])
        self.assertEqual(month_figures(2026, 10)["billed"], Decimal("6000"))
        self.assertEqual(
            month_figures(2026, 10)["collected"], Decimal("3000"))
        self.assertEqual(total_outstanding(), Decimal("3000"))


class C3ReconciliationTests(TestCase):
    def _check_invariants(self):
        annotated = {
            c.pk: c.balance
            for c in annotate_customer_balances(Customer.objects.all())
        }
        positive = sum(
            (b for b in annotated.values() if b > 0), Decimal("0"))
        self.assertEqual(total_outstanding(), positive)
        for customer in Customer.objects.all():
            self.assertEqual(
                allocate_customer(customer)["balance"],
                annotated[customer.pk])
        month = month_figures(2026, 10)
        register = sales_register(date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(
            month["billed"],
            sum((s.total for s in register), Decimal("0")))
        collected = Payment.objects.filter(
            date__gte=date(2026, 10, 1), date__lte=date(2026, 10, 31)
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        self.assertEqual(month["collected"], collected)

    def test_200_random_actions_keep_every_total_in_agreement(self):
        rng = random.Random(20261022)
        admin = make_admin()
        products = [make_product(name="Full Block"), make_product(name="Half Block")]
        customers = [
            make_customer(
                name=f"Shop {i}", phone=f"0300-200000{i}",
                opening=str(rng.choice([-5000, 0, 2500, 10000])))
            for i in range(8)
        ]
        for step in range(200):
            roll = rng.random()
            try:
                if roll < 0.50:
                    customer = rng.choice(customers + [None])
                    lines = []
                    subtotal = Decimal("0")
                    for _ in range(rng.randint(1, 3)):
                        qty = rng.randint(1, 20)
                        price = Decimal(rng.choice([100, 250, 500, 750, 1000]))
                        lines.append({"product": rng.choice(products),
                                      "quantity": qty, "unit_price": price})
                        subtotal += qty * price
                    discount = Decimal(rng.choice([0, 0, 500])) if subtotal > 500 else Decimal("0")
                    total = subtotal - discount
                    paid = rng.choice([Decimal("0"), total // 2, total])
                    make_sale(admin, date(2026, 10, rng.randint(1, 22)),
                              customer, lines, paid_now=str(paid),
                              discount=str(discount))
                elif roll < 0.80:
                    make_payment(admin, rng.choice(customers),
                                 date(2026, 10, rng.randint(1, 22)),
                                 str(rng.randint(100, 5000)))
                elif roll < 0.92:
                    sale = Sale.objects.order_by("?").first()
                    if sale is not None:
                        delete_sale(sale, admin, "property test")
                else:
                    payment = Payment.objects.order_by("?").first()
                    if payment is not None:
                        delete_payment(payment, admin, "property test")
            except ValidationError:
                pass  # an invalid random action is skipped, not counted
            if step in (99, 199):
                self._check_invariants()


class C4NoCustomerPaymentTests(TestCase):
    def test_standalone_payment_without_customer_is_refused(self):
        admin = make_admin()
        with self.assertRaises(ValidationError):
            create_payment(admin, None, date(2026, 10, 10),
                           Decimal("1000"), "cash")
        self.assertEqual(Payment.objects.count(), 0)
        self.client.force_login(admin)
        response = self.client.post(reverse("sales:payment_create"), {
            "date": "2026-10-10", "customer": "", "amount": "1000",
            "method": "cash", "reference": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Payment.objects.count(), 0)


class C5PaymentEditRuleTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.product = make_product()
        self.client.force_login(self.admin)

    def _post_payment_edit(self, payment, **overrides):
        data = {
            "date": "2026-10-10", "customer": str(payment.customer_id or ""),
            "amount": str(payment.amount), "method": "cash",
            "reference": "", "reason": "test edit",
            "version": str(payment.version),
        }
        data.update(overrides)
        return self.client.post(
            reverse("sales:payment_edit", args=[payment.pk]), data)

    def test_customer_can_never_change(self):
        first = make_customer(name="First", phone="0300-1111111")
        second = make_customer(name="Second", phone="0300-2222222")
        payment = make_payment(self.admin, first, date(2026, 10, 10), "1000")
        self._post_payment_edit(payment, customer=str(second.pk))
        payment.refresh_from_db()
        self.assertEqual(payment.customer_id, first.pk)

    def test_walkin_payment_amount_is_locked(self):
        sale = make_sale(self.admin, date(2026, 10, 10), None, [
            {"product": self.product, "quantity": 2, "unit_price": 500},
        ], paid_now="1000")
        payment = sale.payments.get()
        with self.assertRaises(ValidationError):
            update_payment(payment, self.admin, date(2026, 10, 10),
                           Decimal("500"), "cash", "", "shrinking it",
                           payment.version)
        payment.refresh_from_db()
        self.assertEqual(payment.amount, Decimal("1000"))
        # The form locks the field too: a crafted POST keeps the amount.
        self._post_payment_edit(payment, amount="500")
        payment.refresh_from_db()
        self.assertEqual(payment.amount, Decimal("1000"))

    def test_credit_sale_payment_amount_can_change_with_reason(self):
        customer = make_customer()
        sale = make_sale(self.admin, date(2026, 10, 10), customer, [
            {"product": self.product, "quantity": 10, "unit_price": 500},
        ], paid_now="1000")
        payment = sale.payments.get()
        updated = update_payment(payment, self.admin, date(2026, 10, 10),
                                 Decimal("1500"), "cash", "",
                                 "corrected amount", payment.version)
        self.assertEqual(updated.amount, Decimal("1500"))
        allocation = allocate_customer(customer)
        self.assertEqual(allocation["sales"][0]["allocated"], Decimal("1500"))
        self.assertEqual(allocation["sales"][0]["remaining"], Decimal("3500"))
        self.assertEqual(allocation["sales"][0]["status"], "partial")


class C6LeaverPayrollTests(TestCase):
    def test_leaver_gets_last_partial_month_and_no_november_row(self):
        admin = make_admin()
        employee = make_employee(salary="30000", joined=date(2025, 1, 1))
        employee.leaving_date = date(2026, 10, 10)
        employee.is_active = False
        employee.save()
        result = generate_payroll(admin, 2026, 10)
        self.assertEqual(result["created"], 1)
        row = Payroll.objects.get(employee=employee, year=2026, month=10)
        # 10 days of a 31-day month: 30,000 x 10 / 31 = 9,677.419...
        # rounded half-up to 9,677.42.
        self.assertEqual(row.days_employed, 10)
        self.assertEqual(row.base_salary, Decimal("9677.42"))
        # November: not employed at all (left 10 October).
        self.assertIsNone(compute_proration(employee, 2026, 11))
        # ...and November cannot even be generated yet: it is a future
        # month on 2026-10-22, so no November row can exist.
        with self.assertRaises(ValidationError):
            generate_payroll(admin, 2026, 11)
        self.assertEqual(
            Payroll.objects.filter(year=2026, month=11).count(), 0)


class C7LoanScenarioTests(TestCase):
    def test_loan_repaid_through_payroll_without_touching_expense(self):
        admin = make_admin()
        employee = make_employee(salary="30000")
        loan = create_loan(admin, employee, date(2026, 10, 1),
                           Decimal("10000"), Decimal("2000"))
        generate_payroll(admin, 2026, 10)
        row = Payroll.objects.get(employee=employee, year=2026, month=10)
        self.assertEqual(row.loan_deduction, Decimal("2000"))
        self.assertEqual(row.net_salary, Decimal("28000"))
        mark_paid(row, admin, date(2026, 10, 22))
        self.assertEqual(loan_remaining(loan), Decimal("8000"))
        expense = Expense.objects.get(category__name="Salaries")
        # Expense is the full salary (28,000 paid + 2,000 repaid), not
        # the 28,000 that reached the employee.
        self.assertEqual(expense.amount, Decimal("30000"))
        reopen_payroll(row, admin)
        self.assertEqual(loan_remaining(loan), Decimal("10000"))
        self.assertEqual(
            Expense.objects.filter(category__name="Salaries").count(), 0)


class C8ImportBadRowsTests(TestCase):
    def test_bad_rows_flagged_in_preview_and_never_imported(self):
        admin = make_admin()
        long_name = "N" * 201
        long_address = "A" * 1001
        content = (
            "name,phone,address,opening_balance\n"
            "Good Shop,0300-1111111,Main Road,2500\n"
            "NaN Shop,0300-2222222,,NaN\n"
            "Inf Shop,0300-3333333,,Infinity\n"
            "Huge Shop,0300-4444444,,99999999999.99\n"
            "Precision Shop,0300-5555555,,100.999\n"
            f"{long_name},0300-6666666,,100\n"
            f"Long Address Shop,0300-7777777,{long_address},100\n"
        )
        rows = parse_import_file(csv_file(content))
        self.assertEqual(len(rows), 7)
        self.assertIsNone(rows[0]["error"])
        for bad in rows[1:]:
            self.assertIsNotNone(bad["error"])
        self.assertIn("real number", rows[1]["error"])
        self.assertIn("real number", rows[2]["error"])
        self.assertIn("9,999,999,999.99", rows[3]["error"])
        self.assertIn("2 decimal", rows[4]["error"])
        self.assertIn("200", rows[5]["error"])
        self.assertIn("1000", rows[6]["error"])
        saved = save_import_rows(rows, admin)
        self.assertEqual(saved, 1)
        self.assertTrue(Customer.objects.filter(name="Good Shop").exists())
        self.assertEqual(Customer.objects.count(), 1)


class C9AllocationScenarioTests(TestCase):
    def test_opening_then_full_payment_then_overpay(self):
        admin = make_admin()
        product = make_product()
        customer = make_customer(opening="10000")
        make_sale(admin, date(2026, 10, 5), customer, [
            {"product": product, "quantity": 10, "unit_price": 500},
        ], paid_now="5000")
        allocation = allocate_customer(customer)
        # Opening 10,000 untouched; the 5,000 sale is fully paid by its
        # own payment, so the invoice reads paid and balance is 10,000.
        self.assertEqual(allocation["sales"][0]["status"], "paid")
        self.assertEqual(allocation["balance"], Decimal("10000"))
        make_payment(admin, customer, date(2026, 10, 9), "4000")
        allocation = allocate_customer(customer)
        self.assertEqual(allocation["balance"], Decimal("6000"))
        self.assertEqual(allocation["sales"][0]["status"], "paid")
        make_payment(admin, customer, date(2026, 10, 12), "10000")
        allocation = allocate_customer(customer)
        # 6,000 owed, 10,000 paid: 4,000 advance credit.
        self.assertEqual(allocation["balance"], Decimal("-4000"))
        self.assertEqual(allocation["credit"], Decimal("4000"))


class C10QueryStringFuzzTests(TestCase):
    PAGES = [
        "home", "dashboard_activity", "search",
        "customers:list", "customers:import_upload",
        "customers:import_preview",
        "customers:search_fragment",
        "sales:sale_list", "sales:payment_list", "sales:product_list",
        "expenses:expense_list", "expenses:category_list",
        "employees:list", "employees:payroll_list",
        "employees:payroll_generate",
        "reports:index", "reports:monthly", "reports:profit",
        "reports:dues", "reports:register", "reports:expense_report",
        "reports:audit", "reports:recycle", "reports:settings",
    ]
    PK_PAGES = [
        ("customers:detail", "customer"),
        ("customers:balance_fragment", "customer"),
        ("customers:ledger_pdf", "customer"),
        ("customers:ledger_excel", "customer"),
        ("sales:sale_detail", "sale"),
        ("sales:invoice", "sale"),
        ("sales:invoice_pdf", "sale"),
        ("employees:detail", "employee"),
        ("employees:payroll_detail", "payroll"),
        ("employees:payslip_pdf", "payroll"),
    ]
    NASTY = {
        "page": "abc", "customer": "xyz", "product": "xyz",
        "from": "not-a-date", "to": "32-13-99", "user": "abc",
        "model": "Nope", "q": "<script>alert(1)</script>",
        "sort": "zzz", "preset": "nope", "year": "abc",
        "month": "13", "date": "99-99-9999", "format": "pdf",
    }

    def setUp(self):
        admin = make_admin()
        self.client.force_login(admin)
        product = make_product()
        self.customer = make_customer()
        self.sale = make_sale(admin, date(2026, 10, 10), self.customer, [
            {"product": product, "quantity": 2, "unit_price": 500},
        ], paid_now="200")
        employee = make_employee()
        generate_payroll(admin, 2026, 10)
        self.employee = employee
        self.payroll = Payroll.objects.get(employee=employee)
        self.objects = {
            "customer": self.customer.pk, "sale": self.sale.pk,
            "employee": self.employee.pk, "payroll": self.payroll.pk,
        }

    def _check(self, url, label):
        response = self.client.get(url)
        self.assertIn(
            response.status_code, (200, 302, 404),
            f"{label} returned {response.status_code} (a 500 is a bug)")

    def test_every_list_report_and_audit_page_survives_bad_query_strings(self):
        kitchen_sink = "&".join(f"{k}={v}" for k, v in self.NASTY.items())
        for name in self.PAGES:
            url = reverse(name)
            self._check(url, f"{name} (plain)")
            self._check(f"{url}?{kitchen_sink}", f"{name} (kitchen sink)")
            for key, value in self.NASTY.items():
                self._check(f"{url}?{key}={value}", f"{name}?{key}")
        for name, kind in self.PK_PAGES:
            url = reverse(name, args=[self.objects[kind]])
            self._check(url, f"{name} (plain)")
            self._check(f"{url}?{kitchen_sink}", f"{name} (kitchen sink)")
            for key, value in self.NASTY.items():
                self._check(f"{url}?{key}={value}", f"{name}?{key}")
            missing = reverse(name, args=[999999])
            response = self.client.get(missing)
            self.assertEqual(response.status_code, 404, f"{name} bad pk")


class C11MoneyPrecisionTests(TestCase):
    def test_half_up_rounding_and_exact_totals(self):
        self.assertEqual(q2(Decimal("2.675")), Decimal("2.68"))
        self.assertEqual(q2(Decimal("2.674")), Decimal("2.67"))
        self.assertEqual(q2(Decimal("0.125")), Decimal("0.13"))
        admin = make_admin()
        product = make_product()
        customer = make_customer()
        sale = make_sale(admin, date(2026, 10, 10), customer, [
            {"product": product, "quantity": 3, "unit_price": Decimal("333.33")},
        ], discount="0.01")
        # 3 x 333.33 = 999.99, minus 0.01 discount = 999.98 exactly.
        self.assertEqual(sale.total, Decimal("999.98"))
        full = make_employee(name="Full", salary="10000",
                             joined=date(2025, 1, 1))
        days, base = compute_proration(full, 2026, 9)
        self.assertEqual((days, base), (30, Decimal("10000")))
        one_day = make_employee(name="One Day", salary="10000",
                                joined=date(2026, 9, 30))
        days, base = compute_proration(one_day, 2026, 9)
        # 10,000 x 1 / 30 = 333.333... rounded half-up to 333.33.
        self.assertEqual((days, base), (1, Decimal("333.33")))
