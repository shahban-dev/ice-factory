"""B5: WhatsApp wa.me links. B6: password change page, admin delete lock."""

from datetime import date

from django.contrib import admin
from django.test import RequestFactory, TestCase
from django.urls import reverse

from core.tests.helpers import (
    make_admin,
    make_customer,
    make_product,
    make_sale,
)
from core.whatsapp import wa_number, whatsapp_url
from customers.models import Customer
from employees.models import Employee, Loan, Payroll
from expenses.models import Expense, ExpenseCategory
from sales.models import Payment, Product, Sale, SaleItem


class WhatsappHelperTests(TestCase):
    def test_mobile_converts(self):
        self.assertEqual(wa_number("0300-1234567"), "923001234567")
        self.assertEqual(wa_number("03001234567"), "923001234567")
        self.assertEqual(wa_number("+92 300 1234567"), "923001234567")

    def test_non_mobile_returns_none(self):
        self.assertIsNone(wa_number(""))
        self.assertIsNone(wa_number(None))
        self.assertIsNone(wa_number("021-1234567"))  # landline
        self.assertIsNone(wa_number("0300-123"))  # too short

    def test_url_encodes_message(self):
        url = whatsapp_url("0300-1234567", "Hello, Rs 1,000 due.")
        self.assertTrue(url.startswith("https://wa.me/923001234567?text="))
        self.assertIn("Rs%201%2C000", url)
        self.assertIsNone(whatsapp_url("021-1234567", "Hello"))


class WhatsappButtonTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.client.force_login(self.admin)
        self.product = make_product()

    def test_sale_detail_shows_share_button_for_mobile_customer(self):
        customer = make_customer(phone="0300-1234567")
        sale = make_sale(self.admin, date(2026, 10, 10),
                         customer, [{"product": self.product, "quantity": 2,
                                     "unit_price": 500}])
        response = self.client.get(reverse("sales:sale_detail", args=[sale.pk]))
        self.assertContains(response, "wa.me/923001234567")
        self.assertContains(response, "Share invoice on WhatsApp")

    def test_walkin_sale_has_no_share_button(self):
        sale = make_sale(self.admin, date(2026, 10, 10),
                         None, [{"product": self.product, "quantity": 2,
                                 "unit_price": 500}], paid_now="1000")
        response = self.client.get(reverse("sales:sale_detail", args=[sale.pk]))
        self.assertNotContains(response, "wa.me/")

    def test_customer_detail_shows_dues_reminder(self):
        customer = make_customer(phone="0300-1234567", opening="5000")
        response = self.client.get(
            reverse("customers:detail", args=[customer.pk]))
        self.assertContains(response, "wa.me/923001234567")
        self.assertContains(response, "Send dues reminder on WhatsApp")

    def test_dues_report_row_has_reminder_link(self):
        customer = make_customer(name="Debtor", phone="0300-9999999",
                                 opening="7000")
        response = self.client.get(reverse("reports:dues"))
        self.assertContains(response, "wa.me/923009999999")


class PasswordChangeTests(TestCase):
    def setUp(self):
        self.admin = make_admin(password="OldPass12345")
        self.client.force_login(self.admin)

    def test_change_page_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("password_change"))
        self.assertEqual(response.status_code, 302)

    def test_password_change_works(self):
        response = self.client.post(reverse("password_change"), {
            "old_password": "OldPass12345",
            "new_password1": "NewSecurePass123",
            "new_password2": "NewSecurePass123",
        })
        self.assertRedirects(response, reverse("password_change_done"))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("NewSecurePass123"))

    def test_wrong_old_password_rejected(self):
        response = self.client.post(reverse("password_change"), {
            "old_password": "wrong-password",
            "new_password1": "NewSecurePass123",
            "new_password2": "NewSecurePass123",
        })
        self.assertEqual(response.status_code, 200)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("OldPass12345"))


class AdminDeleteLockTests(TestCase):
    def test_business_models_cannot_be_deleted_in_admin(self):
        factory = RequestFactory()
        request = factory.get("/site-admin/")
        request.user = make_admin()
        for model in (Customer, Sale, SaleItem, Payment, Expense,
                      ExpenseCategory, Employee, Payroll, Product, Loan):
            model_admin = admin.site._registry[model]
            self.assertFalse(
                model_admin.has_delete_permission(request),
                f"{model.__name__} must not be deletable in admin")
