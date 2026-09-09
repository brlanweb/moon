# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('alarm', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(model_name='contact', name='wx_token'),
    ]
