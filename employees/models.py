"""Employees and monthly payroll.

Payroll rows are snapshots: base_salary is fixed at generation time from
the employee's monthly salary and proration, so later salary changes never
rewrite past rows. A salary counts as an expense only when the row is
marked PAID, on the paid date, for the amount actually paid (net_salary),
via the linked Expense — payroll rows themselves are never summed into
profit, so nothing is counted twice.
"""

import re

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from core.models import BaseModel
from customers.models import normalize_phone, validate_phone

CNIC_RE = re.compile(r"^\d{5}-\d{7}-\d{1}$")


def normalize_cnic(raw):
    """Accept 1234512345671 or 12345-1234567-1; store the dashed form."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 13:
        return f"{digits[:5]}-{digits[5:12]}-{digits[12:]}"
    return raw.strip() or None


def validate_cnic(value):
    if value and not CNIC_RE.match(value):
        raise ValidationError(
            "Enter a valid CNIC, e.g. 12345-1234567-1."
        )


def mask_cnic(value):
    """Masked for lists: 12345-*******-1. Shown fully only on the detail page."""
    if not value:
        return "—"
    if CNIC_RE.match(value):
        return f"{value[:5]}-*******-{value[-1:]}"
    return value


class Employee(BaseModel):
    ROLE_WORKER = "worker"
    ROLE_DRIVER = "driver"
    ROLE_OTHER = "other"
    ROLE_CHOICES = [
        (ROLE_WORKER, "Worker"),
        (ROLE_DRIVER, "Driver"),
        (ROLE_OTHER, "Other"),
    ]

    name = models.CharField(max_length=200)
    phone = models.CharField(
        max_length=20, blank=True, validators=[validate_phone],
        help_text="Optional. Stored as 03XX-XXXXXXX.",
    )
    # NULL (not "") when empty, so the partial unique constraint allows
    # many employees without a CNIC.
    cnic = models.CharField(
        max_length=15, null=True, blank=True, validators=[validate_cnic],
        help_text="Optional. Format 12345-1234567-1.",
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_WORKER)
    joining_date = models.DateField()
    leaving_date = models.DateField(null=True, blank=True)
    monthly_salary = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["cnic"],
                condition=models.Q(is_deleted=False, is_active=True),
                name="employee_cnic_unique_active",
            ),
            models.CheckConstraint(
                check=models.Q(monthly_salary__gte=0),
                name="employee_salary_non_negative",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        self.phone = normalize_phone(self.phone)
        if self.phone:
            validate_phone(self.phone)
        self.cnic = normalize_cnic(self.cnic)
        if self.cnic:
            validate_cnic(self.cnic)

    def save(self, *args, **kwargs):
        self.phone = normalize_phone(self.phone)
        self.cnic = normalize_cnic(self.cnic)
        super().save(*args, **kwargs)

    @property
    def masked_cnic(self):
        return mask_cnic(self.cnic)


class Payroll(BaseModel):
    STATUS_DRAFT = "draft"
    STATUS_PAID = "paid"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PAID, "Paid"),
    ]

    employee = models.ForeignKey(
        Employee, on_delete=models.PROTECT, related_name="payrolls"
    )
    year = models.PositiveIntegerField()
    month = models.PositiveIntegerField()
    # Snapshot after proration at generation time.
    base_salary = models.DecimalField(max_digits=12, decimal_places=2)
    # Snapshot of the proration itself, so the payslip always matches base.
    days_employed = models.PositiveIntegerField()
    bonus = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        validators=[MinValueValidator(0)],
    )
    deductions = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        validators=[MinValueValidator(0)],
    )
    deduction_note = models.TextField(blank=True)
    net_salary = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default=STATUS_DRAFT
    )
    paid_date = models.DateField(null=True, blank=True)
    linked_expense = models.OneToOneField(
        "expenses.Expense",
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="payroll_rows",
    )

    class Meta:
        ordering = ["-year", "-month", "employee__name"]
        indexes = [
            models.Index(fields=["year", "month"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "year", "month"],
                condition=models.Q(is_deleted=False),
                name="payroll_unique_employee_month",
            ),
            models.CheckConstraint(
                check=models.Q(month__gte=1, month__lte=12),
                name="payroll_month_range",
            ),
            models.CheckConstraint(
                check=models.Q(bonus__gte=0),
                name="payroll_bonus_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(deductions__gte=0),
                name="payroll_deductions_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(net_salary__gte=0),
                name="payroll_net_non_negative",
            ),
        ]

    def __str__(self):
        return f"{self.employee.name} — {self.month:02d}/{self.year}"
