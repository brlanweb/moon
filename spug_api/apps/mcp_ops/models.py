from django.db import models
from django.utils import timezone

from apps.account.models import User
from apps.host.models import Host
from libs import ModelMixin


class McpToken(models.Model, ModelMixin):
    name = models.CharField(max_length=100)
    token_prefix = models.CharField(max_length=20)
    token_digest = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(User, models.PROTECT, related_name='mcp_tokens')
    hosts = models.ManyToManyField(Host, related_name='+', blank=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True)
    last_used_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    replaced_by = models.ForeignKey('self', models.SET_NULL, null=True, related_name='+')

    @property
    def status(self):
        if self.revoked_at:
            return 'revoked'
        if self.expires_at <= timezone.now():
            return 'expired'
        return 'active'

    def to_view(self):
        return {
            'id': self.id, 'name': self.name, 'token_prefix': self.token_prefix,
            'user_id': self.user_id, 'username': self.user.username,
            'host_ids': list(self.hosts.values_list('id', flat=True)),
            'expires_at': self.expires_at.isoformat(),
            'revoked_at': self.revoked_at.isoformat() if self.revoked_at else None,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
            'created_at': self.created_at.isoformat(),
            'status': self.status,
        }

    class Meta:
        db_table = 'mcp_tokens'
        ordering = ('-id',)


class McpAuditLog(models.Model, ModelMixin):
    token = models.ForeignKey(McpToken, models.SET_NULL, null=True, related_name='audit_logs')
    operator = models.ForeignKey(User, models.SET_NULL, null=True, related_name='+')
    operation = models.CharField(max_length=40)
    ip = models.CharField(max_length=50, null=True)
    host = models.ForeignKey(Host, models.SET_NULL, null=True, related_name='+')
    host_name = models.CharField(max_length=100, null=True)
    script = models.TextField(null=True)
    status = models.CharField(max_length=20)
    exit_code = models.IntegerField(null=True)
    output = models.TextField(null=True)
    duration_ms = models.IntegerField(default=0)
    failure_reason = models.CharField(max_length=255, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def to_view(self):
        return {
            'id': self.id, 'token_id': self.token_id,
            'operator': self.operator.username if self.operator else None,
            'operation': self.operation, 'ip': self.ip, 'host_id': self.host_id,
            'host_name': self.host_name, 'script': self.script, 'status': self.status,
            'exit_code': self.exit_code, 'output': self.output,
            'duration_ms': self.duration_ms, 'failure_reason': self.failure_reason,
            'created_at': self.created_at.isoformat(),
        }

    class Meta:
        db_table = 'mcp_audit_logs'
        ordering = ('-id',)
        indexes = [models.Index(fields=['created_at'], name='mcp_audit_created_idx')]
