"""B9: dues report + audit log stay fast at scale.

The regression tests are query counts, not just timings: a count bound
fails on the old per-debtor loop no matter how fast the machine is, and
passes on the bulk version. A timing test at full scale (500 customers,
3,000 sales) proves the 3-second page target directly.
"""

import time
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core.tests.helpers import (
    make_admin,
    make_customer,
    make_employee,
    make_payment,
    make_product,
    make_sale,
)
from customers.models import Customer
from employees.models import Employee, Loan
from reports.services import dues_report
from reports.system_services import (
    audit_entries,
    recycle_bin_entries,
    restore_from_bin,
)
from sales.models import Payment, Sale, SaleItem


class DuesReportQueryTests(TestCase):
    def test_query_count_is_bounded_not_per_debtor(self):
        admin = make_admin()
        product = make_product()
        for i in range(30):
            customer = make_customer(name=f"Shop {i}")
            make_sale(admin, date(2026, 10, 5), customer, [
                {"product": product, "quantity": 2, "unit_price": 500},
            ])
        with CaptureQueriesContext(connection) as ctx:
            rows = dues_report()
        self.assertLessEqual(len(ctx), 15)
        self.assertEqual(len(rows), 30)

    def test_dues_values_still_correct(self):
        admin = make_admin()
        product = make_product()
        debtor = make_customer(name="Debtor", phone="0300-1111111")
        make_sale(admin, date(2026, 10, 5), debtor, [
            {"product": product, "quantity": 10, "unit_price": 500},
        ])
        make_payment(admin, debtor, date(2026, 10, 9), "2000")
        settled = make_customer(name="Settled")
        make_sale(admin, date(2026, 10, 6), settled, [
            {"product": product, "quantity": 2, "unit_price": 500},
        ], paid_now="1000")
        rows = {r["customer"].name: r for r in dues_report()}
        self.assertIn("Debtor", rows)
        self.assertNotIn("Settled", rows)
        self.assertEqual(rows["Debtor"]["balance"], Decimal("3000"))
        self.assertEqual(rows["Debtor"]["oldest_unpaid"], date(2026, 10, 5))
        self.assertEqual(rows["Debtor"]["last_payment"], date(2026, 10, 9))


class AuditLogQueryTests(TestCase):
    def test_query_count_bounded_and_diff_intact(self):
        customer = make_customer(name="Old Name")
        customer.name = "New Name"
        customer._change_reason = "Renamed"
        customer.save()
        with CaptureQueriesContext(connection) as ctx:
            entries = audit_entries(model_name="Customer")
        self.assertLessEqual(len(ctx), 20)
        changed = [e for e in entries if e["type"] == "Changed"]
        self.assertTrue(changed)
        self.assertTrue(any(
            "name: Old Name → New Name" in c
            for e in changed for c in e["changes"]
        ))

    def test_loan_appears_in_audit_and_bin(self):
        admin = make_admin()
        employee = make_employee(name="Loan Man")
        loan = Loan.objects.create(
            employee=employee, date=date(2026, 10, 1), amount=10000,
            monthly_installment=2000)
        entries = audit_entries(model_name="Loan")
        self.assertTrue(any(e["object"].startswith("Loan Man") for e in entries))
        Loan.objects.filter(pk=loan.pk).update(is_deleted=True)
        bin_rows = recycle_bin_entries()
        self.assertTrue(any(
            r["model"] == "Loan" and r["pk"] == loan.pk for r in bin_rows))
        message = restore_from_bin("loan", loan.pk, admin)
        self.assertIn("Restored", message)
        self.assertTrue(Loan.objects.filter(pk=loan.pk).exists())

    def test_loan_restore_refused_when_employee_deleted(self):
        admin = make_admin()
        employee = make_employee(name="Gone Man")
        loan = Loan.objects.create(
            employee=employee, date=date(2026, 10, 1), amount=10000,
            monthly_installment=2000)
        Loan.objects.filter(pk=loan.pk).update(is_deleted=True)
        Employee.objects.filter(pk=employee.pk).update(is_deleted=True)
        with self.assertRaises(ValidationError):
            restore_from_bin("loan", loan.pk, admin)


class DuesTimingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        product = make_product()
        customers = Customer.objects.bulk_create([
            Customer(name=f"Shop {i}", phone=f"0300{i:07d}")
            for i in range(500)
        ])
        sales = Sale.objects.bulk_create([
            Sale(customer=c, date=date(2026, 10, 5),
                 invoice_number=f"INV-2026-{i:04d}")
            for i, c in enumerate(
                [c for c in customers for _ in range(6)])
        ])
        SaleItem.objects.bulk_create([
            SaleItem(sale=s, product=product, quantity=10,
                     unit_price=Decimal("500"))
            for s in sales
        ])
        Payment.objects.bulk_create([
            Payment(customer=s.customer, date=date(2026, 10, 9),
                    amount=Decimal("2000"))
            for s in sales[::2]
        ])
        cls.admin = make_admin()

    def test_dues_report_under_3_seconds_at_scale(self):
        start = time.monotonic()
        rows = dues_report()
        elapsed = time.monotonic() - start
        self.assertEqual(len(rows), 500)
        self.assertLess(elapsed, 3.0)

    def test_dues_page_under_3_seconds_at_scale(self):
        self.client.force_login(self.admin)
        start = time.monotonic()
        response = self.client.get(reverse("reports:dues"))
        elapsed = time.monotonic() - start
        self.assertEqual(response.status_code, 200)
        self.assertLess(elapsed, 3.0)
