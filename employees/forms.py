"""Employee and payroll forms."""

from django import forms
from django.utils import timezone

from core.forms import BootstrapWidgetsMixin, VersionedFormMixin
from customers.models import normalize_phone
from employees.models import Employee, Payroll, normalize_cnic
from employees.services import compute_net


class EmployeeForm(VersionedFormMixin, forms.ModelForm):
    reason = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Why are you changing this?"}),
        help_text="Required when editing.",
    )

    class Meta:
        model = Employee
        fields = ["name", "phone", "cnic", "role", "joining_date",
                  "leaving_date", "monthly_salary", "is_active", "notes"]
        widgets = {
            "name": forms.TextInput(attrs={"autofocus": True}),
            "phone": forms.TextInput(attrs={"placeholder": "0300-1234567", "inputmode": "tel"}),
            "cnic": forms.TextInput(attrs={"placeholder": "12345-1234567-1", "inputmode": "numeric"}),
            "joining_date": forms.DateInput(attrs={"type": "date"}),
            "leaving_date": forms.DateInput(attrs={"type": "date"}),
            "monthly_salary": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01"}),
        }

    def __init__(self, *args, require_reason=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reason"].required = require_reason
        if not require_reason:
            del self.fields["reason"]

    def clean_phone(self):
        return normalize_phone(self.cleaned_data.get("phone") or "")

    def clean_cnic(self):
        cnic = normalize_cnic(self.cleaned_data.get("cnic") or "")
        if cnic:
            is_active = self.cleaned_data.get("is_active", True)
            qs = Employee.objects.filter(
                cnic=cnic, is_active=True, is_deleted=False
            )
            if self.instance is not None and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if is_active and qs.exists():
                raise forms.ValidationError(
                    "Another active employee already has this CNIC."
                )
        return cnic

    def clean(self):
        cleaned = super().clean()
        leaving = cleaned.get("leaving_date")
        joining = cleaned.get("joining_date")
        if leaving and joining and leaving < joining:
            self.add_error("leaving_date", "Leaving date cannot be before joining date.")
        return cleaned


class PayrollGenerateForm(BootstrapWidgetsMixin, forms.Form):
    year = forms.IntegerField(min_value=2000, max_value=2100)
    month = forms.IntegerField(min_value=1, max_value=12)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        self.fields["year"].initial = today.year
        self.fields["month"].initial = today.month

    def clean(self):
        cleaned = super().clean()
        year = cleaned.get("year")
        month = cleaned.get("month")
        if year and month:
            today = timezone.localdate()
            if (year, month) > (today.year, today.month):
                raise forms.ValidationError(
                    "Payroll cannot be generated for a future month."
                )
        return cleaned


class PayrollEditForm(VersionedFormMixin, forms.ModelForm):
    reason = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={"placeholder": "Why are you changing this?"}),
    )

    class Meta:
        model = Payroll
        fields = ["bonus", "deductions", "deduction_note"]
        widgets = {
            "bonus": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01"}),
            "deductions": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01"}),
        }

    def clean(self):
        cleaned = super().clean()
        bonus = cleaned.get("bonus")
        deductions = cleaned.get("deductions")
        if bonus is not None and deductions is not None and self.instance.pk:
            try:
                compute_net(self.instance.base_salary, bonus, deductions)
            except forms.ValidationError as exc:
                self.add_error("deductions", exc)
        return cleaned


class MarkPaidForm(BootstrapWidgetsMixin, forms.Form):
    paid_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["paid_date"].initial = timezone.localdate()

    def clean_paid_date(self):
        value = self.cleaned_data.get("paid_date")
        if value and value > timezone.localdate():
            raise forms.ValidationError("Paid date cannot be in the future.")
        return value
