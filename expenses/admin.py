from django.contrib import admin

from expenses.models import Expense, ExpenseCategory

admin.site.register(ExpenseCategory)
admin.site.register(Expense)
