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
    update_token,
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
        token, plaintext = create_token(self.user, 'CI', 1)
        self.assertTrue(plaintext.startswith('moon_'))
        self.assertEqual(token.token_digest, hashlib.sha256(plaintext.encode()).hexdigest())
        self.assertNotIn(plaintext, json.dumps(token.to_view()))
        self.assertLessEqual(token.expires_at, token.created_at + timedelta(days=1, seconds=1))

    def test_duration_is_limited_to_fixed_choices(self):
        for days in (0, 2, 31, 90, 181, 366, 730):
            with self.subTest(days=days), self.assertRaises(ValueError):
                create_token(self.user, 'invalid', days)

    def test_six_month_and_one_year_lifetimes_are_accepted(self):
        for days in (180, 365):
            with self.subTest(days=days):
                token, _ = create_token(self.user, f'long-{days}', days)
                delta = token.expires_at - token.created_at
                self.assertGreaterEqual(delta, timedelta(days=days) - timedelta(seconds=1))
                self.assertLessEqual(delta, timedelta(days=days, seconds=1))

    def test_expiry_boundary_revocation_regeneration_and_disabled_user_reject(self):
        token, plaintext = create_token(self.user, 'CI', 7)
        token.expires_at = timezone.now()
        token.save(update_fields=['expires_at'])
        with self.assertRaises(AuthorizationError):
            authenticate_token(plaintext, '127.0.0.1')
        self.assertEqual(McpAuditLog.objects.filter(status='rejected', failure_reason='令牌已过期').count(), 1)

        token.expires_at = timezone.now() + timedelta(days=7)
        token.save(update_fields=['expires_at'])
        refreshed, new_plaintext = regenerate_token(token, self.user, 30)
        token.refresh_from_db()
        self.assertEqual(refreshed.id, token.id)
        self.assertIsNone(token.revoked_at)
        with self.assertRaises(AuthorizationError):
            authenticate_token(plaintext, '127.0.0.1')
        self.assertEqual(authenticate_token(new_plaintext, '127.0.0.1').id, token.id)

        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        with self.assertRaises(AuthorizationError):
            authenticate_token(new_plaintext, '127.0.0.1')

    def test_all_registered_hosts_are_listed_including_hosts_added_later(self):
        token, _ = create_token(self.user, 'CI', 1)
        self.assertEqual([item['id'] for item in list_authorized_hosts(token)],
                         [self.allowed.id, self.denied.id])
        later = Host.objects.create(
            name='later', hostname='192.0.2.12', port=22, username='root',
            is_verified=True, created_by=self.user)
        self.assertIn(later.id, [item['id'] for item in list_authorized_hosts(token)])

    @patch('apps.mcp_ops.service._run_ssh')
    def test_execute_rejects_unregistered_dangerous_and_limits_output(self, run_ssh):
        token, _ = create_token(self.user, 'CI', 1)
        with self.assertRaisesRegex(AuthorizationError, '主机未登记'):
            execute_script(token, 999999, 'uptime', '127.0.0.1')
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
        token, _ = create_token(self.user, 'CI', 1)
        from apps.mcp_ops.service import check_connection
        self.assertEqual(check_connection(token, self.allowed.id, '127.0.0.1'), {
            'host_id': self.allowed.id, 'connected': True})
        self.assertEqual(McpAuditLog.objects.get().operation, 'check_connection')

    def test_expired_token_can_be_regenerated_for_same_owner(self):
        token, old_plaintext = create_token(self.user, 'expired', 1)
        token.expires_at = timezone.now() - timedelta(seconds=1)
        token.save(update_fields=['expires_at'])
        refreshed, plaintext = regenerate_token(token, self.user, 1)
        token.refresh_from_db()
        self.assertEqual(refreshed.id, token.id)
        self.assertEqual(refreshed.user_id, self.user.id)
        self.assertIsNone(token.revoked_at)
        self.assertGreater(token.expires_at, timezone.now())
        with self.assertRaises(AuthorizationError):
            authenticate_token(old_plaintext)
        self.assertEqual(authenticate_token(plaintext).id, token.id)

    def test_deleted_token_is_removed_and_rejected_immediately(self):
        from apps.mcp_ops.models import McpToken
        from apps.mcp_ops.service import delete_token
        token, plaintext = create_token(self.user, 'CI', 1)
        authenticate_token(plaintext)
        delete_token(token, self.user)
        self.assertFalse(McpToken.objects.filter(pk=token.pk).exists())
        with self.assertRaisesRegex(AuthorizationError, '无效令牌'):
            authenticate_token(plaintext)
        # Audit history survives the deletion with the token reference cleared.
        self.assertTrue(McpAuditLog.objects.filter(token__isnull=True).exists())

    def test_lost_use_permission_is_immediate(self):
        token, plaintext = create_token(self.user, 'CI', 1)
        self.user.roles.all().update(page_perms={})
        self.user.set_perms_cache()
        with self.assertRaisesRegex(AuthorizationError, '不再具有'):
            authenticate_token(plaintext)
        with self.assertRaisesRegex(AuthorizationError, '不再具有'):
            execute_script(token, self.allowed.id, 'uptime')

    @patch('apps.mcp_ops.service._run_ssh')
    def test_token_plaintext_is_redacted_from_script_output_and_failure(self, run_ssh):
        token, plaintext = create_token(self.user, 'CI', 1)
        run_ssh.return_value = (2, f'failed with {plaintext}')
        result = execute_script(token, self.allowed.id, f'echo {plaintext}', sensitive_values=(plaintext,))
        self.assertEqual(result['status'], 'failed')
        log = McpAuditLog.objects.get()
        self.assertNotIn(plaintext, log.script + log.output + (log.failure_reason or ''))
        self.assertIn('[REDACTED]', log.script + log.output)

    def test_timeout_and_concurrency_rejections_are_audited(self):
        token, _ = create_token(self.user, 'CI', 1)
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


class McpTokenLevelTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create(
            username='root-admin', nickname='Admin', password_hash='x', type='default',
            is_active=True, is_deleted=False, is_supper=True, access_token='a' * 32,
            token_expired=9999999999, last_login='', last_ip='')
        self.user = User.objects.create(
            username='plain', nickname='Plain', password_hash='x', type='default',
            is_active=True, is_deleted=False, access_token='p' * 32,
            token_expired=9999999999, last_login='', last_ip='')
        role = Role.objects.create(name='mcp', page_perms={
            'system': {'mcp': ['view', 'add', 'edit', 'del', 'use']}}, group_perms=[])
        self.user.roles.add(role)
        self.host = Host.objects.create(
            name='h', hostname='192.0.2.20', port=22, username='root',
            is_verified=True, created_by=self.admin)

    def test_default_level_is_normal(self):
        token, _ = create_token(self.user, 'n', 1)
        self.assertEqual(token.level, 'normal')
        self.assertEqual(token.to_view()['level'], 'normal')

    @patch('apps.mcp_ops.service._run_ssh', return_value=(0, 'ok'))
    def test_super_key_skips_risk_check_but_normal_key_is_blocked(self, run_ssh):
        normal, _ = create_token(self.admin, 'n', 1)
        with self.assertRaises(AuthorizationError):
            execute_script(normal, self.host.id, 'rm -rf /', '127.0.0.1')
        run_ssh.assert_not_called()
        sup, _ = create_token(self.admin, 's', 1, 'super')
        self.assertEqual(execute_script(sup, self.host.id, 'rm -rf /tmp/x', '127.0.0.1')['exit_code'], 0)
        run_ssh.assert_called_once()

    @patch('apps.mcp_ops.service._run_ssh', return_value=(0, 'ok'))
    def test_super_key_loses_privilege_when_owner_is_demoted(self, run_ssh):
        sup, _ = create_token(self.admin, 's', 1, 'super')
        self.admin.is_supper = False
        self.admin.save(update_fields=['is_supper'])
        sup.user.refresh_from_db()
        with self.assertRaises(AuthorizationError):
            execute_script(sup, self.host.id, 'rm -rf /', '127.0.0.1')

    def test_non_super_admin_cannot_grant_super_level(self):
        with self.assertRaisesRegex(AuthorizationError, '超级管理员'):
            create_token(self.user, 's', 1, 'super')
        token, _ = create_token(self.user, 'n', 1)
        with self.assertRaisesRegex(AuthorizationError, '超级管理员'):
            update_token(token, self.user, 'n', 'super')
        with self.assertRaises(ValueError):
            create_token(self.admin, 'x', 1, 'root')

    def test_super_admin_can_edit_level_in_place(self):
        token, plaintext = create_token(self.user, 'n', 1)
        updated = update_token(token, self.admin, 'renamed', 'super')
        self.assertEqual((updated.id, updated.name, updated.level), (token.id, 'renamed', 'super'))
        self.assertEqual(authenticate_token(plaintext, '127.0.0.1').id, token.id)

    def test_patch_api_respects_ownership_and_level(self):
        from apps.mcp_ops.views import TokenView
        factory = RequestFactory()
        mine, _ = create_token(self.admin, 'admin-owned', 1)

        def patch_as(user, body):
            request = factory.patch('/mcp-admin/tokens/', data=json.dumps(body), content_type='application/json')
            request.user = user
            return TokenView.as_view()(request).content.decode()

        self.assertIn('令牌不存在', patch_as(self.user, {'id': mine.id, 'name': 'x', 'level': 'normal'}))
        own, _ = create_token(self.user, 'own', 1)
        self.assertIn('超级管理员', patch_as(self.user, {'id': own.id, 'name': 'x', 'level': 'super'}))
        self.assertIn('"level": "super"', patch_as(self.admin, {'id': own.id, 'name': 'x', 'level': 'super'}))

    def test_super_key_bypasses_file_whitelist_only(self):
        from apps.mcp_ops.files import normalize_path
        with self.assertRaises(AuthorizationError):
            normalize_path('/etc/nginx/nginx.conf')
        self.assertEqual(normalize_path('/etc/nginx/nginx.conf', True), '/etc/nginx/nginx.conf')
        for bad in ('etc/passwd', '/tmp/../etc/passwd', '/etc/'):
            with self.subTest(bad=bad), self.assertRaises(AuthorizationError):
                normalize_path(bad, True)


class OfficialSdkRegistrationTests(TestCase):
    def test_official_client_discovers_all_operation_tools(self):
        from apps.mcp_ops.mcp_server import server

        async def verify():
            async with Client(server) as client:
                result = await client.list_tools()
                self.assertEqual(
                    {item.name for item in result.tools},
                    {'list_servers', 'check_connection', 'execute_script',
                     'create_upload_link', 'create_download_link'})

        anyio.run(verify)
