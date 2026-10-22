"""A payment must belong to a customer or to a sale.

Orphan payments (neither) could only exist through the old standalone
payment form, which saved the row and then crashed on the redirect,
leaving money counted as collected cash with no owner. Django CHECK
constraints cannot be conditional, so every orphan row is deleted here
before the constraint is added. This is pre-handover data only: the
simple-history rows for those payments survive (they live in their own
table), so the audit trail of what happened is not lost. If you need an
orphan's details, look at its history rows before migrating.
"""

from django.db import migrations, models


def delete_orphan_payments(apps, schema_editor):
    Payment = apps.get_model("sales", "Payment")
    Payment.objects.filter(
        customer__isnull=True, sale__isnull=True,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            delete_orphan_payments, migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="payment",
            constraint=models.CheckConstraint(
                check=(
                    models.Q(customer__isnull=False)
                    | models.Q(sale__isnull=False)
                ),
                name="payment_needs_customer_or_sale",
            ),
        ),
    ]
