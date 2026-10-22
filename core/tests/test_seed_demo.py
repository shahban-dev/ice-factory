"""seed_demo: refusal gates and a successful seed with correct totals."""

import tempfile
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from customers.models import Customer
from reports.services import monthly_report
from core.management.commands.seed_demo import previous_month
from django.utils import timezone


class SeedDemoTests(TestCase):
    def test_refuses_with_debug_off_and_no_force(self):
        with override_settings(DEBUG=False):
            with self.assertRaises(CommandError):
                call_command("seed_demo")

    def test_refuses_when_demo_already_exists(self):
        Customer.objects.create(name="Demo Existing")
        with override_settings(DEBUG=True):
            with self.assertRaises(CommandError):
                call_command("seed_demo")

    def test_seed_creates_data_matching_expected_totals(self):
        with override_settings(DEBUG=True):
            with tempfile.TemporaryDirectory() as tmp:
                out = str(Path(tmp) / "totals.txt")
                call_command("seed_demo", output=out)
                year, month = previous_month(timezone.localdate())
                m = monthly_report(year, month)
                from decimal import Decimal
                self.assertEqual(m["billed"], Decimal("30900"))
                self.assertEqual(m["collected"], Decimal("21900"))
                self.assertEqual(m["expenses"], Decimal("98000"))
                self.assertEqual(m["salaries_paid"], Decimal("55000"))
                self.assertEqual(m["outstanding_at_month_end"], Decimal("25000"))
                text = Path(out).read_text()
                self.assertIn("Billed: Rs 30900", text)
                self.assertIn("Outstanding at month end: Rs 25000", text)
                self.assertTrue(
                    Customer.objects.filter(name__startswith="Demo ").exists())
