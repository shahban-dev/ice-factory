"""Forms helpers: optimistic-concurrency version field and Bootstrap
widget styling.

Templates render ``{{ field }}`` directly, so widgets must carry their
own Bootstrap classes — otherwise inputs render as unstyled browser
defaults that overflow narrow columns on phones (as the sale form
once did).
"""

from django import forms


def style_form_widgets(form):
    """Add Bootstrap classes to every visible widget of a form instance.

    Selects get ``form-select``, checkboxes get ``form-check-input``,
    everything else gets ``form-control``. Hidden inputs are skipped.
    Safe to call on any form; existing classes are kept.
    """
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, forms.HiddenInput):
            continue
        if isinstance(widget, forms.CheckboxInput):
            add = "form-check-input"
        elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
            add = "form-select"
        else:
            add = "form-control"
        existing = widget.attrs.get("class", "")
        if add not in existing.split():
            widget.attrs["class"] = f"{existing} {add}".strip()


class BootstrapWidgetsMixin:
    """Plain mixin that styles widgets. Add it to any form class."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_form_widgets(self)


class VersionedFormMixin(BootstrapWidgetsMixin, forms.Form):
    """Adds a hidden ``version`` field carrying the version the form was
    loaded with. Views compare it against the locked row before saving.

    Note: the mixin must subclass ``forms.Form`` so Django's form
    metaclass collects the declared ``version`` field. A plain mixin
    attribute is silently ignored by ModelForm, which used to make every
    edit page crash (and every edit POST fail the version check).
    """

    version = forms.IntegerField(widget=forms.HiddenInput(), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance is not None and self.instance.pk is not None:
            self.fields["version"].initial = self.instance.version
