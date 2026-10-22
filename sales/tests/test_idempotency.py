"""B4: double-tapping Save on a slow phone creates exactly one record."""

import uuid
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from core.tests.helpers import make_admin, make_customer, make_product
from expenses.models import Expense, ExpenseCategory
from sales.models import Payment, Sale


class IdempotencyTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.client.force_login(self.admin)
        self.customer = make_customer()
        self.product = make_product()

    def _sale_data(self, token):
        return {
            "date": "2026-10-10", "customer": self.customer.pk,
            "discount": "0", "notes": "", "paid_now": "0",
            "paid_method": "cash", "form_token": token,
            "items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0", "items-MAX_NUM_FORMS": "1000",
            "items-0-product": self.product.pk, "items-0-quantity": "2",
            "items-0-unit_price": "500", "items-0-id": "",
        }

    def test_double_sale_post_creates_one_sale(self):
        token = str(uuid.uuid4())
        first = self.client.post(
            reverse("sales:sale_create"), self._sale_data(token))
        second = self.client.post(
            reverse("sales:sale_create"), self._sale_data(token))
        self.assertEqual(Sale.objects.count(), 1)
        sale = Sale.objects.get()
        # The replay redirects to the original sale, it does not
        # create a second one or error.
        self.assertEqual(second.status_code, 302)
        self.assertIn(f"/sales/{sale.pk}/", second["Location"])

    def test_same_form_different_tokens_create_two_sales(self):
        self.client.post(
            reverse("sales:sale_create"),
            self._sale_data(str(uuid.uuid4())))
        self.client.post(
            reverse("sales:sale_create"),
            self._sale_data(str(uuid.uuid4())))
        self.assertEqual(Sale.objects.count(), 2)

    def test_double_payment_post_creates_one_payment(self):
        token = str(uuid.uuid4())
        data = {
            "customer": self.customer.pk, "date": "2026-10-10",
            "amount": "500", "method": "cash", "reference": "",
            "form_token": token,
        }
        self.client.post(reverse("sales:payment_create"), data)
        self.client.post(reverse("sales:payment_create"), data)
        self.assertEqual(Payment.objects.count(), 1)

    def test_double_expense_post_creates_one_expense(self):
        category = ExpenseCategory.objects.create(name="Diesel")
        token = str(uuid.uuid4())
        data = {
            "date": "2026-10-10", "category": category.pk,
            "amount": "1000", "description": "Fuel",
            "method": "cash", "form_token": token,
        }
        self.client.post(reverse("expenses:expense_create"), data)
        self.client.post(reverse("expenses:expense_create"), data)
        self.assertEqual(Expense.objects.count(), 1)

    def test_missing_or_bad_token_still_creates(self):
        # Old forms and non-browser clients carry no token: they must
        # keep working, just without replay protection.
        data = self._sale_data("")
        self.client.post(reverse("sales:sale_create"), data)
        data["form_token"] = "not-a-uuid"
        self.client.post(reverse("sales:sale_create"), data)
        self.assertEqual(Sale.objects.count(), 2)

    def test_form_renders_a_fresh_token(self):
        response = self.client.get(reverse("sales:sale_create"))
        self.assertEqual(response.status_code, 200)
        token = response.context["form"]["form_token"].value()
        uuid.UUID(token)  # raises unless the rendered token is a UUID
        response = self.client.get(reverse("sales:payment_create"))
        self.assertNotEqual(
            token, response.context["form"]["form_token"].value())
