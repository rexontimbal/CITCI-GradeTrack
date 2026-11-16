# Final step of the three-migration move: drop the old CharField, then
# rename room_new -> room so the live column lands on the name models.py
# actually declares.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('academics', '0022_copy_room_strings_to_room_model'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='classoffering',
            name='room',
        ),
        migrations.RenameField(
            model_name='classoffering',
            old_name='room_new',
            new_name='room',
        ),
    ]
