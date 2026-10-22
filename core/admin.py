from django.contrib import admin

from core.models import InvoiceCounter, Settings

admin.site.register(Settings)
admin.site.register(InvoiceCounter)
