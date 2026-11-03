from django import forms

from core.forms import INPUT_CLASSES

from .models import GradeSheetEntry

TEXTAREA_CLASSES = "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"


class ReturnRemarksForm(forms.Form):
    remarks = forms.CharField(
        label="Remarks for the instructor",
        widget=forms.Textarea(attrs={"rows": 3, "class": TEXTAREA_CLASSES}),
    )


class SubmitConfirmForm(forms.Form):
    certify = forms.BooleanField(
        label="I certify these grades are final and correct.",
        widget=forms.CheckboxInput(
            attrs={"class": "h-4 w-4 rounded border-gray-300 text-brand-accent-600 focus:ring-brand-accent-500"}
        ),
    )


class CorrectionForm(forms.Form):
    final_grade = forms.DecimalField(
        label="Final grade",
        min_value=1,
        max_value=5,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"step": "0.01", "class": INPUT_CLASSES}),
    )
    remarks = forms.ChoiceField(choices=GradeSheetEntry.Remarks.choices, widget=forms.Select(attrs={"class": INPUT_CLASSES}))
    reason = forms.CharField(
        label="Reason for this correction",
        widget=forms.Textarea(attrs={"rows": 3, "class": TEXTAREA_CLASSES}),
    )
