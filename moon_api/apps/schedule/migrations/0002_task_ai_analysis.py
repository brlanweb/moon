# Generated manually for task AI analysis.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('schedule', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='ai_analysis',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='history',
            name='ai_model',
            field=models.CharField(max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='history',
            name='ai_status',
            field=models.CharField(max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='history',
            name='ai_summary',
            field=models.TextField(null=True),
        ),
    ]
