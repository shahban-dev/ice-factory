from django.contrib import admin

from core.admin import NoDeleteAdmin
from customers.models import Customer


@admin.register(Customer)
class CustomerAdmin(NoDeleteAdmin):
    list_display = ["name", "phone", "is_active"]
