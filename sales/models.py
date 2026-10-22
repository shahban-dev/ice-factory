"""Products, sales, sale items and payments.

Subtotal, total and invoice status are COMPUTED, never stored:
- subtotal = sum of line totals
- total = subtotal - discount
- status comes from the allocation function (sales/services.py)

Invoice numbers come from InvoiceCounter, one row per year, locked with
select_for_update inside the saving transaction.
"""

from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from core.models import BaseModel, TimestampedModel


class Product(TimestampedModel):
    """An ice type. No soft delete: products are deactivated, never deleted."""

    name = models.CharField(max_length=200)
    size = models.CharField(
        max_length=200, blank=True,
        help_text="Size or description, e.g. 'Full block 25 kg'.",
    )
    default_price = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                condition=models.Q(is_active=True),
                name="product_name_unique_active",
            ),
            models.CheckConstraint(
                check=models.Q(default_price__gte=0),
                name="product_price_non_negative",
            ),
        ]

    def __str__(self):
        return self.name


class Sale(BaseModel):
    invoice_number = models.CharField(max_length=20, unique=True)
    date = models.DateField()
    # None means a walk-in cash sale.
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="sales",
    )
    discount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        validators=[MinValueValidator(0)],
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [
            models.Index(fields=["customer", "date"]),
            models.Index(fields=["date"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(discount__gte=0),
                name="sale_discount_non_negative",
            ),
        ]

    def __str__(self):
        return self.invoice_number

    @property
    def subtotal(self):
        return sum(
            (item.line_total for item in self.items.all()),
            start=Decimal("0"),
        )

    @property
    def total(self):
        return self.subtotal - self.discount

    @property
    def is_walk_in(self):
        return self.customer_id is None

    @property
    def paid_with_sale(self):
        """Money handed over on the sale form (paid-now payments)."""
        return sum(
            (p.amount for p in self.payments.all()),
            start=Decimal("0"),
        )


class SaleItem(TimestampedModel):
    """No soft delete: rows are replaced inside the sale-edit transaction
    and tracked by history."""

    sale = models.ForeignKey(
        Sale, on_delete=models.PROTECT, related_name="items"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="sale_items"
    )
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    # Snapshot: later price changes never change old bills.
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(0)],
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(quantity__gt=0),
                name="saleitem_quantity_positive",
            ),
            models.CheckConstraint(
                check=models.Q(unit_price__gte=0),
                name="saleitem_price_non_negative",
            ),
        ]

    def __str__(self):
        return f"{self.sale.invoice_number} — {self.product.name} × {self.quantity}"

    @property
    def line_total(self):
        return self.quantity * self.unit_price


class Payment(BaseModel):
    METHOD_CASH = "cash"
    METHOD_BANK = "bank"
    METHOD_OTHER = "other"
    METHOD_CHOICES = [
        (METHOD_CASH, "Cash"),
        (METHOD_BANK, "Bank transfer"),
        (METHOD_OTHER, "Other"),
    ]

    # Empty only for a walk-in sale's payment.
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="payments",
    )
    # Set only when the payment was entered on the sale form.
    sale = models.ForeignKey(
        Sale,
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="payments",
    )
    date = models.DateField()
    amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    method = models.CharField(
        max_length=10, choices=METHOD_CHOICES, default=METHOD_CASH
    )
    reference = models.CharField(
        max_length=200, blank=True,
        help_text="Reference note, e.g. receipt number.",
    )

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [
            models.Index(fields=["customer", "date"]),
            models.Index(fields=["date"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount__gt=0),
                name="payment_amount_positive",
            ),
        ]

    def __str__(self):
        who = self.customer.name if self.customer else "Walk-in"
        return f"{who} — {self.amount} on {self.date:%d-%m-%Y}"
