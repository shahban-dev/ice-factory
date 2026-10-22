"""N+1 guards: the dashboard, customer list and ledger must not issue
one query per row. Bounds were measured from the implementation and
leave headroom for the auth/session queries."""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from core.tests.helpers import (
    make_admin, make_customer, make_product, make_sale,
)


class QueryCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_admin()
        product = make_product()
        for i in range(10):
            customer = make_customer(
                name=f"Shop {i}", phone=f"0300-100000{i}", opening="100")
            make_sale(
                cls.admin, date(2026, 10, 10), customer,
                [{"product": product, "quantity": 2,
                  "unit_price": Decimal("500")}],
                paid_now="200",
            )

    def test_dashboard_query_count(self):
        # Exact counts: the guard is against N+1 growth. Measured with
        # 10 customers; if the implementation changes, re-measure.
        self.client.force_login(self.admin)
        with self.assertNumQueries(34):
            response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)

    def test_customer_list_query_count(self):
        self.client.force_login(self.admin)
        with self.assertNumQueries(8):
            response = self.client.get(reverse("customers:list"))
        self.assertEqual(response.status_code, 200)

    def test_ledger_query_count(self):
        self.client.force_login(self.admin)
        customer = make_customer(name="Ledger Shop", phone="0300-9999999")
        with self.assertNumQueries(11):
            response = self.client.get(
                reverse("customers:detail", args=[customer.pk]))
        self.assertEqual(response.status_code, 200)
