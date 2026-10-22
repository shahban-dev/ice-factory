"""B2: profit report presets, week-start setting, dashboard today
figures."""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from core.models import get_settings
from core.tests.helpers import (
    make_admin,
    make_customer,
    make_product,
    make_sale,
)
from expenses.models import Expense, ExpenseCategory
from reports.services import period_figures, preset_range, week_range


class ProfitPresetTests(TestCase):
    def test_week_monday_default(self):
        # Thursday 2026-10-22, Monday start: week is Mon 19th - Sun 25th.
        start, end = week_range(date(2026, 10, 22), 0)
        self.assertEqual((start, end), (date(2026, 10, 19), date(2026, 10, 25)))

    def test_week_sunday_start(self):
        # Sunday start: week is Sun 18th - Sat 24th.
        start, end = week_range(date(2026, 10, 22), 6)
        self.assertEqual((start, end), (date(2026, 10, 18), date(2026, 10, 24)))

    def test_presets(self):
        today = date(2026, 10, 22)
        self.assertEqual(
            preset_range("today", today, 0)[:2], (today, today))
        self.assertEqual(
            preset_range("yesterday", today, 0)[:2],
            (date(2026, 10, 21), date(2026, 10, 21)))
        self.assertEqual(
            preset_range("last_month", today, 0)[:2],
            (date(2026, 9, 1), date(2026, 9, 30)))
        self.assertEqual(
            preset_range("last_month", date(2026, 1, 15), 0)[:2],
            (date(2025, 12, 1), date(2025, 12, 31)))
        # Custom dates in reverse order are swapped, not rejected.
        self.assertEqual(
            preset_range("custom", today, 0,
                         date(2026, 10, 10), date(2026, 10, 1))[:2],
            (date(2026, 10, 1), date(2026, 10, 10)))
        # Unknown preset and custom without dates fall back to this month.
        self.assertEqual(
            preset_range("bogus", today, 0)[:2],
            (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(
            preset_range("custom", today, 0)[:2],
            (date(2026, 10, 1), date(2026, 10, 31)))

    def test_period_figures_hand_calculated(self):
        admin = make_admin()
        customer = make_customer()
        product = make_product()
        make_sale(admin, date(2026, 10, 5), customer, [
            {"product": product, "quantity": 10, "unit_price": Decimal("500")},
        ], paid_now="2000", discount="500")
        category = ExpenseCategory.objects.create(name="Diesel")
        Expense.objects.create(
            date=date(2026, 10, 6), category=category,
            amount=Decimal("1000"), created_by=admin, updated_by=admin)
        figures = period_figures(date(2026, 10, 1), date(2026, 10, 31))
        # Billed 4,500 (5,000 - 500 discount), collected 2,000,
        # expenses 1,000, sales profit 3,500, cash profit 1,000.
        self.assertEqual(figures["billed"], Decimal("4500"))
        self.assertEqual(figures["collected"], Decimal("2000"))
        self.assertEqual(figures["expenses"], Decimal("1000"))
        self.assertEqual(figures["sales_profit"], Decimal("3500"))
        self.assertEqual(figures["cash_profit"], Decimal("1000"))

    def test_profit_view_and_dashboard_today(self):
        admin = make_admin()
        customer = make_customer()
        product = make_product()
        make_sale(admin, date(2026, 10, 22), customer, [
            {"product": product, "quantity": 2, "unit_price": Decimal("500")},
        ], paid_now="1000")
        category = ExpenseCategory.objects.create(name="Diesel")
        Expense.objects.create(
            date=date(2026, 10, 22), category=category,
            amount=Decimal("300"), created_by=admin, updated_by=admin)
        self.client.force_login(admin)
        response = self.client.get(reverse("reports:profit") + "?preset=today")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["figures"]["billed"], Decimal("1000"))
        self.assertEqual(response.context["figures"]["expenses"], Decimal("300"))
        dashboard = self.client.get(reverse("home"))
        self.assertEqual(dashboard.context["today_expenses"], Decimal("300"))
        self.assertEqual(
            dashboard.context["today_sales_profit"], Decimal("700"))

    def test_week_start_setting_changes_preset(self):
        settings_obj = get_settings()
        settings_obj.week_start_day = 6  # Sunday
        settings_obj.save()
        admin = make_admin()
        self.client.force_login(admin)
        response = self.client.get(reverse("reports:profit") + "?preset=week")
        self.assertEqual(response.status_code, 200)
        # Week containing 2026-10-22 with a Sunday start.
        self.assertEqual(response.context["start"], date(2026, 10, 18))
        self.assertEqual(response.context["end"], date(2026, 10, 24))
