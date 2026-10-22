"""Excel formula-injection neutralization."""

from django.test import SimpleTestCase

from core.excel import safe_cell


class SafeCellTests(SimpleTestCase):
    def test_dangerous_prefixes_get_apostrophe(self):
        self.assertEqual(safe_cell("=2+2"), "'=2+2")
        self.assertEqual(safe_cell("+2+2"), "'+2+2")
        self.assertEqual(safe_cell("-2+2"), "'-2+2")
        self.assertEqual(safe_cell("@SUM(A1:A2)"), "'@SUM(A1:A2)")

    def test_safe_values_untouched(self):
        self.assertEqual(safe_cell("Ahmed Store"), "Ahmed Store")
        self.assertEqual(safe_cell(500), 500)
        self.assertEqual(safe_cell(None), None)
        self.assertEqual(safe_cell(""), "")
