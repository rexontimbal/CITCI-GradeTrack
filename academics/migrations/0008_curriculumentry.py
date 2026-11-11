import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('academics', '0007_major_program_head_change_log'),
    ]

    operations = [
        migrations.AlterField(
            model_name='academicsetupchangelog',
            name='action',
            field=models.CharField(choices=[('CREATED', 'Created'), ('UPDATED', 'Updated'), ('DEACTIVATED', 'Deactivated'), ('REACTIVATED', 'Reactivated'), ('SECTION_JOINED', 'Section joined'), ('SECTION_LEFT', 'Section left'), ('ADDED_TO_CURRICULUM', 'Added to curriculum'), ('REMOVED_FROM_CURRICULUM', 'Removed from curriculum')], max_length=25),
        ),
        migrations.CreateModel(
            name='CurriculumEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('year_level', models.PositiveSmallIntegerField(blank=True, choices=[(1, '1st Year'), (2, '2nd Year'), (3, '3rd Year'), (4, '4th Year')], null=True)),
                ('term', models.CharField(choices=[('FIRST', '1st Sem'), ('SECOND', '2nd Sem'), ('SUMMER', 'Summer')], max_length=10)),
                ('major', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='curriculum_entries', to='academics.major')),
                ('program', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='curriculum_entries', to='academics.program')),
                ('subject', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='curriculum_entries', to='academics.subject')),
            ],
            options={
                'ordering': ['program__code', 'major__code', 'year_level', 'term'],
            },
        ),
        migrations.AddConstraint(
            model_name='curriculumentry',
            constraint=models.UniqueConstraint(fields=('program', 'major', 'year_level', 'term', 'subject'), name='unique_curriculum_slot'),
        ),
    ]
