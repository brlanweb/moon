from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('deploy', '0001_initial'),
    ]

    operations = [
        migrations.RenameField(
            model_name='deployrequest',
            old_name='spug_version',
            new_name='moon_version',
        ),
    ]
