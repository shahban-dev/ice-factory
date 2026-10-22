"""Invoice numbers stay unique when several sales are saved at once.
SQLite serializes writers, so threads retry briefly on lock errors; the
real guarantee on PostgreSQL is the locked counter row.
"""

import threading
import time
from datetime import date
from decimal import Decimal

from django.db import OperationalError
from django.test import TransactionTestCase

from core.models import get_settings
from core.tests.helpers import make_admin, make_customer, make_product
from sales.models import Sale
from sales.services import create_sale


class ConcurrentInvoiceTests(TransactionTestCase):
    def test_simultaneous_saves_get_distinct_numbers(self):
        admin = make_admin()
        product = make_product()
        customer = make_customer()
        # Pre-create the settings row so threads never race its INSERT.
        get_settings()
        numbers = []
        errors = []

        def create_one():
            for attempt in range(10):
                try:
                    sale = create_sale(admin, date(2026, 10, 10), customer,
                                       Decimal("0"), [
                                           {"product": product, "quantity": 1,
                                            "unit_price": Decimal("500")},
                                       ], Decimal("0"), "cash")
                    numbers.append(sale.invoice_number)
                    return
                except OperationalError as exc:
                    if "locked" not in str(exc):
                        errors.append(exc)
                        return
                    time.sleep(0.2)
            errors.append(OperationalError("still locked after retries"))

        threads = [threading.Thread(target=create_one) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(set(numbers)), 4)
        self.assertEqual(Sale.objects.count(), 4)
