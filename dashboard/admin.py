from django.contrib import admin

from config.admin import site

from .models import Notification


@admin.register(Notification, site=site)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "recipient", "is_read", "created_at")
    list_filter = ("is_read",)
    search_fields = ("title", "recipient__username")
