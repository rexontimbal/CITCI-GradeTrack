from django import forms

from core.forms import StyledModelForm

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
