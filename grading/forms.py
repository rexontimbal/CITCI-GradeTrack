from django import forms
from django.core.exceptions import ValidationError

from core.forms import StyledModelForm

from .models import AssessmentItem, GradingComponent, GradingTemplate
from .services import validate_component_weights


class GradingTemplateForm(StyledModelForm):
    class Meta:
        model = GradingTemplate
        fields = ["name", "description", "is_default", "is_active"]


class GradingComponentForm(StyledModelForm):
    class Meta:
        model = GradingComponent
        fields = ["name", "weight", "order"]


class ComponentWeightCheckFormSet(forms.BaseInlineFormSet):
    """Only used where all of a template's components are edited together
    (the "new template" flow); the per-component add/edit/delete pages don't
    use this — they can't enforce the 100% total on every single save
    without making editing painful, so that check runs at apply-time instead
    (see ClassGradingScheme.apply_template)."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        weights = [
            form.cleaned_data["weight"]
            for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get("DELETE")
        ]
        if weights:
            try:
                validate_component_weights(weights)
            except ValidationError as exc:
                raise forms.ValidationError(exc.message)


GradingComponentFormSet = forms.inlineformset_factory(
    GradingTemplate,
    GradingComponent,
    form=GradingComponentForm,
    formset=ComponentWeightCheckFormSet,
    extra=1,
    can_delete=True,
)


class AssessmentItemForm(StyledModelForm):
    class Meta:
        model = AssessmentItem
        fields = ["component", "title", "max_score", "term", "date", "order"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, scheme=None, **kwargs):
        super().__init__(*args, **kwargs)
        if scheme is not None:
            self.fields["component"].queryset = scheme.components.all()
        elif self.instance and self.instance.pk:
            self.fields["component"].queryset = self.instance.component.scheme.components.all()


class MarkIncompleteForm(forms.Form):
    is_incomplete = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(
            attrs={"class": "h-4 w-4 rounded border-gray-300 text-brand-accent-600 focus:ring-brand-accent-500"}
        ),
    )
    incomplete_reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "class": "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"}),
    )

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("is_incomplete") and not cleaned_data.get("incomplete_reason"):
            self.add_error("incomplete_reason", "A reason is required when marking a student INC.")
        return cleaned_data
