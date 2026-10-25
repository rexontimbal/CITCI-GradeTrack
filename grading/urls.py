from django.urls import path

from . import views

app_name = "grading"

urlpatterns = [
    path("templates/", views.templates, name="templates"),
    path("submitted/", views.submitted, name="submitted"),
    path("my-grades/", views.my_grades, name="my_grades"),
    path("my-progress/", views.my_progress, name="my_progress"),
]
