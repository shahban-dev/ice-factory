"""Seed the default expense categories. Idempotent: safe to run twice."""

from django.db import migrations

DEFAULT_CATEGORIES = [
    ("Electricity", False),
    ("Diesel and fuel", False),
    ("Salaries", True),
    ("Maintenance", False),
    ("Packaging", False),
    ("Rent", False),
    ("Transport", False),
    ("Other", False),
]


def seed_categories(apps, schema_editor):
    ExpenseCategory = apps.get_model("expenses", "ExpenseCategory")
    for name, is_system in DEFAULT_CATEGORIES:
        ExpenseCategory.objects.get_or_create(
            name=name, defaults={"is_system": is_system}
        )


def unseed_categories(apps, schema_editor):
    ExpenseCategory = apps.get_model("expenses", "ExpenseCategory")
    ExpenseCategory.objects.filter(
        name__in=[name for name, _ in DEFAULT_CATEGORIES],
        expenses__isnull=True,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("expenses", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_categories, unseed_categories),
    ]
