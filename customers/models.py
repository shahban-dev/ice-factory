"""Customer model. Phone numbers are normalized to 03XX-XXXXXXX on save;
a duplicate phone is a warning with a link, never a hard block."""

import re

from django.core.exceptions import ValidationError
from django.db import models

from core.models import BaseModel

PHONE_RE = re.compile(r"^03\d{2}-\d{7}$")


def normalize_phone(raw):
    """Normalize Pakistani phone formats to 03XX-XXXXXXX.

    Accepts 03XX-XXXXXXX, 03XXXXXXXXX, +92 3XX XXXXXXX, +923XXXXXXXXX,
    with spaces or dashes anywhere. Returns the normalized form, or the
    stripped input unchanged when it cannot be understood.
    """
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("92") and len(digits) == 12:
        digits = "0" + digits[2:]
    if len(digits) == 11 and digits.startswith("03"):
        return f"{digits[:4]}-{digits[4:]}"
    return raw.strip()


def validate_phone(value):
    if value and not PHONE_RE.match(value):
        raise ValidationError(
            "Enter a valid Pakistani mobile number, e.g. 0300-1234567."
        )


class Customer(BaseModel):
    name = models.CharField(max_length=200)
    phone = models.CharField(
        max_length=20, blank=True, validators=[validate_phone],
        help_text="Optional. Stored as 03XX-XXXXXXX.",
    )
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    # May be negative: a negative opening balance is advance credit.
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["phone"]),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        self.phone = normalize_phone(self.phone)
        if self.phone:
            validate_phone(self.phone)

    def save(self, *args, **kwargs):
        self.phone = normalize_phone(self.phone)
        super().save(*args, **kwargs)

    def duplicate_phone_customers(self):
        """Other active customers sharing this phone (for the warning)."""
        if not self.phone:
            return Customer.objects.none()
        qs = Customer.objects.filter(phone=self.phone, is_active=True)
        if self.pk:
            qs = qs.exclude(pk=self.pk)
        return qs
