from django import forms
from django.core.exceptions import ValidationError

from core.forms import StyledModelForm

from .models import AssessmentItem, ClassGradingScheme, GradingComponent, GradingTemplate, SchemeComponent
from .services import check_can_delete_scheme_component, ensure_locked_component_unchanged, validate_component_weights


class GradingTemplateForm(StyledModelForm):
    class Meta:
        model = GradingTemplate
        fields = ["name", "description", "is_default", "is_active"]


class GradingComponentForm(StyledModelForm):
    class Meta:
        model = GradingComponent
        fields = ["name", "category", "weight", "is_locked", "order"]


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


class SchemeComponentForm(StyledModelForm):
    """One row of the instructor's "Grading Components" panel (class Setup
    tab). A locked component's fields are rendered read-only/inert in the
    UI (readonly text inputs, an inert select — see the widget attrs below)
    — but, unlike Django's `disabled=True`, a readonly/inert field still
    submits and gets validated normally, so a tampered POST (e.g. via dev
    tools) is actually caught and rejected by clean() below with a clear
    error, rather than silently ignored."""

    weight = forms.IntegerField(min_value=1, max_value=100, label="Weight %", help_text="Whole numbers only.")

    class Meta:
        model = SchemeComponent
        fields = ["name", "category", "weight"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.is_locked:
            self.fields["name"].widget.attrs["readonly"] = "readonly"
            self.fields["weight"].widget.attrs["readonly"] = "readonly"
            # <select> has no native readonly, so category is instead made
            # inert with CSS/JS; the server-side check below is what
            # actually enforces it either way.
            self.fields["category"].widget.attrs["class"] += " pointer-events-none"
            self.fields["category"].widget.attrs["tabindex"] = "-1"
            for field in self.fields.values():
                field.widget.attrs.setdefault("class", "")
                field.widget.attrs["class"] += " bg-gray-100 text-gray-500"

    def clean(self):
        cleaned_data = super().clean()
        if self.instance and self.instance.pk and self.instance.is_locked:
            ensure_locked_component_unchanged(
                self.instance, cleaned_data.get("name"), cleaned_data.get("category"), cleaned_data.get("weight")
            )
        return cleaned_data


class _SchemeComponentBaseFormSet(forms.BaseInlineFormSet):
    """The whole "Grading Components" panel is one form: add/edit/delete
    rows together, validated — and saved — as a single atomic set, so the
    100% total check (locked + unlocked) runs on the combination the
    instructor actually intends, not on every individual row save."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return

        total_weight = 0
        seen_names = {}
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                if form.cleaned_data.get("DELETE") and form.instance.pk:
                    can_delete, reason = check_can_delete_scheme_component(form.instance)
                    if not can_delete:
                        form.add_error(None, reason)
                continue
            total_weight += form.cleaned_data.get("weight") or 0

            name = (form.cleaned_data.get("name") or "").strip()
            key = name.lower()
            if key in seen_names:
                form.add_error(None, "A component with this name already exists in this class.")
                seen_names[key].add_error(None, "A component with this name already exists in this class.")
            else:
                seen_names[key] = form

        if any(self.errors):
            return

        if total_weight > 100:
            raise forms.ValidationError(f"Total is {total_weight}% — reduce by {total_weight - 100}%.")
        if total_weight < 100:
            raise forms.ValidationError(f"Total is {total_weight}% — add {100 - total_weight}%.")


SchemeComponentFormSet = forms.inlineformset_factory(
    ClassGradingScheme,
    SchemeComponent,
    form=SchemeComponentForm,
    formset=_SchemeComponentBaseFormSet,
    fk_name="scheme",
    extra=0,
    can_delete=True,
)


class AssessmentItemForm(StyledModelForm):
    max_score = forms.IntegerField(min_value=1, label="Max Score", help_text="Whole numbers only.")

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
