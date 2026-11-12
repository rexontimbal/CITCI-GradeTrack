from decimal import Decimal

from django import forms
from django.db.models import Q
from django.urls import reverse_lazy

from accounts.models import User
from core.forms import INPUT_CLASSES, StyledModelForm
from core.widgets import SearchableSelectWidget

from .models import (
    YEAR_LEVEL_CHOICES,
    AcademicYear,
    ClassOffering,
    CurriculumEntry,
    Major,
    Program,
    Section,
    Semester,
    Subject,
)


class AcademicYearForm(StyledModelForm):
    class Meta:
        model = AcademicYear
        fields = ["start_year"]


class SemesterForm(StyledModelForm):
    class Meta:
        model = Semester
        fields = ["academic_year", "term", "start_date", "end_date", "submission_deadline"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "submission_deadline": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.duration_warning = None

    def clean(self):
        from .semester_validation import duration_warning, ranges_overlap, validate_date_range

        cleaned_data = super().clean()
        academic_year = cleaned_data.get("academic_year")
        term = cleaned_data.get("term")
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")

        if academic_year and (start_date or end_date):
            errors = validate_date_range(start_date, end_date, academic_year.start_year, academic_year.end_year)
            for field, message in errors.items():
                self.add_error(field, message)

            if not errors and start_date and end_date:
                others = Semester.objects.filter(
                    academic_year=academic_year, start_date__isnull=False, end_date__isnull=False
                ).exclude(pk=self.instance.pk)
                for other in others:
                    if ranges_overlap(start_date, end_date, other.start_date, other.end_date):
                        self.add_error(
                            None,
                            f"This overlaps with {other} ({other.start_date} to {other.end_date}).",
                        )
                        break

            if not errors:
                self.duration_warning = duration_warning(term, start_date, end_date)

        return cleaned_data


class ProgramForm(StyledModelForm):
    class Meta:
        model = Program
        fields = ["code", "name", "program_head", "is_active"]


class MajorForm(StyledModelForm):
    class Meta:
        model = Major
        fields = ["program", "code", "name", "program_head", "is_active"]


_SECTION_LETTER_WIDGET_ATTRS = {"maxlength": "1", "style": "text-transform: uppercase;", "placeholder": "A"}


class SectionForm(StyledModelForm):
    name = forms.CharField(
        required=False,
        max_length=1,
        label="Letter",
        help_text="Leave blank if this is the only section for this year level.",
        widget=forms.TextInput(attrs=_SECTION_LETTER_WIDGET_ATTRS),
    )

    class Meta:
        model = Section
        fields = ["program", "major", "academic_year", "year_level", "name"]


def _restrict_program_major_fields(form, user):
    """Shared by every Program-Head-scoped form with program/major fields
    (Section, and the curriculum-placement side of Subject): restricts
    both querysets to academics.scoping.scope_for(user), and pre-selects
    program when there's only one choice. A program-level scope tuple
    only covers majors with no head of their own — one with its own head
    is that head's exclusively."""
    from .scoping import scope_for

    scope = scope_for(user) or set()
    program_ids = {program_id for program_id, _ in scope}
    major_ids = {major_id for _, major_id in scope if major_id is not None}
    form.fields["program"].queryset = Program.objects.filter(pk__in=program_ids)
    form.fields["major"].queryset = Major.objects.filter(
        Q(pk__in=major_ids) | Q(program_id__in=program_ids, program_head__isnull=True)
    )
    if len(program_ids) == 1 and not form.initial.get("program"):
        form.initial["program"] = next(iter(program_ids))


class ProgramHeadSectionForm(StyledModelForm):
    """Same model as SectionForm, but program/major choices are locked to
    the acting Program Head's scope (academics.scoping.scope_for) and
    academic_year is never a form field — the view locks it to the active
    semester's academic year server-side."""

    name = forms.CharField(
        required=False,
        max_length=1,
        label="Letter",
        help_text="Leave blank if this is the only section for this year level.",
        widget=forms.TextInput(attrs=_SECTION_LETTER_WIDGET_ATTRS),
    )

    class Meta:
        model = Section
        fields = ["program", "major", "year_level", "name"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        _restrict_program_major_fields(self, user)


_UNITS_WIDGET_ATTRS = {"type": "number", "step": "0.5", "min": "0.5", "max": "9.0", "class": "no-spinner"}


class AdminSubjectForm(StyledModelForm):
    """Admin can edit any subject's code/title/units/active flag directly
    — used by the admin prospectus page's edit action. Unlike a Program
    Head, admin isn't restricted to subjects used solely within one scope
    (see SubjectEditForm). Code-change restrictions (uniqueness, blocked
    once released grades reference it) are enforced in the view, not
    here, since they depend on request context (is this a "Correct code"
    action, who's asking)."""

    class Meta:
        model = Subject
        fields = ["code", "title", "units", "is_active"]
        widgets = {"units": forms.NumberInput(attrs=_UNITS_WIDGET_ATTRS)}


class SubjectEditForm(StyledModelForm):
    """A Program Head may edit title/units/code of a subject used solely
    within their own scope — a code change is still subject to the same
    view-level uniqueness/released-grades checks as admin's."""

    class Meta:
        model = Subject
        fields = ["code", "title", "units"]
        widgets = {"units": forms.NumberInput(attrs=_UNITS_WIDGET_ATTRS)}


class SubjectAddForm(forms.Form):
    """The Add Subject modal's single form — one `code` field doubles as
    a lookup: if it matches an existing catalog subject (case/spacing-
    insensitive), `title`/`units` are ignored and the existing subject is
    reused; otherwise they're required and a new Subject is created.
    `matched_subject` is stashed on `cleaned_data` by `clean()` for the
    view to act on without re-querying."""

    code = forms.CharField(
        max_length=20,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "hx-get": reverse_lazy("academics:subject_add"),
                "hx-include": "closest form",
                "hx-target": "#modal-content",
                "hx-swap": "innerHTML",
                "hx-trigger": "keyup changed delay:300ms",
            }
        ),
    )
    title = forms.CharField(max_length=200, required=False)
    units = forms.DecimalField(
        max_digits=3,
        decimal_places=1,
        min_value=Decimal("0.5"),
        max_value=Decimal("9.0"),
        required=False,
        widget=forms.NumberInput(attrs=_UNITS_WIDGET_ATTRS),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A plain forms.Form (not StyledModelForm) never gets the shared
        # bordered-input classes automatically -- apply them here, merged
        # with each field's own attrs (hx-* on code, no-spinner on units)
        # rather than overwriting them.
        for field in self.fields.values():
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{INPUT_CLASSES} {existing}".strip()

    def clean(self):
        from .services import find_subject_by_normalized_code

        cleaned = super().clean()
        code = (cleaned.get("code") or "").strip()
        if not code:
            return cleaned
        matched = find_subject_by_normalized_code(code)
        cleaned["matched_subject"] = matched
        if matched is None:
            if not cleaned.get("title"):
                self.add_error("title", "Required for a new subject.")
            if cleaned.get("units") is None:
                self.add_error("units", "Required for a new subject.")
        return cleaned


class SubjectCodeCorrectionForm(forms.Form):
    """Admin-only "Correct code" action — bypasses the normal released-
    grades block (`subject_edit` applies that to everyone else), but
    requires a reason and is always logged as an admin override."""

    code = forms.CharField(max_length=20)
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{INPUT_CLASSES} {existing}".strip()


class AdhocOfferingForm(forms.Form):
    """"Offer another subject…" — any active subject, even one outside
    this program/major's curriculum for this term (academics.services.
    preview_adhoc_offering handles the rest, with its own warning copy in
    the template)."""

    subject = forms.ModelChoiceField(
        queryset=Subject.objects.filter(is_active=True),
        widget=SearchableSelectWidget(
            search_url=reverse_lazy("academics:subject_search"), queryset=Subject.objects.filter(is_active=True)
        ),
        label="Subject",
    )
    year_level = forms.TypedChoiceField(
        choices=[("", "No year level (e.g. TCP)")] + list(YEAR_LEVEL_CHOICES),
        coerce=int,
        empty_value=None,
        required=False,
        label="Year level",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        existing = self.fields["year_level"].widget.attrs.get("class", "")
        self.fields["year_level"].widget.attrs["class"] = f"{INPUT_CLASSES} {existing}".strip()


def _grouped_subject_choices(sections, term=None, base_queryset=None):
    """Groups the subject picker into "From the curriculum" (subjects
    with a CurriculumEntry matching any of `sections`' program/major/
    year_level, for `term` if given) first, then "All subjects" -- using
    Django's native grouped-choices support on ModelChoiceField (a list
    of (group_label, [(pk, label), ...]) tuples). Falls back to one
    ungrouped list when no sections are selected yet (nothing to suggest
    from)."""
    base_queryset = Subject.objects.filter(is_active=True) if base_queryset is None else base_queryset
    all_subjects = list(base_queryset.order_by("code"))
    if not sections:
        return [(s.pk, str(s)) for s in all_subjects]

    # Built per-section as an OR'd Q(), not a blind field__in=[...,None] --
    # SQL's IN (NULL) never matches a NULL column (it needs IS NULL), so a
    # section with no major/year_level needs its own isnull=True clause.
    section_q = Q()
    for s in sections:
        major_q = Q(major_id=s.major_id) if s.major_id is not None else Q(major_id__isnull=True)
        year_q = Q(year_level=s.year_level) if s.year_level is not None else Q(year_level__isnull=True)
        section_q |= Q(program_id=s.program_id) & major_q & year_q
    entries = CurriculumEntry.objects.filter(section_q).select_related("subject")
    if term:
        entries = entries.filter(term=term)
    suggested_ids = {e.subject_id for e in entries if e.subject.is_active}
    if not suggested_ids:
        return [(s.pk, str(s)) for s in all_subjects]

    suggested = [s for s in all_subjects if s.pk in suggested_ids]
    rest = [s for s in all_subjects if s.pk not in suggested_ids]
    choices = []
    if suggested:
        choices.append(("From the curriculum", [(s.pk, str(s)) for s in suggested]))
    if rest:
        choices.append(("All subjects", [(s.pk, str(s)) for s in rest]))
    return choices


class ClassOfferingForm(StyledModelForm):
    sections = forms.ModelMultipleChoiceField(
        queryset=Section.objects.select_related("program", "major"),
        widget=forms.SelectMultiple(attrs={"size": 6}),
        help_text="Select every section this class serves (hold Ctrl/Cmd to pick more than one).",
    )
    instructor = forms.ModelChoiceField(
        queryset=User.objects.filter(role=User.Role.INSTRUCTOR, is_active=True),
        required=False,
        widget=SearchableSelectWidget(
            search_url=reverse_lazy("academics:instructor_search"),
            queryset=User.objects.filter(role=User.Role.INSTRUCTOR),
        ),
        help_text="Teaching loads are normally assigned by the Program Head — changing it here is logged "
        "as an admin override.",
    )

    class Meta:
        model = ClassOffering
        fields = ["subject", "sections", "semester", "instructor", "schedule", "room", "is_active"]

    def __init__(self, *args, selected_sections=None, **kwargs):
        super().__init__(*args, **kwargs)
        sections = selected_sections if selected_sections is not None else (
            list(self.instance.sections.all()) if self.instance.pk else []
        )
        term = self.instance.semester.term if self.instance.pk else None
        self.fields["subject"].choices = _grouped_subject_choices(sections, term=term)

    def clean(self):
        cleaned_data = super().clean()
        semester = cleaned_data.get("semester")
        sections = cleaned_data.get("sections")
        if semester and sections:
            mismatched = [s for s in sections if s.academic_year_id != semester.academic_year_id]
            if mismatched:
                names = ", ".join(str(s) for s in mismatched)
                self.add_error(
                    "sections", f"These sections aren't in the semester's academic year: {names}"
                )
        return cleaned_data


class ProgramHeadClassOfferingForm(StyledModelForm):
    """Same model as ClassOfferingForm, but `sections` is restricted to the
    acting Program Head's own in-scope sections for the active academic
    year, `subject` is any active subject (the shared catalog — see
    ProgramHeadSubjectForm), and there's no `semester` field — the view
    locks it to the active semester server-side."""

    subject = forms.ModelChoiceField(queryset=Subject.objects.filter(is_active=True))
    instructor = forms.ModelChoiceField(
        queryset=User.objects.filter(role=User.Role.INSTRUCTOR, is_active=True),
        required=False,
        widget=SearchableSelectWidget(
            search_url=reverse_lazy("academics:instructor_search"),
            queryset=User.objects.filter(role=User.Role.INSTRUCTOR),
        ),
    )

    class Meta:
        model = ClassOffering
        fields = ["subject", "sections", "schedule", "room", "instructor", "is_active"]

    def __init__(self, *args, user=None, academic_year=None, selected_sections=None, term=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .scoping import sections_in_scope

        qs = sections_in_scope(user)
        if academic_year is not None:
            qs = qs.filter(academic_year=academic_year)
        self.fields["sections"].queryset = qs.select_related("program", "major")

        sections = selected_sections if selected_sections is not None else (
            list(self.instance.sections.all()) if self.instance.pk else []
        )
        resolved_term = term if term is not None else (self.instance.semester.term if self.instance.pk else None)
        self.fields["subject"].choices = _grouped_subject_choices(sections, term=resolved_term)


class JoinClassForm(forms.Form):
    """"Join existing class" — add the acting head's own in-scope sections
    to a class someone else already created for the same subject+semester,
    instead of creating a duplicate class."""

    class_offering = forms.ModelChoiceField(queryset=ClassOffering.objects.none(), label="Class to join")
    sections = forms.ModelMultipleChoiceField(
        queryset=Section.objects.none(), widget=forms.SelectMultiple(attrs={"size": 5}), label="Your section(s) to add"
    )

    def __init__(self, *args, class_queryset=None, sections_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["class_offering"].queryset = class_queryset
        self.fields["sections"].queryset = sections_queryset
        for field in self.fields.values():
            field.widget.attrs["class"] = "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"


class TeachingAssignmentForm(forms.Form):
    """Not a ModelForm — academics.services.assign_instructor does the
    actual mutation + validation + logging + notifications; this form only
    collects the two inputs the "Assign/Change instructor" modal needs."""

    instructor = forms.ModelChoiceField(
        queryset=User.objects.filter(role=User.Role.INSTRUCTOR, is_active=True),
        required=False,
        widget=SearchableSelectWidget(
            search_url=reverse_lazy("academics:instructor_search"),
            queryset=User.objects.filter(role=User.Role.INSTRUCTOR),
        ),
        label="Instructor",
        help_text="Leave blank to unassign.",
    )
    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "class": "w-full rounded-lg border-gray-300 text-sm"}),
        help_text="Optional — shown in the audit log and this class's assignment history.",
    )




class JoinCodeForm(forms.Form):
    code = forms.CharField(
        max_length=7,
        label="Join code",
        widget=forms.TextInput(
            attrs={
                "class": "w-full rounded-lg border border-gray-300 px-3 py-2 text-center text-lg font-semibold uppercase tracking-widest",
                "placeholder": "ABCD123",
                "autocomplete": "off",
            }
        ),
    )

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()
