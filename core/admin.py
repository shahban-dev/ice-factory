from django.contrib import admin

from core.models import InvoiceCounter, Settings


class NoDeleteAdmin(admin.ModelAdmin):
    """Business records are soft-deleted through the app, with an
    audit trail — the admin's hard delete would bypass both rules,
    so it is disabled for every business model."""

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Settings)
admin.site.register(InvoiceCounter)
