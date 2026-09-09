from django.db import migrations


def remove_retired_directory_config(apps, schema_editor):
    settings = apps.get_model('setting', 'Setting')
    settings.objects.using(schema_editor.connection.alias).filter(key='ldap_service').delete()


class Migration(migrations.Migration):
    dependencies = [('setting', '0001_initial')]

    # Bind credentials cannot be reconstructed. Back up before applying.
    operations = [migrations.RunPython(remove_retired_directory_config)]
