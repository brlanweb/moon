from django.db import migrations


def forwards(apps, schema_editor):
    Repository = apps.get_model('repository', 'Repository')
    Repository.objects.filter(remarks='SPUG AUTO MAKE').update(remarks='MOON AUTO MAKE')


def backwards(apps, schema_editor):
    Repository = apps.get_model('repository', 'Repository')
    Repository.objects.filter(remarks='MOON AUTO MAKE').update(remarks='SPUG AUTO MAKE')


class Migration(migrations.Migration):

    dependencies = [
        ('repository', '0001_initial'),
    ]

    operations = [
        migrations.RenameField(
            model_name='repository',
            old_name='spug_version',
            new_name='moon_version',
        ),
        migrations.RunPython(forwards, backwards),
    ]
