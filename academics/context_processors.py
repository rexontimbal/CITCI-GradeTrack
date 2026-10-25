from .models import Semester


def active_semester(request):
    if not request.user.is_authenticated:
        return {}
    return {"active_semester": Semester.objects.filter(is_active=True).select_related("academic_year").first()}
