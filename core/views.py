from django.db import connection
from django.db.utils import OperationalError
from django.http import JsonResponse


def healthz(request):
    """Health check for the server admin / a monitoring tool — pings the
    database with a trivial query and returns 200 if it answers, 503 if
    not. Deliberately unauthenticated (a monitoring tool shouldn't need
    credentials) and deliberately minimal (no personal data, no app
    internals beyond db:true/false)."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({"status": "ok", "db": True})
    except OperationalError:
        return JsonResponse({"status": "error", "db": False}, status=503)
