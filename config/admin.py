"""Django Admin is now a superuser-only emergency/data-repair tool — the
sidebar never links to it (accounts/menu.py), and day-to-day work should
go through the app's own pages (which validate and write to the audit
log / per-domain change logs; Django Admin bypasses all of that). This
custom AdminSite enforces that server-side too, rather than relying on
the accident that UserForm.save() never sets is_staff for any role.

Every app's admin.py registers its models against this `site`, not the
default `django.contrib.admin.site` (via `@admin.register(Model,
site=site)`) — see CLAUDE.md section 11.
"""

from django.contrib import admin


class SuperuserOnlyAdminSite(admin.AdminSite):
    def has_permission(self, request):
        return bool(request.user.is_active and request.user.is_superuser)


site = SuperuserOnlyAdminSite(name="admin")
