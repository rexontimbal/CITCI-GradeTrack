from django.urls import path

from . import views

app_name = "academics"

urlpatterns = [
    path("terms/", views.terms, name="terms"),
    path("programs/", views.programs, name="programs"),
    path("sections/", views.sections, name="sections"),
    path("subjects/", views.subjects, name="subjects"),
    path("classes/", views.classes, name="classes"),
    path("my-classes/", views.my_classes, name="my_classes"),
    path("enrollment/", views.enrollment, name="enrollment"),
]
