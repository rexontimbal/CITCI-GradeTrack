from django.urls import path

from . import views

app_name = "forecasting"

urlpatterns = [
    path("model/", views.model, name="model"),
    path("at-risk/", views.at_risk, name="at_risk"),
]
