"""Copies each StudentProfile's section/year_level into a SectionMembership
row before 0019 removes those fields. Year level itself is never copied
anywhere -- it's derived from the section now, per SectionMembership's own
design (see academics/models.py). Picks the semester to attach the
membership to as: the active semester whose academic year matches the
section's, else any semester with that academic year (earliest term
first), else the row is skipped (no semester to attach it to -- this only
happens for a section whose academic year has no semester at all, an
edge case no real seeded/demo data hits)."""

from django.db import migrations


def copy_forward(apps, schema_editor):
    StudentProfile = apps.get_model("academics", "StudentProfile")
    SectionMembership = apps.get_model("academics", "SectionMembership")
    Semester = apps.get_model("academics", "Semester")

    for profile in StudentProfile.objects.exclude(section__isnull=True).select_related("section"):
        section = profile.section
        semester = (
            Semester.objects.filter(academic_year=section.academic_year, is_active=True).first()
            or Semester.objects.filter(academic_year=section.academic_year).order_by("term").first()
        )
        if semester is None:
            continue
        SectionMembership.objects.get_or_create(
            student_id=profile.user_id, semester=semester, defaults={"section": section}
        )


def copy_backward(apps, schema_editor):
    # Irreversible by design -- StudentProfile.section/year_level are
    # removed in the very next migration, so there's nothing meaningful to
    # reverse this into.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0017_add_section_membership"),
    ]

    operations = [
        migrations.RunPython(copy_forward, copy_backward),
    ]
