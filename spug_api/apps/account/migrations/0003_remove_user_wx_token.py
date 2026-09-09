# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('account', '0002_role_created_by'),
    ]

    operations = [
        migrations.RemoveField(model_name='user', name='wx_token'),
    ]
