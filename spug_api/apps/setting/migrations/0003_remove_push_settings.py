# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.db import migrations


def remove_push_settings(apps, schema_editor):
    # Preserve an enabled legacy MFA policy: removing its transport must not silently weaken login.
    setting = apps.get_model('setting', 'Setting')
    setting.objects.using(schema_editor.connection.alias).filter(
        key__in=['spug_push_key']).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('setting', '0002_remove_ldap_service'),
        ('account', '0003_remove_user_wx_token'),
        ('alarm', '0002_remove_contact_wx_token'),
    ]

    operations = [
        migrations.RunPython(remove_push_settings),
    ]
