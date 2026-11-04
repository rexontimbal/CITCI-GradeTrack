from django import forms

from core.forms import StyledModelForm

from .models import InstitutionSettings


class InstitutionSettingsForm(StyledModelForm):
    class Meta:
        model = InstitutionSettings
        fields = [
            "school_name",
            "sub_line",
            "address",
            "department",
            "logo",
            "dean_name",
            "dean_title",
            "academic_head_name",
            "academic_head_title",
            "registrar_name",
            "registrar_title",
            "show_unofficial_scores_to_students",
            "show_forecasts_to_students",
            "privacy_notice_text",
            "data_privacy_officer_contact",
        ]
        widgets = {
            "privacy_notice_text": forms.Textarea(attrs={"rows": 8}),
        }
