from django.contrib import admin

from sales.models import Payment, Product, Sale, SaleItem


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 0


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ["invoice_number", "date", "customer", "discount"]
    inlines = [SaleItemInline]


admin.site.register(Product)
admin.site.register(Payment)
