from django.contrib.auth.forms import SetPasswordForm

_INPUT_CLASSES = (
    "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm "
    "focus:border-brand-accent-600 focus:outline-none focus:ring-2 focus:ring-brand-accent-500"
)


class ForcedPasswordChangeForm(SetPasswordForm):
    """Same validation as Django's SetPasswordForm; used on first login."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = _INPUT_CLASSES
