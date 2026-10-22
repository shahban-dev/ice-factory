"""A6: Urdu names print correctly in PDFs.

Before the fix every PDF used Helvetica only, so an Urdu name printed
as black boxes. Now Arabic-script text is shaped (arabic-reshaper +
python-bidi) and rendered in the bundled Noto Sans Arabic font, while
Latin text is untouched. The font-embedding assertions below are the
regression test: if the Arabic font is not used, its name cannot appear
in the PDF bytes.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from core.pdf_text import contains_arabic, font_for, shape_text
from core.tests.helpers import (
    make_admin, make_customer, make_employee, make_product, make_sale,
)
from employees.models import Payroll
from employees.services import generate_payroll

URDU_NAME = "احمد آئس سٹور"


class PdfTextTests(TestCase):
    def test_latin_text_untouched(self):
        self.assertEqual(shape_text("Ahmed Store"), "Ahmed Store")
        self.assertFalse(contains_arabic("Ahmed Store"))
        self.assertEqual(font_for("Ahmed Store"), "Helvetica")

    def test_urdu_text_shaped_and_detected(self):
        shaped = shape_text(URDU_NAME)
        self.assertTrue(contains_arabic(URDU_NAME))
        self.assertNotEqual(shaped, URDU_NAME)
        self.assertEqual(font_for(URDU_NAME), "NotoSansArabic")
        self.assertEqual(font_for(URDU_NAME, bold=True), "NotoSansArabic-Bold")

    def test_mixed_text_keeps_latin(self):
        shaped = shape_text(f"Shop {URDU_NAME}")
        self.assertIn("Shop", shaped)
        self.assertNotEqual(shaped, f"Shop {URDU_NAME}")


class UrduPdfTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.client.force_login(self.admin)
        self.product = make_product()
        self.customer = make_customer(name=URDU_NAME)
        self.sale = make_sale(
            self.admin, date(2026, 10, 10), self.customer,
            [{"product": self.product, "quantity": 2,
              "unit_price": Decimal("500")}],
            paid_now="1000",
        )

    def test_invoice_pdf_embeds_arabic_font(self):
        response = self.client.get(
            reverse("sales:invoice_pdf", args=[self.sale.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(b"NotoSansArabic", response.content)

    def test_ledger_pdf_embeds_arabic_font(self):
        response = self.client.get(
            reverse("customers:ledger_pdf", args=[self.customer.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"NotoSansArabic", response.content)

    def test_dues_pdf_embeds_arabic_font(self):
        # The setUp sale is fully paid; add an unpaid one so this
        # customer appears in the dues report.
        make_sale(
            self.admin, date(2026, 10, 12), self.customer,
            [{"product": self.product, "quantity": 1,
              "unit_price": Decimal("500")}],
            paid_now="0",
        )
        response = self.client.get(
            reverse("reports:dues") + "?format=pdf")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"NotoSansArabic", response.content)

    def test_payslip_pdf_embeds_arabic_font(self):
        employee = make_employee(name=URDU_NAME)
        generate_payroll(self.admin, 2026, 10)
        row = Payroll.objects.get(employee=employee, year=2026, month=10)
        response = self.client.get(
            reverse("employees:payslip_pdf", args=[row.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"NotoSansArabic", response.content)
