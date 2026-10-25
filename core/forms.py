from django import forms

INPUT_CLASSES = (
    "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm "
    "focus:border-brand-accent-600 focus:outline-none focus:ring-2 focus:ring-brand-accent-500"
)
CHECKBOX_CLASSES = "h-4 w-4 rounded border-gray-300 text-brand-accent-600 focus:ring-brand-accent-500"


class StyledModelForm(forms.ModelForm):
    """Applies consistent Tailwind classes to every field's widget so
    per-entity forms don't need to repeat it."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = CHECKBOX_CLASSES
            else:
                field.widget.attrs["class"] = INPUT_CLASSES
