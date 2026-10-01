from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('account', '0002_role_created_by'),
    ]

    operations = [
        migrations.RemoveField(model_name='user', name='wx_token'),
    ]
