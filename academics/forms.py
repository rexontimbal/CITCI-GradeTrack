from django import forms
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
        fields = ["academic_year", "term", "start_date", "end_date"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }


class ProgramForm(StyledModelForm):
    class Meta:
        model = Program
        fields = ["code", "name", "program_head", "is_active"]


class MajorForm(StyledModelForm):
    class Meta:
        model = Major
        fields = ["program", "code", "name", "is_active"]


class SectionForm(StyledModelForm):
    class Meta:
        model = Section
        fields = ["program", "major", "academic_year", "year_level", "name"]


class SubjectForm(StyledModelForm):
    class Meta:
        model = Subject
        fields = ["code", "title", "units", "program", "major", "year_level", "term", "is_active"]


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
