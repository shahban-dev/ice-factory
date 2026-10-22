"""Money helpers: ROUND_HALF_UP and the Rs display format."""

from decimal import Decimal

from django.test import SimpleTestCase

from core.money import format_balance, format_rs, q2


class MoneyTests(SimpleTestCase):
    def test_round_half_up(self):
        # The classic float trap: 2.5 rounds up, not to even.
        self.assertEqual(q2(Decimal("2.5")), Decimal("2.50"))
        self.assertEqual(q2(Decimal("2.675")), Decimal("2.68"))
        self.assertEqual(q2(Decimal("9677.419354838709677419354839")),
                         Decimal("9677.42"))

    def test_format_rs_whole(self):
        self.assertEqual(format_rs(Decimal("1250000")), "Rs 1,250,000")
        self.assertEqual(format_rs(Decimal("0")), "Rs 0")

    def test_format_rs_decimals_only_when_nonzero(self):
        self.assertEqual(format_rs(Decimal("9677.42")), "Rs 9,677.42")
        self.assertEqual(format_rs(Decimal("500.00")), "Rs 500")

    def test_format_rs_negative(self):
        self.assertEqual(format_rs(Decimal("-600")), "Rs -600")

    def test_format_balance_credit(self):
        self.assertEqual(format_balance(Decimal("-5000")), "Rs 5,000 credit")
        self.assertEqual(format_balance(Decimal("3500")), "Rs 3,500")
