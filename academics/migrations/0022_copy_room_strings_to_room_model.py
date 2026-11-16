"""Copies each distinct, non-blank ClassOffering.room string into a Room
row (case-insensitive dedup — "Room 101" and "room 101" become one Room),
and points every ClassOffering at it via the new room_new FK, before 0023
removes the old string field and renames room_new -> room."""

from django.db import migrations


def copy_forward(apps, schema_editor):
    ClassOffering = apps.get_model("academics", "ClassOffering")
    Room = apps.get_model("academics", "Room")

    rooms_by_lower_name = {}
    for class_offering in ClassOffering.objects.exclude(room="").only("id", "room"):
        raw_name = class_offering.room.strip()
        if not raw_name:
            continue
        key = raw_name.lower()
        room = rooms_by_lower_name.get(key)
        if room is None:
            room, _ = Room.objects.get_or_create(name__iexact=raw_name, defaults={"name": raw_name})
            rooms_by_lower_name[key] = room
        class_offering.room_new_id = room.id
        class_offering.save(update_fields=["room_new"])


def copy_backward(apps, schema_editor):
    # Irreversible by design -- the old string field is removed in the
    # very next migration, so there's nothing meaningful to reverse into.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0021_add_room"),
    ]

    operations = [
        migrations.RunPython(copy_forward, copy_backward),
    ]
