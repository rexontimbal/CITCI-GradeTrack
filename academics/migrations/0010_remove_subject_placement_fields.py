from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('academics', '0009_populate_curriculum_entries'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='subject',
            name='program',
        ),
        migrations.RemoveField(
            model_name='subject',
            name='major',
        ),
        migrations.RemoveField(
            model_name='subject',
            name='year_level',
        ),
        migrations.RemoveField(
            model_name='subject',
            name='term',
        ),
    ]
