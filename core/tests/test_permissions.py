"""Permission gates: every app URL redirects anonymous users to login,
and a logged-in user without permissions gets 403 on protected pages.
Exports and downloads are covered too."""

from django.test import TestCase
from django.urls import reverse

from core.tests.helpers import (
    make_admin, make_customer, make_employee, make_product, make_sale,
    make_user,
)
from datetime import date
from decimal import Decimal


class PermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_admin()
        cls.plain = make_user()
        cls.customer = make_customer()
        cls.product = make_product()
        cls.employee = make_employee()
        cls.sale = make_sale(
            cls.admin, date(2026, 10, 10), cls.customer,
            [{"product": cls.product, "quantity": 2, "unit_price": Decimal("500")}],
            paid_now="0",
        )

    def _urls(self):
        c, p, s = self.customer.pk, self.product.pk, self.sale.pk
        return [
            reverse("home"),
            reverse("customers:list"),
            reverse("customers:detail", args=[c]),
            reverse("customers:create"),
            reverse("customers:edit", args=[c]),
            reverse("customers:delete", args=[c]),
            reverse("customers:import_upload"),
            reverse("customers:ledger_pdf", args=[c]),
            reverse("customers:ledger_excel", args=[c]),
            reverse("sales:sale_list"),
            reverse("sales:sale_create"),
            reverse("sales:sale_detail", args=[s]),
            reverse("sales:sale_edit", args=[s]),
            reverse("sales:sale_delete", args=[s]),
            reverse("sales:invoice", args=[s]),
            reverse("sales:invoice_pdf", args=[s]),
            reverse("sales:product_list"),
            reverse("sales:product_create"),
            reverse("sales:payment_list"),
            reverse("sales:payment_create"),
            reverse("expenses:expense_list"),
            reverse("expenses:expense_create"),
            reverse("expenses:category_list"),
            reverse("employees:list"),
            reverse("employees:create"),
            reverse("employees:detail", args=[self.employee.pk]),
            reverse("employees:payroll_list"),
            reverse("employees:payroll_generate"),
            reverse("reports:index"),
            reverse("reports:monthly"),
            reverse("reports:dues"),
            reverse("reports:register"),
            reverse("reports:expense_report"),
            reverse("reports:audit"),
            reverse("reports:recycle"),
            reverse("reports:settings"),
        ]

    def test_anonymous_redirects_to_login(self):
        for url in self._urls():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/accounts/login/", response["Location"])

    def test_plain_user_gets_403_on_protected_pages(self):
        self.client.force_login(self.plain)
        for url in self._urls():
            with self.subTest(url=url):
                response = self.client.get(url)
                # The dashboard (home) only requires login, so a plain
                # user sees it; everything else must refuse.
                if url == reverse("home"):
                    self.assertEqual(response.status_code, 200)
                else:
                    self.assertEqual(response.status_code, 403)

    def test_admin_gets_200_everywhere(self):
        self.client.force_login(self.admin)
        for url in self._urls():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

    def test_exports_require_permission(self):
        # Anonymous export attempts redirect; plain users get 403.
        c, s = self.customer.pk, self.sale.pk
        export_urls = [
            reverse("customers:ledger_pdf", args=[c]),
            reverse("reports:monthly") + "?format=pdf",
            reverse("reports:dues") + "?format=excel",
            reverse("sales:invoice_pdf", args=[s]),
        ]
        for url in export_urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 302)
                self.client.force_login(self.plain)
                self.assertEqual(self.client.get(url).status_code, 403)
                self.client.logout()

    def test_backup_download_requires_password_and_permission(self):
        url = reverse("reports:backup_download")
        # Anonymous -> login redirect.
        self.assertEqual(self.client.post(url, {"password": "x"}).status_code, 302)
        # Plain user -> 403 even before the password is checked.
        self.client.force_login(self.plain)
        self.assertEqual(
            self.client.post(url, {"password": "TestPassword123"}).status_code, 403)
        self.client.logout()
        # Admin with a wrong password is sent back to settings, no file.
        self.client.force_login(self.admin)
        response = self.client.post(url, {"password": "wrong-password"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("settings", response["Location"])
