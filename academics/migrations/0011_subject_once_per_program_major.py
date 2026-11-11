"""Tightens CurriculumEntry's uniqueness from "one per year-level/term
slot" to "one per program/major, period" (a subject can only sit once
in a given program/major's curriculum — the Add Subject modal's
duplicate checks rely on this). Two conditional unique constraints, not
one plain (program, major, subject) constraint: SQL never treats two
NULLs as equal in a unique index, so a plain constraint would silently
fail to catch a TCP-style duplicate (major is always NULL there).

A defensive data pass runs first: if any (program, major, subject)
combination somehow already has more than one CurriculumEntry (expected
to be none in practice — nothing built so far could create one), keep
only the earliest and delete the rest, logging what got removed, so the
new constraint can never fail to apply because of pre-existing data.
"""

from django.db import migrations, models


def dedupe_curriculum_entries(apps, schema_editor):
    CurriculumEntry = apps.get_model("academics", "CurriculumEntry")
    seen = {}
    removed = []
    for entry in CurriculumEntry.objects.order_by("id"):
        key = (entry.program_id, entry.major_id, entry.subject_id)
        if key in seen:
            removed.append((entry.id, key))
            entry.delete()
        else:
            seen[key] = entry.id
    if removed:
        print(f"  Removed {len(removed)} duplicate CurriculumEntry row(s) ahead of the new constraint: {removed}")


def noop_reverse(apps, schema_editor):
    """Nothing to reverse -- the removed duplicates (if any) are gone for good."""


class Migration(migrations.Migration):

    dependencies = [
        ('academics', '0010_remove_subject_placement_fields'),
    ]

    operations = [
        migrations.RunPython(dedupe_curriculum_entries, noop_reverse),
        migrations.RemoveConstraint(
            model_name='curriculumentry',
            name='unique_curriculum_slot',
        ),
        migrations.AddConstraint(
            model_name='curriculumentry',
            constraint=models.UniqueConstraint(
                condition=models.Q(('major__isnull', False)),
                fields=('program', 'major', 'subject'),
                name='unique_subject_per_program_major',
            ),
        ),
        migrations.AddConstraint(
            model_name='curriculumentry',
            constraint=models.UniqueConstraint(
                condition=models.Q(('major__isnull', True)),
                fields=('program', 'subject'),
                name='unique_subject_per_program_no_major',
            ),
        ),
        migrations.AlterField(
            model_name='academicsetupchangelog',
            name='action',
            field=models.CharField(choices=[('CREATED', 'Created'), ('UPDATED', 'Updated'), ('DEACTIVATED', 'Deactivated'), ('REACTIVATED', 'Reactivated'), ('SECTION_JOINED', 'Section joined'), ('SECTION_LEFT', 'Section left'), ('ADDED_TO_CURRICULUM', 'Added to curriculum'), ('REMOVED_FROM_CURRICULUM', 'Removed from curriculum'), ('CODE_CORRECTED', 'Code corrected')], max_length=25),
        ),
    ]
