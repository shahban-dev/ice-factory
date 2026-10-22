"""Seed a demo dataset: sample customers, products and employees plus
one full month of sales, payments, expenses and payroll — and a file of
hand-calculated expected report totals for that month, so the demo can
be checked against the reports by hand.

Safety: the command REFUSES to run unless DEBUG is on, or --force is
given together with typing "SEED DEMO" at the prompt. It also refuses
if demo data already exists (customer names starting with "Demo ").

The demo month is the previous calendar month, so every date is safely
in the past. Expected totals are computed here from the literal line
items — deliberately NOT through reports.services, so the file is an
independent check on the reports, not a copy of them.
"""

from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from customers.models import Customer
from employees.models import Employee
from employees.services import generate_payroll, mark_paid
from expenses.models import Expense, ExpenseCategory
from sales.models import Product
from sales.services import create_payment, create_sale


def previous_month(today):
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


class Command(BaseCommand):
    help = "Seed demo data (previous calendar month) + expected totals file."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true",
                            help="Allow seeding with DEBUG off (asks for typed confirmation).")
        parser.add_argument("--output", default="seed_demo_expected_totals.txt",
                            help="Where to write the expected totals file.")

    def handle(self, *args, **options):
        from django.utils import timezone

        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "Refusing to seed demo data with DEBUG off. Re-run with "
                "--force and type SEED DEMO at the prompt, or enable DEBUG."
            )
        if options["force"] and not settings.DEBUG:
            typed = input('Type "SEED DEMO" to confirm seeding demo data: ')
            if typed.strip() != "SEED DEMO":
                raise CommandError("Confirmation did not match. Aborting.")
        if Customer.objects.filter(name__startswith="Demo ").exists():
            raise CommandError(
                "Demo data already exists (customers starting with 'Demo '). "
                "Delete them first if you want a fresh demo."
            )

        user = None  # created_by/updated_by stay empty for demo rows
        today = timezone.localdate()
        year, month = previous_month(today)
        day = lambda d: date(year, month, d)  # noqa: E731

        products = {
            "Full Block": Product.objects.create(
                name="Demo Full Block", default_price=Decimal("500")),
            "Half Block": Product.objects.create(
                name="Demo Half Block", default_price=Decimal("300")),
            "Quarter Block": Product.objects.create(
                name="Demo Quarter Block", default_price=Decimal("150")),
        }
        customers = {
            "General": Customer.objects.create(
                name="Demo General Store", phone="0300-1000001",
                opening_balance=Decimal("5000")),
            "Corner": Customer.objects.create(
                name="Demo Corner Shop", phone="0300-1000002",
                opening_balance=Decimal("0")),
            "Hotel": Customer.objects.create(
                name="Demo Hotel", phone="0300-1000003",
                opening_balance=Decimal("12000")),
            "Canteen": Customer.objects.create(
                name="Demo Canteen", phone="0300-1000004",
                opening_balance=Decimal("-2000")),
        }
        employees = {
            "Ahmed": Employee.objects.create(
                name="Demo Ahmed", monthly_salary=Decimal("30000"),
                joining_date=date(2025, 1, 1)),
            "Bilal": Employee.objects.create(
                name="Demo Bilal", monthly_salary=Decimal("25000"),
                joining_date=date(2025, 6, 15)),
            "Fatima": Employee.objects.create(
                name="Demo Fatima", monthly_salary=Decimal("20000"),
                joining_date=date(2025, 3, 1)),
        }

        # Sales: (customer, day, [(product, qty, price)], paid_now)
        sales = [
            ("General", 3, [("Full Block", 10, "500")], "2000"),
            ("Corner", 7, [("Half Block", 20, "300")], "0"),
            ("Hotel", 11, [("Full Block", 30, "500")], "15000"),
            (None, 15, [("Full Block", 5, "500")], "2500"),
            ("Canteen", 19, [("Half Block", 8, "300")], "400"),
        ]
        for key, d, items, paid in sales:
            create_sale(
                user, day(d),
                customers[key] if key else None,
                Decimal("0"),
                [{"product": products[name], "quantity": qty,
                  "unit_price": Decimal(price)} for name, qty, price in items],
                Decimal(paid), "cash",
            )
        # General payments (not tied to a sale).
        create_payment(user, customers["General"], day(5), Decimal("1000"), "cash")
        create_payment(user, customers["Canteen"], day(21), Decimal("1000"), "cash")

        # Expenses.
        for name, amount, d in [
            ("Electricity", "15000", 9),
            ("Diesel and fuel", "8000", 14),
            ("Rent", "20000", 1),
        ]:
            Expense.objects.create(
                date=day(d), category=ExpenseCategory.objects.get(name=name),
                amount=Decimal(amount), method="cash")

        # Payroll: generate for all three, pay two of them.
        generate_payroll(user, year, month)
        from employees.models import Payroll
        for name, pay_day in [("Ahmed", 25), ("Bilal", 26)]:
            row = Payroll.objects.get(
                employee=employees[name], year=year, month=month)
            mark_paid(row, user, day(pay_day))
        # Fatima stays a draft (unpaid).

        # --- Expected totals, computed from the literals above. ---
        sale_totals = [Decimal("5000"), Decimal("6000"), Decimal("15000"),
                       Decimal("2500"), Decimal("2400")]
        paid_now = [Decimal("2000"), Decimal("0"), Decimal("15000"),
                    Decimal("2500"), Decimal("400")]
        general_payments = [Decimal("1000"), Decimal("1000")]
        billed = sum(sale_totals)
        collected = sum(paid_now) + sum(general_payments)
        manual_expenses = Decimal("15000") + Decimal("8000") + Decimal("20000")
        salaries_paid = Decimal("30000") + Decimal("25000")
        expenses = manual_expenses + salaries_paid
        balances = {
            "Demo General Store": Decimal("5000") + Decimal("5000")
                - Decimal("2000") - Decimal("1000"),
            "Demo Corner Shop": Decimal("0") + Decimal("6000"),
            "Demo Hotel": Decimal("12000") + Decimal("15000") - Decimal("15000"),
            "Demo Canteen": Decimal("-2000") + Decimal("2400")
                - Decimal("400") - Decimal("1000"),
        }
        outstanding = sum(b for b in balances.values() if b > 0)
        blocks = {"Demo Full Block": 10 + 30 + 5, "Demo Half Block": 20 + 8}

        lines = [
            f"Demo data for {year}-{month:02d} (previous calendar month).",
            "",
            "Monthly report — expected values (check against Reports > Monthly report):",
            f"  Billed: Rs {billed}",
            f"  Collected: Rs {collected}",
            f"  Expenses: Rs {expenses}",
            f"  Salaries paid: Rs {salaries_paid}",
            f"  Sales profit (billed - expenses): Rs {billed - expenses}",
            f"  Cash profit (collected - expenses): Rs {collected - expenses}",
            f"  Outstanding at month end: Rs {outstanding}",
            "",
            "Blocks sold per product:",
        ]
        lines += [f"  {name}: {qty}" for name, qty in blocks.items()]
        lines += ["", "Customer balances at month end:"]
        lines += [f"  {name}: Rs {bal}" for name, bal in balances.items()]
        lines += [
            "",
            "Top customers by billed: Demo Hotel Rs 15000, Demo Corner Shop "
            "Rs 6000, Demo General Store Rs 5000, Demo Canteen Rs 2400.",
            "Dues report: Demo General Store Rs 7000, Demo Corner Shop "
            "Rs 6000, Demo Hotel Rs 12000 (Demo Canteen has Rs 1000 credit "
            "and does not appear).",
        ]
        with open(options["output"], "w") as fh:
            fh.write("\n".join(lines) + "\n")
        self.stdout.write(self.style.SUCCESS(
            f"Demo data seeded for {year}-{month:02d}. Expected totals "
            f"written to {options['output']}."
        ))
