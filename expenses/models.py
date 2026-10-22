"""Expense categories and expenses.

Categories are never deleted (only deactivated). The Salaries category is
a system category: it cannot be deactivated and cannot be chosen manually
on expense forms — salary expenses are created only by payroll.
"""

from django.core.validators import MinValueValidator
from django.db import models

from core.models import BaseModel, TimestampedModel

DEFAULT_CATEGORIES = [
    ("Electricity", False),
    ("Diesel and fuel", False),
    ("Salaries", True),
    ("Maintenance", False),
    ("Packaging", False),
    ("Rent", False),
    ("Transport", False),
    ("Other", False),
]


class ExpenseCategory(TimestampedModel):
    """No soft delete: categories are deactivated, never deleted."""

    name = models.CharField(max_length=200, unique=True)
    is_active = models.BooleanField(default=True)
    is_system = models.BooleanField(
        default=False,
        help_text="System categories cannot be deactivated or chosen manually.",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Expense(BaseModel):
    METHOD_CASH = "cash"
    METHOD_BANK = "bank"
    METHOD_OTHER = "other"
    METHOD_CHOICES = [
        (METHOD_CASH, "Cash"),
        (METHOD_BANK, "Bank transfer"),
        (METHOD_OTHER, "Other"),
    ]

    date = models.DateField()
    category = models.ForeignKey(
        ExpenseCategory, on_delete=models.PROTECT, related_name="expenses"
    )
    amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    description = models.TextField(blank=True)
    method = models.CharField(
        max_length=10, choices=METHOD_CHOICES, default=METHOD_CASH
    )

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [
            models.Index(fields=["date", "category"]),
            models.Index(fields=["date"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount__gt=0),
                name="expense_amount_positive",
            ),
        ]

    def __str__(self):
        return f"{self.date:%d-%m-%Y} — {self.category.name} — {self.amount}"

    @property
    def is_payroll_linked(self):
        """True when a non-deleted payroll row points at this expense.
        (Reverse OneToOne: the accessor is a single object, not a manager;
        missing relations raise RelatedObjectDoesNotExist, a subclass of
        AttributeError, so getattr's default applies.)"""
        row = getattr(self, "payroll_rows", None)
        return row is not None and not row.is_deleted
