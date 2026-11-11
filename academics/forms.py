from django import forms
from django.db.models import Q
from django.urls import reverse_lazy

from accounts.models import User
from core.forms import StyledModelForm
from core.widgets import SearchableSelectWidget

from .models import AcademicYear, ClassOffering, CurriculumEntry, Major, Program, Section, Semester, Subject


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


class SectionForm(StyledModelForm):
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

    class Meta:
        model = Section
        fields = ["program", "major", "year_level", "name"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        _restrict_program_major_fields(self, user)


class AdminSubjectForm(StyledModelForm):
    """Admin can edit any subject's code/title/units/active flag directly
    — used by the admin prospectus page's edit action. Unlike a Program
    Head, admin isn't restricted to subjects used solely within one scope
    (see SubjectEditForm)."""

    class Meta:
        model = Subject
        fields = ["code", "title", "units", "is_active"]


class SubjectEditForm(StyledModelForm):
    """A Program Head may only edit title/units of a subject used solely
    within their own scope — never its code (that's admin-only, since a
    code change could affect other programs sharing the subject, even
    though *this* subject happens not to be shared right now)."""

    class Meta:
        model = Subject
        fields = ["title", "units"]


class SubjectQuickCreateForm(StyledModelForm):
    """The "create a new subject" path of the Add-to-curriculum modal —
    code/title/units only; the new subject is immediately attached to one
    CurriculumEntry by the view, never left unplaced."""

    class Meta:
        model = Subject
        fields = ["code", "title", "units"]


class CurriculumEntryExistingSubjectForm(forms.Form):
    """The "use an existing subject" path of the Add-to-curriculum modal
    — program/major/year_level/term come from the page's current filter
    context server-side, never from this form."""

    subject = forms.ModelChoiceField(
        queryset=Subject.objects.filter(is_active=True),
        label="Subject",
        widget=SearchableSelectWidget(
            search_url=reverse_lazy("academics:subject_search"),
            queryset=Subject.objects.filter(is_active=True),
        ),
    )


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


class BulkAssignInstructorForm(forms.Form):
    class_ids = forms.ModelMultipleChoiceField(queryset=ClassOffering.objects.all(), widget=forms.MultipleHiddenInput)
    instructor = forms.ModelChoiceField(
        queryset=User.objects.filter(role=User.Role.INSTRUCTOR, is_active=True),
        widget=SearchableSelectWidget(
            search_url=reverse_lazy("academics:instructor_search"),
            queryset=User.objects.filter(role=User.Role.INSTRUCTOR),
        ),
        label="Assign to instructor",
    )
