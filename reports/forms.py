"""Settings and manual-backup forms."""

from django import forms

from core.forms import BootstrapWidgetsMixin
from core.models import Settings


class SettingsForm(BootstrapWidgetsMixin, forms.ModelForm):
    class Meta:
        model = Settings
        fields = ["factory_name", "address", "phone", "invoice_prefix",
                  "tax_registration_line", "invoice_footer_note",
                  "week_start_day"]
        widgets = {
            "factory_name": forms.TextInput(attrs={"autofocus": True}),
        }


class BackupDownloadForm(BootstrapWidgetsMixin, forms.Form):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
        help_text="Enter your login password again to confirm.",
    )
