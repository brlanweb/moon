import hashlib
import json
from datetime import timedelta
from unittest.mock import patch

import anyio
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.account.models import Role, User
from apps.host.models import Group, Host
from apps.mcp_ops.models import McpAuditLog
from apps.mcp_ops.mcp_server import _request_ip
from apps.mcp_ops.service import (
    AuthorizationError,
    OperationError,
    authenticate_token,
    create_token,
    execute_script,
    list_authorized_hosts,
    regenerate_token,
)
from mcp import Client


class McpOperationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            username='operator', nickname='Operator', password_hash='x', type='default',
            is_active=True, is_deleted=False, access_token='x' * 32,
            token_expired=9999999999, last_login='', last_ip='127.0.0.1')
        role = Role.objects.create(name='ops', page_perms={
            'system': {'mcp': ['view', 'add', 'edit', 'del', 'use']}
        }, group_perms=[])
        self.user.roles.add(role)
        self.allowed = Host.objects.create(
            name='allowed', hostname='192.0.2.10', port=22, username='root',
            is_verified=True, created_by=self.user)
        self.denied = Host.objects.create(
            name='denied', hostname='192.0.2.11', port=22, username='root',
            is_verified=True, created_by=self.user)
        group = Group.objects.create(name='allowed-group')
        group.hosts.add(self.allowed)
        role.group_perms = [group.id]
        role.save(update_fields=['group_perms'])

    def test_create_only_returns_plaintext_once_and_stores_digest(self):
        token, plaintext = create_token(self.user, 'CI', 1, [self.allowed.id])
        self.assertTrue(plaintext.startswith('moon_'))
        self.assertEqual(token.token_digest, hashlib.sha256(plaintext.encode()).hexdigest())
        self.assertNotIn(plaintext, json.dumps(token.to_view()))
        self.assertLessEqual(token.expires_at, token.created_at + timedelta(days=1, seconds=1))

    def test_duration_is_limited_to_fixed_choices_and_thirty_days(self):
        for days in (0, 2, 31):
            with self.subTest(days=days), self.assertRaises(ValueError):
                create_token(self.user, 'invalid', days, [self.allowed.id])

    def test_expiry_boundary_revocation_regeneration_and_disabled_user_reject(self):
        token, plaintext = create_token(self.user, 'CI', 7, [self.allowed.id])
        token.expires_at = timezone.now()
        token.save(update_fields=['expires_at'])
        with self.assertRaises(AuthorizationError):
            authenticate_token(plaintext, '127.0.0.1')
        self.assertEqual(McpAuditLog.objects.filter(status='rejected', failure_reason='令牌已过期').count(), 1)

        token.expires_at = timezone.now() + timedelta(days=7)
        token.save(update_fields=['expires_at'])
        replacement, new_plaintext = regenerate_token(token, self.user, 30)
        token.refresh_from_db()
        self.assertIsNotNone(token.revoked_at)
        with self.assertRaises(AuthorizationError):
            authenticate_token(plaintext, '127.0.0.1')
        self.assertEqual(authenticate_token(new_plaintext, '127.0.0.1').id, replacement.id)

        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        with self.assertRaises(AuthorizationError):
            authenticate_token(new_plaintext, '127.0.0.1')

    def test_only_currently_permitted_and_token_authorized_hosts_are_listed(self):
        token, _ = create_token(self.user, 'CI', 1, [self.allowed.id])
        token.hosts.add(self.denied)
        hosts = list_authorized_hosts(token)
        self.assertEqual([item['id'] for item in hosts], [self.allowed.id])

    @patch('apps.mcp_ops.service._run_ssh')
    def test_execute_rejects_unregistered_dangerous_and_limits_output(self, run_ssh):
        token, _ = create_token(self.user, 'CI', 1, [self.allowed.id])
        with self.assertRaises(AuthorizationError):
            execute_script(token, self.denied.id, 'uptime', '127.0.0.1')
        with self.assertRaises(AuthorizationError):
            execute_script(token, self.allowed.id, 'rm -rf /', '127.0.0.1')
        run_ssh.return_value = (0, 'x' * 70000)
        result = execute_script(token, self.allowed.id, 'printf ok', '127.0.0.1')
        self.assertLessEqual(len(result['output'].encode()), 65536)
        self.assertTrue(result['truncated'])
        logs = McpAuditLog.objects.order_by('id')
        self.assertEqual([item.status for item in logs], ['rejected', 'rejected', 'success'])
        self.assertNotIn('rm -rf /', logs[1].script)
        self.assertNotIn(token.token_digest, json.dumps([item.to_view() for item in logs]))

    @patch('apps.mcp_ops.service.Host.get_ssh')
    def test_connection_check_uses_registered_host_ssh(self, get_ssh):
        get_ssh.return_value.ping.return_value = True
        token, _ = create_token(self.user, 'CI', 1, [self.allowed.id])
        from apps.mcp_ops.service import check_connection
        self.assertEqual(check_connection(token, self.allowed.id, '127.0.0.1'), {
            'host_id': self.allowed.id, 'connected': True})
        self.assertEqual(McpAuditLog.objects.get().operation, 'check_connection')

    def test_expired_token_can_be_regenerated_for_same_owner(self):
        token, old_plaintext = create_token(self.user, 'expired', 1, [self.allowed.id])
        token.expires_at = timezone.now() - timedelta(seconds=1)
        token.save(update_fields=['expires_at'])
        replacement, plaintext = regenerate_token(token, self.user, 1)
        token.refresh_from_db()
        self.assertEqual(replacement.user_id, self.user.id)
        self.assertIsNotNone(token.revoked_at)
        with self.assertRaises(AuthorizationError):
            authenticate_token(old_plaintext)
        self.assertEqual(authenticate_token(plaintext).id, replacement.id)

    def test_lost_role_and_lost_host_permission_are_immediate(self):
        token, plaintext = create_token(self.user, 'CI', 1, [self.allowed.id])
        self.user.roles.all().update(page_perms={})
        self.user.set_perms_cache()
        with self.assertRaisesRegex(AuthorizationError, '不再具有'):
            authenticate_token(plaintext)
        role = self.user.roles.first()
        role.page_perms = {'system': {'mcp': ['use']}}
        role.group_perms = []
        role.save()
        self.user.set_perms_cache()
        with self.assertRaisesRegex(AuthorizationError, '未登记、未授权'):
            execute_script(token, self.allowed.id, 'uptime')

    @patch('apps.mcp_ops.service._run_ssh')
    def test_token_plaintext_is_redacted_from_script_output_and_failure(self, run_ssh):
        token, plaintext = create_token(self.user, 'CI', 1, [self.allowed.id])
        run_ssh.return_value = (2, f'failed with {plaintext}')
        result = execute_script(token, self.allowed.id, f'echo {plaintext}', sensitive_values=(plaintext,))
        self.assertEqual(result['status'], 'failed')
        log = McpAuditLog.objects.get()
        self.assertNotIn(plaintext, log.script + log.output + (log.failure_reason or ''))
        self.assertIn('[REDACTED]', log.script + log.output)

    def test_timeout_and_concurrency_rejections_are_audited(self):
        token, _ = create_token(self.user, 'CI', 1, [self.allowed.id])
        with self.assertRaisesRegex(AuthorizationError, '1 到 300'):
            execute_script(token, self.allowed.id, 'uptime', timeout=301)
        with patch('apps.mcp_ops.service._SEMAPHORE.acquire', return_value=False):
            with self.assertRaisesRegex(OperationError, '并发'):
                execute_script(token, self.allowed.id, 'uptime')
        self.assertEqual(McpAuditLog.objects.filter(status='rejected').count(), 2)

    def test_request_ip_ignores_untrusted_x_forwarded_for(self):
        context = type('Context', (), {'headers': {
            'x-forwarded-for': '203.0.113.99', 'x-moon-client-ip': '198.51.100.8'
        }})()
        self.assertEqual(_request_ip(context), '198.51.100.8')

    def test_admin_api_enforces_permission_and_parameter_boundaries(self):
        from apps.mcp_ops.views import AuditView, TokenView
        factory = RequestFactory()
        request = factory.post('/mcp-admin/tokens/', data=json.dumps({
            'name': 'bad', 'days': 2, 'host_ids': [self.allowed.id]
        }), content_type='application/json')
        request.user = self.user
        response = TokenView.as_view()(request)
        self.assertIn('有效期只能', response.content.decode())

        other = User.objects.create(
            username='none', nickname='None', password_hash='x', type='default',
            is_active=True, is_deleted=False, access_token='y' * 32,
            token_expired=9999999999, last_login='', last_ip='')
        request = factory.get('/mcp-admin/logs/?page_size=101')
        request.user = other
        self.assertIn('权限拒绝', AuditView.as_view()(request).content.decode())


class OfficialSdkRegistrationTests(TestCase):
    def test_official_client_discovers_all_operation_tools(self):
        from apps.mcp_ops.mcp_server import server

        async def verify():
            async with Client(server) as client:
                result = await client.list_tools()
                self.assertEqual(
                    {item.name for item in result.tools},
                    {'list_servers', 'check_connection', 'execute_script'})

        anyio.run(verify)
