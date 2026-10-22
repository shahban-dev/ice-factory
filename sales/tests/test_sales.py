"""Sales rules: totals, discounts, invoice numbers, walk-in, paid-now,
future dates, allocation, edits, deletes and restores."""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from core.services import ConcurrentEditError
from core.tests.helpers import (
    make_admin, make_customer, make_payment, make_product, make_sale,
)
from django.urls import reverse
from sales.forms import SaleForm
from sales.models import Payment, Sale
from sales.services import (
    allocate_customer, create_payment, create_sale, delete_sale,
    update_payment, update_sale,
)


class SaleTotalsTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.p1 = make_product("Full Block", "500")
        self.p2 = make_product("Half Block", "300")
        self.customer = make_customer()

    def test_subtotal_and_discount(self):
        sale = make_sale(self.admin, date(2026, 10, 10), self.customer, [
            {"product": self.p1, "quantity": 10, "unit_price": Decimal("500")},
            {"product": self.p2, "quantity": 5, "unit_price": Decimal("300")},
        ], discount="100")
        self.assertEqual(sale.subtotal, Decimal("6500"))
        self.assertEqual(sale.total, Decimal("6400"))

    def test_discount_cannot_exceed_subtotal(self):
        with self.assertRaises(ValidationError):
            make_sale(self.admin, date(2026, 10, 10), self.customer, [
                {"product": self.p1, "quantity": 1, "unit_price": Decimal("500")},
            ], discount="600")

    def test_total_must_be_positive(self):
        with self.assertRaises(ValidationError):
            make_sale(self.admin, date(2026, 10, 10), self.customer, [
                {"product": self.p1, "quantity": 1, "unit_price": Decimal("500")},
            ], discount="500")

    def test_no_items_rejected(self):
        with self.assertRaises(ValidationError):
            make_sale(self.admin, date(2026, 10, 10), self.customer, [])

    def test_future_sale_blocked(self):
        with self.assertRaises(ValidationError):
            make_sale(self.admin, date(2099, 1, 1), self.customer, [
                {"product": self.p1, "quantity": 1, "unit_price": Decimal("500")},
            ])


class InvoiceNumberTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.p1 = make_product()
        self.customer = make_customer()

    def _sale(self, sale_date):
        return make_sale(self.admin, sale_date, self.customer, [
            {"product": self.p1, "quantity": 1, "unit_price": Decimal("500")},
        ])

    def test_sequence(self):
        s1 = self._sale(date(2026, 10, 10))
        s2 = self._sale(date(2026, 10, 11))
        self.assertEqual(s1.invoice_number, "INV-2026-0001")
        self.assertEqual(s2.invoice_number, "INV-2026-0002")

    def test_year_rollover(self):
        s2025 = self._sale(date(2025, 12, 31))
        s2026 = self._sale(date(2026, 1, 1))
        self.assertEqual(s2025.invoice_number, "INV-2025-0001")
        self.assertEqual(s2026.invoice_number, "INV-2026-0001")

    def test_deleted_numbers_never_reused(self):
        s1 = self._sale(date(2026, 10, 10))
        delete_sale(Sale.objects.get(pk=s1.pk), self.admin, "test")
        s2 = self._sale(date(2026, 10, 11))
        self.assertEqual(s2.invoice_number, "INV-2026-0002")

    def test_invoice_number_never_changes_on_edit(self):
        sale = self._sale(date(2026, 10, 10))
        version = Sale.objects.get(pk=sale.pk).version
        updated, _ = update_sale(
            Sale.objects.get(pk=sale.pk), self.admin, date(2026, 10, 10),
            self.customer, Decimal("0"),
            [{"product": self.p1, "quantity": 3, "unit_price": Decimal("500")}],
            "", "more blocks", version)
        self.assertEqual(updated.invoice_number, sale.invoice_number)


class WalkInTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.p1 = make_product()

    def test_walk_in_must_be_fully_paid(self):
        with self.assertRaises(ValidationError):
            create_sale(self.admin, date(2026, 10, 10), None, Decimal("0"), [
                {"product": self.p1, "quantity": 2, "unit_price": Decimal("500")},
            ], Decimal("500"), "cash")

    def test_walk_in_edit_updates_payment(self):
        sale = create_sale(self.admin, date(2026, 10, 10), None, Decimal("0"), [
            {"product": self.p1, "quantity": 2, "unit_price": Decimal("500")},
        ], Decimal("1000"), "cash")
        version = Sale.objects.get(pk=sale.pk).version
        updated, _ = update_sale(
            Sale.objects.get(pk=sale.pk), self.admin, date(2026, 10, 10),
            None, Decimal("0"),
            [{"product": self.p1, "quantity": 3, "unit_price": Decimal("500")}],
            "", "more blocks", version)
        self.assertEqual(Payment.objects.get(sale=updated).amount, Decimal("1500"))

    def test_paid_now_cannot_exceed_total(self):
        customer = make_customer()
        with self.assertRaises(ValidationError):
            make_sale(self.admin, date(2026, 10, 10), customer, [
                {"product": self.p1, "quantity": 1, "unit_price": Decimal("500")},
            ], paid_now="600")


class AllocationTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.p1 = make_product()
        self.customer = make_customer(opening="1000")

    def test_opening_first_then_oldest(self):
        s1 = make_sale(self.admin, date(2026, 10, 10), self.customer, [
            {"product": self.p1, "quantity": 10, "unit_price": Decimal("500")},
        ], paid_now="2000")
        s2 = make_sale(self.admin, date(2026, 10, 15), self.customer, [
            {"product": self.p1, "quantity": 3, "unit_price": Decimal("500")},
        ])
        a = allocate_customer(self.customer)
        # A7: a sale's own linked payments stay with that sale first.
        # s1's Rs 2,000 paid-now covers s1 (not the opening balance),
        # so the opening balance is still fully outstanding.
        self.assertEqual(a["opening_allocated"], Decimal("0"))
        self.assertEqual(a["opening_remaining"], Decimal("1000"))
        self.assertEqual(a["sales"][0]["status"], "partial")
        self.assertEqual(a["sales"][0]["allocated"], Decimal("2000"))
        self.assertEqual(a["sales"][0]["remaining"], Decimal("3000"))
        self.assertEqual(a["sales"][1]["status"], "unpaid")
        self.assertEqual(a["balance"], Decimal("1000") + Decimal("6500") - Decimal("2000"))

    def test_exact_payment(self):
        make_sale(self.admin, date(2026, 10, 10), self.customer, [
            {"product": self.p1, "quantity": 2, "unit_price": Decimal("500")},
        ], paid_now="0")
        make_payment(self.admin, self.customer, date(2026, 10, 11), "2000")
        a = allocate_customer(self.customer)
        self.assertEqual(a["sales"][0]["status"], "paid")
        self.assertEqual(a["balance"], Decimal("0"))

    def test_overpayment_is_credit(self):
        make_sale(self.admin, date(2026, 10, 10), self.customer, [
            {"product": self.p1, "quantity": 2, "unit_price": Decimal("500")},
        ], paid_now="0")
        make_payment(self.admin, self.customer, date(2026, 10, 11), "5000")
        a = allocate_customer(self.customer)
        self.assertEqual(a["credit"], Decimal("3000"))
        self.assertEqual(a["balance"], Decimal("-3000"))

    def test_negative_opening_is_extra_payment(self):
        customer = make_customer(name="Credit Co", opening="-500")
        make_sale(self.admin, date(2026, 10, 10), customer, [
            {"product": self.p1, "quantity": 4, "unit_price": Decimal("500")},
        ])
        a = allocate_customer(customer)
        self.assertEqual(a["sales"][0]["allocated"], Decimal("500"))
        self.assertEqual(a["sales"][0]["remaining"], Decimal("1500"))

    def test_edit_after_payment_reallocates(self):
        sale = make_sale(self.admin, date(2026, 10, 10), self.customer, [
            {"product": self.p1, "quantity": 10, "unit_price": Decimal("500")},
        ], paid_now="0")
        make_payment(self.admin, self.customer, date(2026, 10, 11), "2000")
        version = Sale.objects.get(pk=sale.pk).version
        update_sale(
            Sale.objects.get(pk=sale.pk), self.admin, date(2026, 10, 10),
            self.customer, Decimal("0"),
            [{"product": self.p1, "quantity": 4, "unit_price": Decimal("500")}],
            "", "fewer blocks", version)
        a = allocate_customer(self.customer)
        # Opening 1000 + sale 2000 - payment 2000 = 1000 owed; the sale
        # itself is partial (1000 of its 2000 covered after the opening).
        self.assertEqual(a["sales"][0]["status"], "partial")
        self.assertEqual(a["sales"][0]["remaining"], Decimal("1000"))
        self.assertEqual(a["balance"], Decimal("1000"))

    def test_delete_sale_removes_only_linked_payments(self):
        sale = make_sale(self.admin, date(2026, 10, 10), self.customer, [
            {"product": self.p1, "quantity": 2, "unit_price": Decimal("500")},
        ], paid_now="200")
        general = make_payment(self.admin, self.customer, date(2026, 10, 11), "100")
        delete_sale(Sale.objects.get(pk=sale.pk), self.admin, "test")
        self.assertTrue(Sale.all_objects.get(pk=sale.pk).is_deleted)
        self.assertTrue(
            Payment.all_objects.filter(sale_id=sale.pk, is_deleted=True).exists())
        self.assertTrue(Payment.objects.filter(pk=general.pk).exists())

    def test_stale_version_rejected(self):
        sale = make_sale(self.admin, date(2026, 10, 10), self.customer, [
            {"product": self.p1, "quantity": 2, "unit_price": Decimal("500")},
        ])
        with self.assertRaises(ConcurrentEditError):
            update_sale(
                Sale.objects.get(pk=sale.pk), self.admin, date(2026, 10, 10),
                self.customer, Decimal("0"),
                [{"product": self.p1, "quantity": 2, "unit_price": Decimal("500")}],
                "", "stale", 999)

    def test_customer_move_moves_linked_payments(self):
        other = make_customer(name="Other Shop", phone="0300-2222222")
        sale = make_sale(self.admin, date(2026, 10, 10), self.customer, [
            {"product": self.p1, "quantity": 2, "unit_price": Decimal("500")},
        ], paid_now="400")
        version = Sale.objects.get(pk=sale.pk).version
        update_sale(
            Sale.objects.get(pk=sale.pk), self.admin, date(2026, 10, 10),
            other, Decimal("0"),
            [{"product": self.p1, "quantity": 2, "unit_price": Decimal("500")}],
            "", "wrong customer", version)
        self.assertEqual(Payment.objects.get(sale=sale).customer_id, other.pk)


