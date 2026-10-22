"""Shared base models for every business table.

Two bases exist on purpose:

- ``BaseModel`` — full audit + soft delete. Used by Customer, Sale,
  Payment, Expense, Employee and Payroll.
- ``TimestampedModel`` — audit + history but NO soft delete. Used by
  Product, ExpenseCategory and SaleItem (they are deactivated or replaced,
  never soft-deleted) and by Settings (a singleton row).

History comes from django-simple-history. The logged-in user is recorded by
``HistoryRequestMiddleware``; a change reason can be attached per save via
``obj._change_reason = "..."`` (see services.soft_delete_objects).
"""

import uuid

from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords

from .managers import SoftDeleteManager


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(class)s_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(class)s_updated",
    )
    history = HistoricalRecords(inherit=True)

    class Meta:
        abstract = True


class BaseModel(TimestampedModel):
    """Adds soft delete, a delete batch and optimistic-concurrency versioning."""

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(class)s_deleted",
    )
    # When deleting a parent also deletes children, they share one UUID so
    # restore brings back exactly those children.
    delete_batch = models.UUIDField(null=True, blank=True, db_index=True)
    # Optimistic concurrency: every edit form carries the version it was
    # loaded with. On save, inside a transaction with select_for_update, a
    # mismatch refuses the save (see services.check_version).
    version = models.PositiveIntegerField(default=0)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        # Version starts at 0 on creation and rises by 1 on every update.
        if self.pk is not None:
            self.version += 1
        super().save(*args, **kwargs)


class Settings(TimestampedModel):
    """Single-row factory settings. The logo is a static file in the repo,
    never an upload, so it is not a field here."""

    factory_name = models.CharField(max_length=200, default="Ice Factory")
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    invoice_prefix = models.CharField(max_length=10, default="INV")
    tax_registration_line = models.CharField(max_length=200, blank=True)
    invoice_footer_note = models.TextField(blank=True)

    class Meta:
        verbose_name = "Factory settings"
        verbose_name_plural = "Factory settings"

    def __str__(self):
        return self.factory_name

    def save(self, *args, **kwargs):
        # Singleton: this row always has pk 1.
        self.pk = 1
        super().save(*args, **kwargs)


def get_settings():
    """Return the singleton settings row, creating it on first use."""
    obj, _ = Settings.objects.get_or_create(
        pk=1, defaults={"factory_name": "Ice Factory"}
    )
    return obj


class InvoiceCounter(models.Model):
    """One counter row per year. Invoice numbers are generated inside the
    saving transaction from this row locked with select_for_update — never
    from max()+1, so two sales saved at the same moment cannot collide."""

    year = models.PositiveIntegerField(unique=True)
    last_number = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.year}: {self.last_number}"


class BackupLog(models.Model):
    """One row per backup attempt (scheduled or manual download). The
    settings page shows the last successful one."""

    KIND_SCHEDULED = "scheduled"
    KIND_MANUAL = "manual"
    KIND_CHOICES = [
        (KIND_SCHEDULED, "Scheduled"),
        (KIND_MANUAL, "Manual download"),
    ]
    STATUS_SUCCESS = "success"
    STATUS_FAILURE = "failure"
    STATUS_CHOICES = [
        (STATUS_SUCCESS, "Success"),
        (STATUS_FAILURE, "Failure"),
    ]

    created_at = models.DateTimeField(auto_now_add=True)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    filename = models.CharField(max_length=300, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    message = models.TextField(blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%d-%m-%Y %H:%M} — {self.kind} — {self.status}"
