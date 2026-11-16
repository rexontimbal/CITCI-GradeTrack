# Hand-written: this step only ADDS the Room model and a new, temporary
# ClassOffering.room_new FK field. The existing ClassOffering.room CharField
# is copied into Room rows by 0022 (data migration) before 0023 removes the
# old field and renames room_new -> room — same "add the model, copy the
# data, remove the old field" three-step pattern already used for
# CurriculumEntry/SectionMembership (see CLAUDE.md).

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('academics', '0020_alter_classoffering_join_code_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='Room',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(max_length=50, unique=True)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.AddField(
            model_name='classoffering',
            name='room_new',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='class_offerings',
                to='academics.room',
            ),
        ),
    ]
