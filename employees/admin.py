from django.contrib import admin

from employees.models import Employee, Payroll

admin.site.register(Employee)
admin.site.register(Payroll)
