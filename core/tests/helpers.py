"""Shared test factories for the Ice Factory test suite."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model

from customers.models import Customer
from employees.models import Employee
from expenses.models import ExpenseCategory
from sales.models import Product
from sales.services import create_payment, create_sale


def make_admin(username="admin", password="TestPassword123"):
    User = get_user_model()
    user = User.objects.create_user(username=username, password=password)
    user.is_superuser = True
    user.is_staff = True
    user.save()
    return user


def make_user(username="plain", password="TestPassword123"):
    """A logged-in user with NO permissions (not staff, not superuser)."""
    User = get_user_model()
    return User.objects.create_user(username=username, password=password)


def make_product(name="Full Block", price="500"):
    return Product.objects.create(
        name=name, default_price=Decimal(price),
        created_by=None, updated_by=None,
    )


def make_customer(name="Ahmed Store", phone="0300-1111111", opening="0"):
    return Customer.objects.create(
        name=name, phone=phone, opening_balance=Decimal(opening),
        created_by=None, updated_by=None,
    )


def make_sale(user, sale_date, customer, items, paid_now="0", discount="0",
              method="cash"):
    return create_sale(
        user, sale_date, customer, Decimal(discount), items,
        Decimal(paid_now), method,
    )


def make_payment(user, customer, pay_date, amount, method="cash"):
    return create_payment(user, customer, pay_date, Decimal(amount), method)


def make_employee(name="Ali Worker", salary="30000", joined=date(2025, 1, 1),
                  left=None):
    return Employee.objects.create(
        name=name, monthly_salary=Decimal(salary), joining_date=joined,
        leaving_date=left, created_by=None, updated_by=None,
    )


def salaries_category():
    return ExpenseCategory.objects.get(name="Salaries")
