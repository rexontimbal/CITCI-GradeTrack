from django import forms

from core.forms import StyledModelForm

from .models import Intervention


class InterventionForm(StyledModelForm):
    class Meta:
        model = Intervention
        fields = ["date", "type", "notes", "follow_up_date", "outcome"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "follow_up_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
