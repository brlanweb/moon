from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('monitor', '0003_alter_detection_type'),
    ]

    operations = [
        migrations.AlterField(
            model_name='detection',
            name='type',
            field=models.CharField(choices=[
                ('1', '\u7ad9\u70b9\u68c0\u6d4b'),
                ('2', '\u7aef\u53e3\u68c0\u6d4b'),
                ('3', '\u8fdb\u7a0b\u68c0\u6d4b'),
                ('4', '\u81ea\u5b9a\u4e49\u811a\u672c'),
                ('5', 'Ping\u68c0\u6d4b'),
                ('6', 'Docker\u670d\u52a1\u68c0\u6d4b'),
                ('7', '\u8d44\u6e90\u76d1\u63a7'),
            ], max_length=2),
        ),
    ]
