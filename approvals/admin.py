from django.contrib import admin

from config.admin import site

from .models import GradeCorrection, GradeSheet, GradeSheetEntry, GradeSheetTransition


class GradeSheetEntryInline(admin.TabularInline):
    model = GradeSheetEntry
    extra = 0


class GradeSheetTransitionInline(admin.TabularInline):
    model = GradeSheetTransition
    extra = 0


@admin.register(GradeSheet, site=site)
class GradeSheetAdmin(admin.ModelAdmin):
    list_display = ("class_offering", "period", "status", "submitted_at", "approved_at", "released_at", "locked_at")
    list_filter = ("status", "period", "class_offering__semester")
    search_fields = ("class_offering__subject__code",)
    inlines = [GradeSheetTransitionInline, GradeSheetEntryInline]


@admin.register(GradeSheetEntry, site=site)
class GradeSheetEntryAdmin(admin.ModelAdmin):
    list_display = ("sheet", "roster_entry", "final_grade", "remarks")
    list_filter = ("remarks",)
    search_fields = ("roster_entry__student__username", "roster_entry__student__last_name")


@admin.register(GradeCorrection, site=site)
class GradeCorrectionAdmin(admin.ModelAdmin):
    list_display = ("entry", "old_grade", "new_grade", "corrected_by", "created_at")
    search_fields = ("entry__roster_entry__student__username",)


@admin.register(GradeSheetTransition, site=site)
class GradeSheetTransitionAdmin(admin.ModelAdmin):
    list_display = ("sheet", "from_status", "to_status", "actor", "created_at")
    list_filter = ("to_status",)
