from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('alarm', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(model_name='contact', name='wx_token'),
    ]
