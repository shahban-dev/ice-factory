"""Expense and category forms."""

from django import forms
from django.utils import timezone

from core.forms import BootstrapWidgetsMixin, VersionedFormMixin
from expenses.models import Expense, ExpenseCategory


class ExpenseCategoryForm(BootstrapWidgetsMixin, forms.ModelForm):
    class Meta:
        model = ExpenseCategory
        fields = ["name", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"autofocus": True}),
        }


class ExpenseForm(VersionedFormMixin, forms.ModelForm):
    reason = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Why are you changing this?"}),
        help_text="Required when editing.",
    )

    class Meta:
        model = Expense
        fields = ["date", "category", "amount", "description", "method"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "amount": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01"}),
        }

    def __init__(self, *args, require_reason=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reason"].required = require_reason
        if not require_reason:
            del self.fields["reason"]
        # The Salaries category is never chosen manually. Keep the current
        # category selectable when editing an old expense.
        qs = ExpenseCategory.objects.filter(is_active=True, is_system=False)
        if self.instance is not None and self.instance.pk and self.instance.category_id:
            qs = qs | ExpenseCategory.objects.filter(pk=self.instance.category_id)
        self.fields["category"].queryset = qs

    def clean_date(self):
        value = self.cleaned_data.get("date")
        if value and value > timezone.localdate():
            raise forms.ValidationError("Expense date cannot be in the future.")
        return value

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        if amount is not None and amount <= 0:
            raise forms.ValidationError("Amount must be more than zero.")
        return amount