class PaymentGuardTests(TestCase):
    """A2/A3: no orphan payments, no customer drift, walk-in amounts
    locked, and sale dates move their linked payments."""

    def setUp(self):
        self.admin = make_admin()
        self.p1 = make_product()
        self.customer = make_customer()
        self.other = make_customer(name="Other Shop", phone="0300-2222222")

    def test_create_payment_without_customer_rejected(self):
        with self.assertRaises(ValidationError):
            create_payment(
                self.admin, None, date(2026, 10, 10), Decimal("500"), "cash")
        self.assertEqual(Payment.objects.count(), 0)

    def test_payment_form_without_customer_is_error_not_500(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("sales:payment_create"), {
            "customer": "", "date": "2026-10-10", "amount": "500",
            "method": "cash", "reference": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertIn("customer", response.context["form"].errors)

    def test_walkin_payment_amount_locked(self):
        walkin = make_sale(self.admin, date(2026, 10, 10), None, [
            {"product": self.p1, "quantity": 2, "unit_price": Decimal("500")},
        ], paid_now="1000")
        payment = Payment.objects.get(sale=walkin)
        with self.assertRaises(ValidationError):
            update_payment(
                Payment.objects.get(pk=payment.pk), self.admin,
                date(2026, 10, 10), Decimal("100"), "cash", "",
                "trying to change it", payment.version)
        self.assertEqual(
            Payment.objects.get(pk=payment.pk).amount, Decimal("1000"))

    def test_credit_sale_linked_payment_amount_editable(self):
        sale = make_sale(self.admin, date(2026, 10, 10), self.customer, [
            {"product": self.p1, "quantity": 2, "unit_price": Decimal("500")},
        ], paid_now="200")
        payment = Payment.objects.get(sale=sale)
        updated = update_payment(
            Payment.objects.get(pk=payment.pk), self.admin,
            date(2026, 10, 10), Decimal("500"), "cash", "",
            "corrected amount", payment.version)
        self.assertEqual(updated.amount, Decimal("500"))

    def test_payment_customer_cannot_change_via_edit_view(self):
        sale = make_sale(self.admin, date(2026, 10, 10), self.customer, [
            {"product": self.p1, "quantity": 2, "unit_price": Decimal("500")},
        ], paid_now="200")
        payment = Payment.objects.get(sale=sale)
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("sales:payment_edit", args=[payment.pk]), {
                "customer": self.other.pk, "date": "2026-10-10",
                "amount": "200", "method": "cash", "reference": "",
                "reason": "trying to move it", "version": payment.version,
            })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            Payment.objects.get(pk=payment.pk).customer_id,
            self.customer.pk)

    def test_sale_date_edit_moves_linked_payments(self):
        sale = make_sale(self.admin, date(2026, 10, 10), self.customer, [
            {"product": self.p1, "quantity": 2, "unit_price": Decimal("500")},
        ], paid_now="200")
        version = Sale.objects.get(pk=sale.pk).version
        update_sale(
            Sale.objects.get(pk=sale.pk), self.admin, date(2026, 10, 12),
            self.customer, Decimal("0"),
            [{"product": self.p1, "quantity": 2, "unit_price": Decimal("500")}],
            "", "date was wrong", version)
        self.assertEqual(
            Payment.objects.get(sale=sale).date, date(2026, 10, 12))


class MoneyPrecisionTests(TestCase):
    """A8: more than 2 decimals is a form/service error, never a 500."""

    def setUp(self):
        self.admin = make_admin()
        self.p1 = make_product()
        self.customer = make_customer()

    def test_paid_now_precision_rejected(self):
        with self.assertRaises(ValidationError):
            make_sale(self.admin, date(2026, 10, 10), self.customer, [
                {"product": self.p1, "quantity": 2,
                 "unit_price": Decimal("500")},
            ], paid_now="0.001")
        self.assertEqual(Sale.objects.count(), 0)
        form = SaleForm(data={
            "date": "2026-10-10", "customer": self.customer.pk,
            "discount": "0", "notes": "", "paid_now": "0.001",
            "paid_method": "cash",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("paid_now", form.errors)

    def test_unit_price_precision_rejected_by_formset(self):
        from sales.forms import SaleItemFormSet
        formset = SaleItemFormSet(data={
            "items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0", "items-MAX_NUM_FORMS": "1000",
            "items-0-product": self.p1.pk, "items-0-quantity": "2",
            "items-0-unit_price": "0.005", "items-0-id": "",
        }, instance=Sale())
        self.assertFalse(formset.is_valid())
