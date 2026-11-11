from django.db import migrations


def backfill_snapshot(apps, schema_editor):
    ClassOffering = apps.get_model("academics", "ClassOffering")
    for offering in ClassOffering.objects.select_related("subject").filter(subject_code_snapshot=""):
        offering.subject_code_snapshot = offering.subject.code
        offering.subject_title_snapshot = offering.subject.title
        offering.subject_units_snapshot = offering.subject.units
        offering.save(update_fields=["subject_code_snapshot", "subject_title_snapshot", "subject_units_snapshot"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0013_backfill_semester_status"),
    ]

    operations = [
        migrations.RunPython(backfill_snapshot, noop),
    ]
