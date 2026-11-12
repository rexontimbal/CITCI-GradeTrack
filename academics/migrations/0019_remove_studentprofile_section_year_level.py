from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('academics', '0018_copy_student_section_to_membership'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='studentprofile',
            name='section',
        ),
        migrations.RemoveField(
            model_name='studentprofile',
            name='year_level',
        ),
    ]
