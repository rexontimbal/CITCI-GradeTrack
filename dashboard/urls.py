from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("notifications/", views.notifications, name="notifications"),
    path("notifications/bell/", views.bell, name="bell"),
    path("notifications/<int:pk>/mark-read/", views.mark_read, name="mark_read"),
    path("notifications/mark-all-read/", views.mark_all_read, name="mark_all_read"),
    path("notifications/mark-all-read/page/", views.notifications_mark_all_read, name="notifications_mark_all_read"),
]
