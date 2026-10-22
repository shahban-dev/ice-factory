from django.contrib import admin

from core.admin import NoDeleteAdmin
from expenses.models import Expense, ExpenseCategory


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(NoDeleteAdmin):
    list_display = ["name", "is_active"]


@admin.register(Expense)
class ExpenseAdmin(NoDeleteAdmin):
    list_display = ["date", "category", "amount"]
