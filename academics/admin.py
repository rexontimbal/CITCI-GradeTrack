from django.contrib import admin

from config.admin import site

from .models import (
    AcademicYear,
    ClassOffering,
    ClassRosterEntry,
    CurriculumEntry,
    Major,
    Program,
    Section,
    SectionMembership,
    Semester,
    StudentProfile,
    Subject,
)


@admin.register(AcademicYear, site=site)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ("__str__", "start_year", "end_year")
    ordering = ("-start_year",)


@admin.register(Semester, site=site)
class SemesterAdmin(admin.ModelAdmin):
    list_display = ("__str__", "academic_year", "term", "is_active")
    list_filter = ("academic_year", "term", "is_active")


@admin.register(Program, site=site)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "program_head", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")


@admin.register(Major, site=site)
class MajorAdmin(admin.ModelAdmin):
    list_display = ("__str__", "name", "program", "is_active")
    list_filter = ("program", "is_active")
    search_fields = ("code", "name")


@admin.register(Section, site=site)
class SectionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "program", "major", "academic_year", "year_level", "name")
    list_filter = ("program", "major", "academic_year", "year_level")
    search_fields = ("name", "program__code")


@admin.register(Subject, site=site)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "units", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "title")


@admin.register(CurriculumEntry, site=site)
class CurriculumEntryAdmin(admin.ModelAdmin):
    list_display = ("subject", "program", "major", "year_level", "term")
    list_filter = ("program", "major", "year_level", "term")
    search_fields = ("subject__code", "subject__title")


@admin.register(StudentProfile, site=site)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "program", "major", "status")
    list_filter = ("program", "major", "status")
    search_fields = ("user__username", "user__first_name", "user__last_name", "user__id_number")


@admin.register(SectionMembership, site=site)
class SectionMembershipAdmin(admin.ModelAdmin):
    list_display = ("student", "section", "semester")
    list_filter = ("semester", "section__program")
    search_fields = ("student__username", "student__first_name", "student__last_name", "student__id_number")


@admin.register(ClassOffering, site=site)
class ClassOfferingAdmin(admin.ModelAdmin):
    list_display = ("__str__", "semester", "instructor", "roster_count", "is_active")
    list_filter = ("semester", "sections__program", "is_active")
    search_fields = ("subject__code", "subject__title")
    filter_horizontal = ("sections",)


@admin.register(ClassRosterEntry, site=site)
class ClassRosterEntryAdmin(admin.ModelAdmin):
    list_display = ("student", "class_offering", "status", "date_added", "date_dropped")
    list_filter = ("status", "class_offering__semester")
    search_fields = ("student__username", "student__first_name", "student__last_name")
