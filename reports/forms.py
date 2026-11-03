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
        ]
