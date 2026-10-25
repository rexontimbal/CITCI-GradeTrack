from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = (
        "username",
        "full_name",
        "role",
        "id_number",
        "is_active",
        "must_change_password",
    )
    list_filter = ("role", "is_active", "must_change_password")
    search_fields = ("username", "first_name", "last_name", "id_number", "email")
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "CITCI GradeTrack",
            {"fields": ("role", "middle_name", "id_number", "must_change_password")},
        ),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        (
            "CITCI GradeTrack",
            {"fields": ("role", "middle_name", "id_number", "must_change_password")},
        ),
    )
