# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.

from django.db import migrations, models
import django.db.models.deletion
import libs.mixins
import libs.utils


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0001_initial'),
        ('ai', '0003_auto_20260830_2259'),
    ]

    operations = [
        migrations.AddField(
            model_name='agentsession',
            name='context_summary',
            field=models.TextField(null=True),
        ),
        migrations.AddField(
            model_name='agentsession',
            name='summary_record_id',
            field=models.IntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='agentrecord',
            name='kind',
            field=models.CharField(choices=[('context', '任务上下文'), ('question', '用户提问'), ('answer', 'AI回复'), ('thought', 'AI分析'), ('command', '执行命令'), ('confirm', '待确认命令'), ('output', '命令输出'), ('verify', '结果复检'), ('summary', '最终结论'), ('skill', '加载技能'), ('tool', 'MCP调用'), ('tool_result', 'MCP结果'), ('compress', '上下文压缩'), ('error', '异常')], max_length=20),
        ),
        migrations.CreateModel(
            name='McpServer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=64)),
                ('type', models.CharField(choices=[('docker', 'Docker'), ('http', 'HTTP')], max_length=10)),
                ('image', models.CharField(max_length=255, null=True)),
                ('command', models.CharField(max_length=255, null=True)),
                ('env', models.TextField(null=True)),
                ('url', models.CharField(max_length=255, null=True)),
                ('headers', models.TextField(null=True)),
                ('timeout', models.IntegerField(default=60)),
                ('tools_cache', models.TextField(null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('desc', models.CharField(max_length=255, null=True)),
                ('created_at', models.CharField(default=libs.utils.human_datetime, max_length=20)),
                ('updated_at', models.CharField(max_length=20, null=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='account.user')),
                ('updated_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='account.user')),
            ],
            options={
                'db_table': 'ai_mcp_servers',
                'ordering': ('-id',),
            },
            bases=(models.Model, libs.mixins.ModelMixin),
        ),
        migrations.CreateModel(
            name='Skill',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=64)),
                ('description', models.CharField(max_length=255)),
                ('content', models.TextField()),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.CharField(default=libs.utils.human_datetime, max_length=20)),
                ('updated_at', models.CharField(max_length=20, null=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='account.user')),
                ('updated_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='account.user')),
            ],
            options={
                'db_table': 'ai_skills',
                'ordering': ('-id',),
            },
            bases=(models.Model, libs.mixins.ModelMixin),
        ),
    ]
