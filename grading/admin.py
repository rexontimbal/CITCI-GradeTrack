from django.contrib import admin

from config.admin import site

from .models import (
    AssessmentItem,
    ClassGradingScheme,
    GradingComponent,
    GradingTemplate,
    SchemeComponent,
    Score,
    ScoreChangeLog,
)


class GradingComponentInline(admin.TabularInline):
    model = GradingComponent
    extra = 1


@admin.register(GradingTemplate, site=site)
class GradingTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "weight_total", "is_default", "is_active")
    list_filter = ("is_default", "is_active")
    search_fields = ("name",)
    inlines = [GradingComponentInline]


class SchemeComponentInline(admin.TabularInline):
    model = SchemeComponent
    extra = 0


@admin.register(ClassGradingScheme, site=site)
class ClassGradingSchemeAdmin(admin.ModelAdmin):
    list_display = ("class_offering", "source_template")
    search_fields = ("class_offering__subject__code",)
    inlines = [SchemeComponentInline]


@admin.register(AssessmentItem, site=site)
class AssessmentItemAdmin(admin.ModelAdmin):
    list_display = ("title", "class_offering", "component", "term", "max_score", "order")
    list_filter = ("term", "class_offering")
    search_fields = ("title", "class_offering__subject__code")


@admin.register(Score, site=site)
class ScoreAdmin(admin.ModelAdmin):
    list_display = ("roster_entry", "item", "score", "updated_by", "updated_at")
    list_filter = ("item__class_offering", "item__term")
    search_fields = ("roster_entry__student__username", "roster_entry__student__last_name")


@admin.register(ScoreChangeLog, site=site)
class ScoreChangeLogAdmin(admin.ModelAdmin):
    list_display = ("score", "old_value", "new_value", "changed_by", "changed_at")
    list_filter = ("changed_at",)
    search_fields = ("score__roster_entry__student__username",)
