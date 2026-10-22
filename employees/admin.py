from django.contrib import admin

from core.admin import NoDeleteAdmin
from employees.models import Employee, Loan, Payroll


@admin.register(Employee)
class EmployeeAdmin(NoDeleteAdmin):
    list_display = ["name", "role", "is_active"]


@admin.register(Payroll)
class PayrollAdmin(NoDeleteAdmin):
    list_display = ["employee", "year", "month", "status"]


@admin.register(Loan)
class LoanAdmin(NoDeleteAdmin):
    list_display = ["employee", "date", "amount", "status"]
