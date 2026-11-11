"""Copies every existing Subject's program/major/year_level/term (still
present on the Subject model at this point in migration history — they're
only dropped in the next migration) into one CurriculumEntry row each.
Subjects with no program (shared/general subjects) get no entry, same as
the old model recorded no placement for them either. A Subject whose
`term` is the empty string (a latent bug in offerings_import's
auto-create path, which never passed a term) falls back to FIRST rather
than failing the CurriculumEntry.term NOT NULL/choices constraint —
logged so a real `migrate` run shows exactly which rows got defaulted."""

from django.db import migrations


def populate_curriculum_entries(apps, schema_editor):
    Subject = apps.get_model("academics", "Subject")
    CurriculumEntry = apps.get_model("academics", "CurriculumEntry")

    defaulted = []
    for subject in Subject.objects.filter(program_id__isnull=False):
        term = subject.term or "FIRST"
        if not subject.term:
            defaulted.append(subject.code)
        CurriculumEntry.objects.get_or_create(
            program_id=subject.program_id,
            major_id=subject.major_id,
            year_level=subject.year_level,
            term=term,
            subject_id=subject.id,
        )
    if defaulted:
        print(f"  Defaulted blank term to FIRST for: {', '.join(defaulted)}")


def noop_reverse(apps, schema_editor):
    """Nothing to reverse — the Subject placement fields this was copied
    from are removed by the next migration anyway, and this migration
    itself never deletes data on its way forward."""


class Migration(migrations.Migration):

    dependencies = [
        ('academics', '0008_curriculumentry'),
    ]

    operations = [
        migrations.RunPython(populate_curriculum_entries, noop_reverse),
    ]
