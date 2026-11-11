from django.db import migrations
from django.utils import timezone


def backfill_status(apps, schema_editor):
    """The ACTIVE semester (is_active=True) becomes ACTIVE; everything
    else becomes CLOSED unless it clearly hasn't started/ended yet (no
    end_date, or an end_date in the future), in which case it's UPCOMING
    -- so a semester someone already set up ahead of time doesn't get
    locked read-only by this migration."""
    Semester = apps.get_model("academics", "Semester")
    today = timezone.localdate()
    for semester in Semester.objects.all():
        if semester.is_active:
            status = "ACTIVE"
        elif semester.end_date and semester.end_date >= today:
            status = "UPCOMING"
        elif not semester.end_date and semester.start_date and semester.start_date > today:
            status = "UPCOMING"
        else:
            status = "CLOSED"
        semester.status = status
        semester.save(update_fields=["status"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0012_offering_models"),
    ]

    operations = [
        migrations.RunPython(backfill_status, noop),
    ]
