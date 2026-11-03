"""Data fix, no audit noise: some GradeSheetEntry rows were frozen with a
provisional ON_TRACK/AT_RISK label (from grading.services' mid-term
`remarks` property) instead of a FINAL PASSED/FAILED one — the root cause
(approvals.services.submit_grade_sheet) is fixed separately in code. This
recomputes those rows' `remarks` from their already-stored `final_grade`,
leaving INC/DROPPED/PASSED/FAILED rows untouched. Deliberately not logged
to GradeSheetTransition/GradeCorrection — this is a system data fix, not a
grade correction a human made.
"""

from decimal import Decimal

from django.db import migrations

PASSING_THRESHOLD = Decimal("3.00")
PROVISIONAL_LABELS = ("ON_TRACK", "AT_RISK")


def fix_provisional_remarks(apps, schema_editor):
    GradeSheetEntry = apps.get_model("approvals", "GradeSheetEntry")
    affected = GradeSheetEntry.objects.filter(remarks__in=PROVISIONAL_LABELS)
    for entry in affected:
        if entry.final_grade is None:
            entry.remarks = "FAILED"
        else:
            entry.remarks = "PASSED" if entry.final_grade <= PASSING_THRESHOLD else "FAILED"
        entry.save(update_fields=["remarks"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(fix_provisional_remarks, noop_reverse),
    ]
