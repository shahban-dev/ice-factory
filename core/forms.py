"""Forms helpers: optimistic-concurrency version field."""

from django import forms


class VersionedFormMixin(forms.Form):
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
