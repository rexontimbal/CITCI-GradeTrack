from django.urls import path

from . import views

app_name = "approvals"

urlpatterns = [
    # Instructor
    path("classes/<int:pk>/submit-review/", views.submit_review, name="submit_review"),
    path("classes/<int:pk>/submit/", views.submit, name="submit"),
    path("submitted/", views.submitted_sheets, name="submitted"),
    # Program Head
    path("", views.index, name="index"),
    path("release-all/", views.release_all, name="release_all"),
    # Shared review page (Program Head + Admin)
    path("sheets/<int:pk>/", views.review, name="review"),
    path("sheets/<int:pk>/approve/", views.approve, name="approve"),
    path("sheets/<int:pk>/return/", views.return_sheet, name="return_sheet"),
    path("sheets/<int:pk>/release/", views.release, name="release"),
    # INC completion — instructor files, Program Head decides
    path("inc-completions/", views.inc_completions_list, name="inc_completions_list"),
    path("inc-completions/<int:entry_pk>/file/", views.inc_completion_file, name="inc_completion_file"),
    path("inc-completions/<int:pk>/decide/", views.inc_completion_decide, name="inc_completion_decide"),
    # Admin
    path("admin/sheets/", views.admin_sheets, name="admin_sheets"),
    path("admin/lock-term/", views.admin_lock_term, name="admin_lock_term"),
    path("entries/<int:pk>/correct/", views.correct_entry, name="correct_entry"),
]
