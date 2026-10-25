from django import forms

from core.forms import StyledModelForm

from .models import AcademicYear, ClassOffering, Program, Section, Semester, Subject


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


class SectionForm(StyledModelForm):
    class Meta:
        model = Section
        fields = ["program", "academic_year", "year_level", "name"]


class SubjectForm(StyledModelForm):
    class Meta:
        model = Subject
        fields = ["code", "title", "lec_units", "lab_units", "program", "year_level", "term", "is_active"]


class ClassOfferingForm(StyledModelForm):
    class Meta:
        model = ClassOffering
        fields = ["subject", "section", "semester", "instructor", "schedule", "room", "is_active"]
