"""Group C, scenario C12: concurrency.

Two halves: 25 simultaneous sales get 25 distinct invoice numbers
(the locked counter row on PostgreSQL; SQLite serializes writers, so
threads retry briefly on lock errors, exactly like the existing
4-thread test), and two admins editing the same sale at once — the
second one gets the friendly stale-version message, not a lost update
and not a 500.
"""

import threading
import time
from datetime import date
from decimal import Decimal

from django.db import OperationalError
from django.test import TransactionTestCase
from django.urls import reverse

from core.models import get_settings
from core.tests.helpers import make_admin, make_customer, make_product, make_sale
from sales.forms import SaleItemFormSet
from sales.models import Sale


class C12ConcurrencyTests(TransactionTestCase):
    def test_25_simultaneous_sales_get_25_distinct_numbers(self):
        admin = make_admin()
        product = make_product()
        customer = make_customer()
        # Pre-create the settings row so threads never race its INSERT.
        get_settings()
        numbers = []
        errors = []

        def create_one():
            for _attempt in range(20):
                try:
                    sale = make_sale(admin, date(2026, 10, 10), customer, [
                        {"product": product, "quantity": 1,
                         "unit_price": 500},
                    ])
                    numbers.append(sale.invoice_number)
                    return
                except OperationalError as exc:
                    if "locked" not in str(exc):
                        errors.append(exc)
                        return
                    time.sleep(0.2)
            errors.append(OperationalError("still locked after retries"))

        threads = [threading.Thread(target=create_one) for _ in range(25)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(numbers), 25)
        self.assertEqual(len(set(numbers)), 25)
        self.assertEqual(Sale.objects.count(), 25)

    def test_second_admin_editing_same_sale_gets_stale_message(self):
        first = make_admin(username="admin-one")
        second = make_admin(username="admin-two")
        product = make_product()
        customer = make_customer()
        sale = make_sale(first, date(2026, 10, 10), customer, [
            {"product": product, "quantity": 2, "unit_price": 500},
        ])
        item = sale.items.get()
        prefix = SaleItemFormSet(instance=sale).prefix

        def edit_data(version, notes):
            return {
                "date": "2026-10-10", "customer": str(customer.pk),
                "discount": "0", "notes": notes, "reason": "test edit",
                "version": str(version), "paid_now": "0",
                "paid_method": "cash",
                f"{prefix}-TOTAL_FORMS": "1",
                f"{prefix}-INITIAL_FORMS": "1",
                f"{prefix}-MIN_NUM_FORMS": "0",
                f"{prefix}-MAX_NUM_FORMS": "1000",
                f"{prefix}-0-id": str(item.pk),
                f"{prefix}-0-product": str(product.pk),
                f"{prefix}-0-quantity": "2",
                f"{prefix}-0-unit_price": "500",
            }

        stale_version = Sale.objects.get(pk=sale.pk).version
        self.client.force_login(first)
        response = self.client.post(
            reverse("sales:sale_edit", args=[sale.pk]),
            edit_data(stale_version, "edited by first admin"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            Sale.objects.get(pk=sale.pk).notes, "edited by first admin")
        self.client.force_login(second)
        response = self.client.post(
            reverse("sales:sale_edit", args=[sale.pk]),
            edit_data(stale_version, "edited by second admin"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "was changed by")
        self.assertContains(response, "Reload and try again")
        # The second admin's edit did not land.
        self.assertEqual(
            Sale.objects.get(pk=sale.pk).notes, "edited by first admin")
