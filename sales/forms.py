"""Product, sale and payment forms.

The sale form is built for speed on a phone: customer search-as-you-type
(HTMX), default price prefilled, add-row button, and Paid in full /
Paid nothing / Custom amount buttons. Totals are recomputed on the server;
anything the browser shows is display only.
"""

from django import forms
from django.forms import inlineformset_factory
from django.utils import timezone

from core.forms import BootstrapWidgetsMixin, VersionedFormMixin
from customers.models import Customer
from sales.models import Payment, Product, Sale, SaleItem


def _not_future(value, label):
    if value and value > timezone.localdate():
        raise forms.ValidationError(f"{label} cannot be in the future.")
    return value


class ProductForm(BootstrapWidgetsMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "size", "default_price", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"autofocus": True}),
            "default_price": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01"}),
        }


class SaleForm(VersionedFormMixin, forms.ModelForm):
    reason = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Why are you changing this?"}),
        help_text="Required when editing.",
    )
    # Money received with this sale. 0 means "Paid nothing".
    paid_now = forms.DecimalField(
        required=False, min_value=0, initial=0,
        widget=forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01"}),
    )
    paid_method = forms.ChoiceField(
        choices=Payment.METHOD_CHOICES, initial=Payment.METHOD_CASH
    )

    class Meta:
        model = Sale
        fields = ["date", "customer", "discount", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "customer": forms.HiddenInput(),
            "discount": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01"}),
        }

    def __init__(self, *args, require_reason=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reason"].required = require_reason
        if not require_reason:
            del self.fields["reason"]
        # Only active customers appear in pickers; keep the current one
        # selectable when editing an old sale.
        qs = Customer.objects.filter(is_active=True)
        if self.instance is not None and self.instance.pk and self.instance.customer_id:
            qs = qs | Customer.objects.filter(pk=self.instance.customer_id)
        self.fields["customer"].queryset = qs
        self.fields["customer"].required = False

    def clean_date(self):
        return _not_future(self.cleaned_data.get("date"), "Sale date")


SaleItemFormSet = inlineformset_factory(
    Sale, SaleItem,
    fields=["product", "quantity", "unit_price"],
    extra=1, can_delete=True,
    widgets={
        "product": forms.Select(attrs={"class": "form-select"}),
        "quantity": forms.NumberInput(attrs={"inputmode": "numeric", "min": "1", "class": "form-control"}),
        "unit_price": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01", "class": "form-control"}),
    },
)


class PaymentForm(VersionedFormMixin, forms.ModelForm):
    reason = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Why are you changing this?"}),
        help_text="Required when editing.",
    )

    class Meta:
        model = Payment
        fields = ["customer", "date", "amount", "method", "reference"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "amount": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01"}),
        }

    def __init__(self, *args, require_reason=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reason"].required = require_reason
        if not require_reason:
            del self.fields["reason"]
        qs = Customer.objects.filter(is_active=True)
        if self.instance is not None and self.instance.pk and self.instance.customer_id:
            qs = qs | Customer.objects.filter(pk=self.instance.customer_id)
        self.fields["customer"].queryset = qs

    def clean_date(self):
        return _not_future(self.cleaned_data.get("date"), "Payment date")

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        if amount is not None and amount <= 0:
            raise forms.ValidationError("Amount must be more than zero.")
        return amount
