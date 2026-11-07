from django.contrib import admin

from config.admin import site

from .models import InstitutionSettings


@admin.register(InstitutionSettings, site=site)
class InstitutionSettingsAdmin(admin.ModelAdmin):
    list_display = ("school_name", "dean_name", "academic_head_name")

    def has_add_permission(self, request):
        return not InstitutionSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
