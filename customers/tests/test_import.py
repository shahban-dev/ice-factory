"""Customer import: preview errors, duplicate warnings, atomic save."""

import io

import openpyxl
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from core.tests.helpers import make_admin, make_customer
from customers.models import Customer
from customers.services import parse_import_file, save_import_rows


def csv_file(content):
    return SimpleUploadedFile("customers.csv", content.encode(), content_type="text/csv")


class ImportParseTests(TestCase):
    def test_csv_parse_and_errors(self):
        rows = parse_import_file(csv_file(
            "name,phone,address,opening_balance\n"
            "Good Shop,0300-1111111,Main Road,2500\n"
            "Bad Balance,0300-2222222,,notanumber\n"
            "Bad Phone,12345,,100\n"
        ))
        self.assertEqual(len(rows), 3)
        self.assertIsNone(rows[0]["error"])
        self.assertEqual(rows[0]["opening_balance"], 2500)
        self.assertIsNotNone(rows[1]["error"])
        self.assertIsNotNone(rows[2]["error"])

    def test_xlsx_parse(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["name", "phone", "address", "opening_balance"])
        ws.append(["XLSX Shop", "0300-8888888", "", "750"])
        buf = io.BytesIO()
        wb.save(buf)
        rows = parse_import_file(SimpleUploadedFile(
            "c.xlsx", buf.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "XLSX Shop")
        self.assertEqual(rows[0]["opening_balance"], 750)

    def test_duplicate_warnings(self):
        make_customer(name="Existing", phone="0300-1111111")
        rows = parse_import_file(csv_file(
            "name,phone,address,opening_balance\n"
            "New Shop,0300-1111111,,100\n"
            "Twin One,0300-3333333,,100\n"
            "Twin Two,0300-3333333,,100\n"
        ))
        self.assertEqual(len(rows[0]["warnings"]), 1)  # existing customer
        self.assertEqual(len(rows[2]["warnings"]), 1)  # duplicate in file

    def test_save_is_atomic(self):
        rows = parse_import_file(csv_file(
            "name,phone,address,opening_balance\n"
            "Good Shop,0300-1111111,,100\n"
            "Bad Row,0300-2222222,,oops\n"
        ))
        saved = save_import_rows(rows, make_admin())
        # Only the good row is saved; the bad row blocks itself, not others.
        self.assertEqual(saved, 1)
        self.assertTrue(Customer.objects.filter(name="Good Shop").exists())
        self.assertFalse(Customer.objects.filter(name="Bad Row").exists())

    def test_file_size_limit(self):
        big = "name,phone\n" + ("Shop,0300-1111111\n" * 6000)
        with self.assertRaises(ValidationError):
            parse_import_file(csv_file(big))
