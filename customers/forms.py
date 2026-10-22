"""Customer forms. Edit forms carry the record version and require a
reason, which is saved as the history change reason."""

from django import forms

from core.forms import VersionedFormMixin
from customers.models import Customer, normalize_phone


class CustomerForm(VersionedFormMixin, forms.ModelForm):
    reason = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Why are you changing this?"}),
        help_text="Required when editing.",
    )

    class Meta:
        model = Customer
        fields = ["name", "phone", "address", "notes", "opening_balance", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"autofocus": True}),
            "phone": forms.TextInput(attrs={"placeholder": "0300-1234567", "inputmode": "tel"}),
            "opening_balance": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01"}),
        }

    def __init__(self, *args, require_reason=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reason"].required = require_reason
        if not require_reason:
            del self.fields["reason"]

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data.get("phone") or "")
        return phone


class CustomerImportUploadForm(forms.Form):
    file = forms.FileField(
        help_text="Excel (.xlsx) or CSV (.csv), maximum 5 MB and 5,000 rows. "
                  "Columns: name, phone, address, opening_balance."
    )

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        name = (uploaded.name or "").lower()
        if not (name.endswith(".xlsx") or name.endswith(".csv")):
            raise forms.ValidationError("Only .xlsx and .csv files are accepted.")
        if uploaded.size > 5 * 1024 * 1024:
            raise forms.ValidationError("File is too large (maximum 5 MB).")
        return uploaded
