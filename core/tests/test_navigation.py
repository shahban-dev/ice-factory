"""Navigation tests: the navbar must highlight exactly the section the
user is on, and every section page must offer a back button.

The laptop navbar used to wrap because the menu was too long for the
screen; the back buttons were missing everywhere except delete pages
and the invoice. These tests pin both behaviours."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from customers.models import Customer

# (url name, nav label shown as active)
ACTIVE_CASES = [
    ("home", "Dashboard"),
    ("customers:list", "Customers"),
    ("sales:sale_list", "Sales"),
    ("sales:product_list", "Products"),
    ("sales:payment_list", "Payments"),
    ("expenses:expense_list", "Expenses"),
    ("employees:list", "Employees"),
    ("employees:payroll_list", "Payroll"),
    ("reports:index", "Reports"),
]

# (url name, back button label)
BACK_CASES = [
    ("customers:list", "\u2190 Dashboard"),
    ("sales:sale_list", "\u2190 Dashboard"),
    ("sales:product_list", "\u2190 Dashboard"),
    ("sales:payment_list", "\u2190 Dashboard"),
    ("expenses:expense_list", "\u2190 Dashboard"),
    ("employees:list", "\u2190 Dashboard"),
    ("employees:payroll_list", "\u2190 Dashboard"),
    ("reports:index", "\u2190 Dashboard"),
    ("reports:settings", "\u2190 Dashboard"),
    ("sales:sale_create", "\u2190 Back to sales"),
    ("expenses:category_list", "\u2190 Back to expenses"),
    ("reports:monthly", "\u2190 Back to reports"),
    ("reports:dues", "\u2190 Back to reports"),
    ("reports:recycle", "\u2190 Back to reports"),
    ("reports:audit", "\u2190 Back to reports"),
]


class NavigationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            "admin", "admin@example.com", "TestPassword123")
        self.client.force_login(self.admin)

    def test_navbar_highlights_exactly_one_section(self):
        for name, label in ACTIVE_CASES:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(
                    response,
                    f'<a class="nav-link active" href="{reverse(name)}" '
                    f'aria-current="page">{label}</a>',
                )
                self.assertContains(response, 'aria-current="page"', count=1)

    def test_more_menu_highlights_settings(self):
        # Settings lives under More, so both the item and the More
        # toggle must show the user where they are.
        response = self.client.get(reverse("reports:settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'<a class="dropdown-item active" href="{reverse("reports:settings")}" '
            'aria-current="page">Settings</a>',
        )
        self.assertContains(
            response,
            '<a class="nav-link dropdown-toggle active" href="#" role="button" '
            'data-bs-toggle="dropdown" aria-expanded="false">More</a>',
        )
        self.assertContains(response, 'aria-current="page"', count=1)

    def test_every_section_page_has_a_back_button(self):
        for name, label in BACK_CASES:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, label)

    def test_detail_pages_have_back_buttons(self):
        customer = Customer.objects.create(name="Test Store")
        response = self.client.get(
            reverse("customers:detail", args=[customer.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "\u2190 Back to customers")
        response = self.client.get(reverse("search") + "?q=Test")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "\u2190 Dashboard")
