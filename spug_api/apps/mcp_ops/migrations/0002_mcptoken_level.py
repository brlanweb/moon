from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('mcp_ops', '0001_initial'),
    ]
    operations = [
        migrations.AddField(
            model_name='mcptoken',
            name='level',
            field=models.CharField(choices=[('normal', '普通'), ('super', '超管')], default='normal', max_length=10),
        ),
    ]
