from django import forms
from django.db.models import Q
from django.urls import reverse_lazy

from accounts.models import User
from core.forms import StyledModelForm
from core.widgets import SearchableSelectWidget

from .models import AcademicYear, ClassOffering, Major, Program, Section, Semester, Subject


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
    (Section, Subject): restricts both querysets to academics.scoping.
    scope_for(user), and pre-selects program when there's only one choice.
    A program-level scope tuple only covers majors with no head of their
    own — one with its own head is that head's exclusively."""
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


class SubjectForm(StyledModelForm):
    class Meta:
        model = Subject
        fields = ["code", "title", "units", "program", "major", "year_level", "term", "is_active"]


class ProgramHeadSubjectForm(StyledModelForm):
    """Same model as SubjectForm, but `program` is required (not blankable
    — shared/general subjects with no program stay admin-only to create,
    per the shared-subject-catalog rule) and program/major choices are
    locked to scope."""

    class Meta:
        model = Subject
        fields = ["code", "title", "units", "program", "major", "year_level", "term", "is_active"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["program"].required = True
        self.fields["program"].empty_label = None
        _restrict_program_major_fields(self, user)


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

    def __init__(self, *args, user=None, academic_year=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .scoping import sections_in_scope

        qs = sections_in_scope(user)
        if academic_year is not None:
            qs = qs.filter(academic_year=academic_year)
        self.fields["sections"].queryset = qs.select_related("program", "major")


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
