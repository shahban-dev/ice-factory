"""Customer rules: phone normalization/validation, duplicate warnings,
and the delete guard."""

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from core.tests.helpers import make_admin, make_customer, make_sale, make_product
from customers.models import Customer, normalize_phone, validate_phone
from datetime import date
from decimal import Decimal


class PhoneTests(TestCase):
    def test_normalization(self):
        self.assertEqual(normalize_phone("+92 300 1234567"), "0300-1234567")
        self.assertEqual(normalize_phone("03001234567"), "0300-1234567")
        self.assertEqual(normalize_phone("0300-1234567"), "0300-1234567")
        self.assertEqual(normalize_phone(""), "")

    def test_validation(self):
        validate_phone("0300-1234567")
        with self.assertRaises(ValidationError):
            validate_phone("12345")
        with self.assertRaises(ValidationError):
            validate_phone("0400-1234567")  # must start with 03

    def test_model_normalizes_on_save(self):
        customer = make_customer(phone="03001234567")
        self.assertEqual(customer.phone, "0300-1234567")


class DuplicatePhoneTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.client.force_login(self.admin)
        make_customer(name="First Shop", phone="0300-1111111")

    def test_duplicate_phone_warns_with_link_but_saves(self):
        response = self.client.post(reverse("customers:create"), {
            "name": "Second Shop", "phone": "0300-1111111",
            "address": "", "notes": "", "opening_balance": "0", "is_active": "on",
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Customer.objects.filter(name="Second Shop").exists())
        # The warning message names the existing customer.
        from django.contrib.messages import get_messages
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("First Shop" in m for m in messages))


class CustomerDeleteGuardTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.client.force_login(self.admin)
        self.customer = make_customer()
        self.product = make_product()

    def test_delete_blocked_with_sales(self):
        make_sale(self.admin, date(2026, 10, 10), self.customer,
                  [{"product": self.product, "quantity": 1,
                    "unit_price": Decimal("500")}])
        response = self.client.get(
            reverse("customers:delete", args=[self.customer.pk]))
        self.assertContains(response, "cannot be deleted")

    def test_delete_blocked_with_nonzero_balance(self):
        customer = make_customer(name="Owes", opening="500")
        response = self.client.get(
            reverse("customers:delete", args=[customer.pk]))
        self.assertContains(response, "cannot be deleted")

    def test_delete_allowed_when_clean(self):
        response = self.client.post(
            reverse("customers:delete", args=[self.customer.pk]),
            {"reason": "test"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Customer.all_objects.get(pk=self.customer.pk).is_deleted)
