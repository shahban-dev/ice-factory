from django.contrib import admin

from core.admin import NoDeleteAdmin
from sales.models import Payment, Product, Sale, SaleItem


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 0
    can_delete = False


@admin.register(Sale)
class SaleAdmin(NoDeleteAdmin):
    list_display = ["invoice_number", "date", "customer", "discount"]
    inlines = [SaleItemInline]


@admin.register(SaleItem)
class SaleItemAdmin(NoDeleteAdmin):
    list_display = ["sale", "product", "quantity", "unit_price"]


@admin.register(Product)
class ProductAdmin(NoDeleteAdmin):
    list_display = ["name", "is_active"]


@admin.register(Payment)
class PaymentAdmin(NoDeleteAdmin):
    list_display = ["date", "customer", "amount", "method"]
