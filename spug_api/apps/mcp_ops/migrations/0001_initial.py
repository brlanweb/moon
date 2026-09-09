# Generated for Moon MCP operation service.
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ('account', '0003_remove_user_wx_token'),
        ('host', '0001_initial'),
    ]
    operations = [
        migrations.CreateModel(
            name='McpToken',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('token_prefix', models.CharField(max_length=20)),
                ('token_digest', models.CharField(max_length=64, unique=True)),
                ('expires_at', models.DateTimeField()),
                ('revoked_at', models.DateTimeField(null=True)),
                ('last_used_at', models.DateTimeField(null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='account.user')),
                ('hosts', models.ManyToManyField(blank=True, related_name='+', to='host.host')),
                ('replaced_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='mcp_ops.mcptoken')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='mcp_tokens', to='account.user')),
            ],
            options={'db_table': 'mcp_tokens', 'ordering': ('-id',)},
        ),
        migrations.CreateModel(
            name='McpAuditLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('operation', models.CharField(max_length=40)),
                ('ip', models.CharField(max_length=50, null=True)),
                ('host_name', models.CharField(max_length=100, null=True)),
                ('script', models.TextField(null=True)),
                ('status', models.CharField(max_length=20)),
                ('exit_code', models.IntegerField(null=True)),
                ('output', models.TextField(null=True)),
                ('duration_ms', models.IntegerField(default=0)),
                ('failure_reason', models.CharField(max_length=255, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('host', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='host.host')),
                ('operator', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='account.user')),
                ('token', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='audit_logs', to='mcp_ops.mcptoken')),
            ],
            options={'db_table': 'mcp_audit_logs', 'ordering': ('-id',)},
        ),
        migrations.AddIndex(
            model_name='mcpauditlog',
            index=models.Index(fields=['created_at'], name='mcp_audit_created_idx'),
        ),
    ]
