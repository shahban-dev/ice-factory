"""Employee and payroll forms."""

from decimal import Decimal

from django import forms
from django.db import models
from django.utils import timezone

from core.forms import BootstrapWidgetsMixin, VersionedFormMixin
from customers.models import normalize_phone
from employees.models import Employee, Loan, Payroll, normalize_cnic
from employees.services import compute_net, loan_remaining


class LoanForm(VersionedFormMixin, forms.ModelForm):
    reason = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Why are you changing this?"}),
        help_text="Required when editing.",
    )

    class Meta:
        model = Loan
        fields = ["date", "amount", "monthly_installment", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "amount": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01"}),
            "monthly_installment": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01"}),
        }

    def __init__(self, *args, require_reason=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reason"].required = require_reason
        if not require_reason:
            del self.fields["reason"]

    def clean_date(self):
        value = self.cleaned_data.get("date")
        if value and value > timezone.localdate():
            raise forms.ValidationError("Loan date cannot be in the future.")
        return value

    def clean(self):
        cleaned = super().clean()
        amount = cleaned.get("amount")
        installment = cleaned.get("monthly_installment")
        if amount is not None and amount <= 0:
            self.add_error("amount", "Loan amount must be more than zero.")
        if installment is not None and installment <= 0:
            self.add_error(
                "monthly_installment",
                "Monthly installment must be more than zero.")
        if (self.instance is not None and self.instance.pk
                and amount is not None):
            from employees.services import loan_repaid
            repaid = loan_repaid(self.instance)
            if amount < repaid:
                self.add_error(
                    "amount",
                    f"Loan amount cannot be less than the Rs {repaid} "
                    "already repaid.")
        return cleaned


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
        fields = ["bonus", "deductions", "deduction_note",
                  "loan", "loan_deduction"]
        widgets = {
            "bonus": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01"}),
            "deductions": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01"}),
            "loan_deduction": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance is not None and self.instance.pk:
            # Active loans, plus the row's own loan even if it settled
            # since, so an existing selection never vanishes.
            qs = Loan.objects.filter(employee=self.instance.employee)
            qs = qs.filter(
                models.Q(status=Loan.STATUS_ACTIVE)
                | models.Q(pk=self.instance.loan_id)
            ).order_by("date", "id")
            self.fields["loan"].queryset = qs
            self.fields["loan"].required = False
            self.fields["loan_deduction"].required = False

    def clean(self):
        cleaned = super().clean()
        bonus = cleaned.get("bonus")
        deductions = cleaned.get("deductions")
        loan = cleaned.get("loan")
        loan_deduction = cleaned.get("loan_deduction") or Decimal("0")
        if self.instance.pk:
            if loan_deduction > 0 and loan is None:
                self.add_error(
                    "loan",
                    "Pick the loan this deduction repays, or set the "
                    "loan deduction to zero.")
            elif loan is not None and loan_deduction > loan_remaining(loan):
                self.add_error(
                    "loan_deduction",
                    f"Cannot exceed the Rs {loan_remaining(loan)} still "
                    "owed on this loan.")
            if bonus is not None and deductions is not None:
                try:
                    compute_net(
                        self.instance.base_salary, bonus, deductions,
                        loan_deduction)
                except forms.ValidationError as exc:
                    self.add_error("deductions", exc)
        return cleaned


class MarkPaidForm(BootstrapWidgetsMixin, forms.Form):
    paid_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"})
    )
    # Empty = pay the net salary. A different amount requires a note.
    paid_amount = forms.DecimalField(
        required=False, max_digits=12, decimal_places=2,
        widget=forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01"}),
    )
    paid_note = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "placeholder": "Required if the amount differs from net salary"}),
    )

    def __init__(self, *args, payroll=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.payroll = payroll
        self.fields["paid_date"].initial = timezone.localdate()
        if payroll is not None:
            self.fields["paid_amount"].initial = payroll.net_salary
            self.fields["paid_amount"].help_text = (
                f"Net salary is Rs {payroll.net_salary}. Leave it to pay "
                "the net, or enter the amount actually paid."
            )

    def clean_paid_date(self):
        value = self.cleaned_data.get("paid_date")
        if value and value > timezone.localdate():
            raise forms.ValidationError("Paid date cannot be in the future.")
        return value

    def clean(self):
        cleaned = super().clean()
        amount = cleaned.get("paid_amount")
        note = (cleaned.get("paid_note") or "").strip()
        if amount is not None and amount < 0:
            self.add_error("paid_amount", "Amount paid cannot be negative.")
        if (self.payroll is not None and amount is not None
                and amount != self.payroll.net_salary and not note):
            self.add_error(
                "paid_note",
                "Amount paid differs from net salary — a note is required.")
        return cleaned
