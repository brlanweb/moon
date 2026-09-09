"""Independent security contracts. No real SSH, Redis, or persistent database.

Policy assumption: non-superusers manage their own tokens and may read only
currently permitted host logs; superusers may inspect all tokens/logs. A page
permission alone is not assumed to grant cross-host script visibility.
Run using apps.mcp_ops.test_settings. This file intentionally tests production
entry points; it never patches authorization, risk decisions, or audit writes.
"""
import hashlib
import json
import socket
import threading
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlencode

from asgiref.sync import async_to_sync
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.test import RequestFactory, TestCase

from apps.account.models import Role, User
from apps.account.views import RoleView, UserView
from apps.host.models import Group, Host
from apps.mcp_ops import service
from apps.mcp_ops.models import McpAuditLog, McpToken
from apps.mcp_ops.views import AuditView, RegenerateView, TokenView


def _require_isolation():
    databases = settings.DATABASES
    if set(databases) != {'default'}:
        raise RuntimeError('Security tests require exactly one isolated database')
    db = databases['default']
    name = str(db['NAME'])
    if db['ENGINE'] != 'django.db.backends.sqlite3' or not (
            name == ':memory:' or (name.startswith('file:memorydb_') and 'mode=memory' in name)):
        raise RuntimeError('Security tests refuse persistent or non-SQLite databases')
    if db.get('TEST', {}).get('NAME') != ':memory:':
        raise RuntimeError('Security tests require an explicit in-memory TEST database')
    if 'locmem' not in settings.CACHES['default']['BACKEND']:
        raise RuntimeError('Security tests refuse external caches')
    if 'InMemory' not in settings.CHANNEL_LAYERS['default']['BACKEND']:
        raise RuntimeError('Security tests refuse external channel layers')


_require_isolation()


class SecurityContractTests(TestCase):
    def setUp(self):
        _require_isolation()
        cache.clear()
        self.addCleanup(cache.clear)
        self.network = self.enterContext(patch.object(
            socket.socket, 'connect', side_effect=AssertionError('Real network forbidden')))
        self.ssh_factory = self.enterContext(patch.object(
            Host, 'get_ssh', side_effect=AssertionError('Unmocked SSH forbidden')))
        self.run_ssh = self.enterContext(patch.object(service, '_run_ssh', return_value=(0, 'ok')))
        self.factory = RequestFactory()
        self.user = self.make_user('contract-operator')
        self.admin = self.make_user('contract-admin', is_supper=True)
        self.other = self.make_user('contract-other')
        self.role = Role.objects.create(name='contract-role', page_perms={
            'system': {'mcp': ['view', 'add', 'edit', 'del', 'use']}}, group_perms=[])
        self.user.roles.add(self.role)
        self.allowed = Host.objects.create(
            id=1, name='contract-allowed', hostname='192.0.2.10', port=22,
            username='test', is_verified=True, created_by=self.admin)
        self.denied = Host.objects.create(
            id=2, name='contract-denied', hostname='192.0.2.11', port=22,
            username='test', is_verified=True, created_by=self.admin)
        self.group = Group.objects.create(name='contract-group')
        self.group.hosts.add(self.allowed)
        self.role.group_perms = [self.group.id]
        self.role.save(update_fields=['group_perms'])
        self.token, self.plaintext = service.create_token(
            self.user, 'contract-token', 7, [self.allowed.id])

    @staticmethod
    def make_user(username, **kwargs):
        return User.objects.create(
            username=username, nickname=username, password_hash='not-a-password',
            type='default', is_active=True, is_deleted=False,
            access_token='', token_expired=0, last_login='', last_ip='', **kwargs)

    def request(self, view, method='get', user=None, body=None):
        if method in ('get', 'delete'):
            request = getattr(self.factory, method)('/contract/?' + urlencode(body or {}))
        else:
            request = getattr(self.factory, method)(
                '/contract/', data=json.dumps(body or {}), content_type='application/json')
        request.user = user or self.user
        return json.loads(view.as_view()(request).content)

    def audit_rows(self, response):
        self.assertFalse(response['error'])
        data = response['data']
        rows = data['records'] if isinstance(data, dict) else data
        self.assertIsInstance(rows, list)
        return rows

    def assert_no_secret(self, value, secret=None):
        serialized = json.dumps(value, default=str, ensure_ascii=False)
        self.assertFalse((secret or self.plaintext) in serialized,
                         'Full bearer credential leaked (value suppressed)')

    def assert_audit_safe(self, secret=None):
        rows = list(McpAuditLog.objects.values())
        self.assertTrue(rows, 'Rejection/execution must leave an audit record')
        self.assert_no_secret(rows, secret)

    def rpc(self, tool, arguments=None, plaintext=None, token=None):
        from apps.mcp_ops import mcp_server
        from mcp.server.auth.provider import AccessToken
        plaintext = self.plaintext if plaintext is None else plaintext
        token = token or self.token
        access = AccessToken(token=plaintext, client_id='security-contract',
                             scopes=['mcp:operate'], claims={'token_id': token.id})
        context = SimpleNamespace(headers={
            'authorization': 'Bearer ' + plaintext, 'x-moon-client-ip': '192.0.2.20'})
        variable = getattr(mcp_server, '_TOKEN_VALUE', None)
        reset = variable.set(plaintext) if variable is not None else None
        try:
            with patch.object(mcp_server, 'get_access_token', return_value=access):
                return async_to_sync(mcp_server.server.call_tool)(
                    tool, arguments or {}, context)
        finally:
            if variable is not None:
                variable.reset(reset)

    def assert_rpc_rejected(self, tool, arguments=None, **kwargs):
        from mcp.server.mcpserver.exceptions import ToolError
        try:
            result = self.rpc(tool, arguments, **kwargs)
        except (ToolError, service.AuthorizationError):
            return
        self.assertTrue(getattr(result, 'isError', False), 'RPC unexpectedly accepted invalid request')

    def test_isolation_runtime(self):
        self.assertEqual(connection.vendor, 'sqlite')
        self.assertTrue(connection.is_in_memory_db())
        self.network.assert_not_called()
        self.ssh_factory.assert_not_called()

    def test_plaintext_only_once_digest_not_in_management_responses(self):
        self.assertTrue(self.token.token_digest == hashlib.sha256(self.plaintext.encode()).hexdigest())
        self.assert_no_secret(list(McpToken.objects.values()))
        response = self.request(TokenView)
        self.assertFalse(response['error'])
        self.assert_no_secret(response)
        self.assertFalse(self.token.token_digest in json.dumps(response), 'Digest leaked in token list')

    def test_creation_timestamp_is_lifetime_anchor_with_advancing_clock(self):
        base = datetime(2030, 1, 1)
        ticks = iter(base + timedelta(microseconds=i) for i in range(100))
        with patch('django.utils.timezone.now', side_effect=lambda: next(ticks)):
            token, _ = service.create_token(self.user, 'anchor', 1, [self.allowed.id])
        self.assertEqual(token.expires_at - token.created_at, timedelta(days=1))

    def lifetime_contract(self, days):
        base = datetime(2030, 1, 1, 12, 0, 0, 123456)
        with patch('django.utils.timezone.now', return_value=base):
            token, plaintext = service.create_token(self.user, 'fixed', days, [self.allowed.id])
        boundary = base + timedelta(days=days)
        self.assertEqual(token.created_at, base)
        self.assertEqual(token.expires_at, boundary)
        for now in (base, base + timedelta(hours=12), boundary - timedelta(microseconds=1)):
            with patch('django.utils.timezone.now', return_value=now):
                self.assertEqual(service.authenticate_token(plaintext).id, token.id)
                token.refresh_from_db()
                self.assertEqual(token.expires_at, boundary)
                self.assertEqual(token.last_used_at, now)
        for now in (boundary, boundary + timedelta(microseconds=1)):
            with patch('django.utils.timezone.now', return_value=now):
                self.assertEqual(token.status, 'expired')
                with self.assertRaises(service.AuthorizationError):
                    service.authenticate_token(plaintext)
        token.refresh_from_db()
        self.assertEqual(token.expires_at, boundary)
        self.assert_audit_safe(plaintext)

    def test_expired_token_regeneration_replaces_once_and_revokes_old(self):
        base = datetime(2030, 1, 1)
        self.token.expires_at = base
        self.token.save(update_fields=['expires_at'])
        with patch('django.utils.timezone.now', return_value=base):
            with self.assertRaises(service.AuthorizationError):
                service.authenticate_token(self.plaintext)
            replacement, plaintext = service.regenerate_token(self.token, self.user, 30)
            self.assertEqual(replacement.expires_at, base + timedelta(days=30))
            self.assertEqual(service.authenticate_token(plaintext).id, replacement.id)
            with self.assertRaises(service.AuthorizationError):
                service.authenticate_token(self.plaintext)
            self.token.refresh_from_db()
            self.assertIsNotNone(self.token.revoked_at)
            self.assertEqual(self.token.replaced_by_id, replacement.id)
            self.assertFalse(plaintext == self.plaintext)
            before = McpToken.objects.count()
            with self.assertRaises(ValueError):
                service.regenerate_token(self.token, self.user, 1)
            self.assertEqual(McpToken.objects.count(), before)

    def test_invalid_regeneration_is_atomic_old_token_still_works(self):
        before = McpToken.objects.count()
        with self.assertRaises(ValueError):
            service.regenerate_token(self.token, self.user, 31)
        self.token.refresh_from_db()
        self.assertIsNone(self.token.revoked_at)
        self.assertEqual(McpToken.objects.count(), before)
        self.assertEqual(service.authenticate_token(self.plaintext).id, self.token.id)

    def test_revocation_effective_on_next_rpc(self):
        self.rpc('list_servers')
        service.revoke_token(self.token)
        self.assert_rpc_rejected('execute_script', {'host_id': 1, 'script': 'uptime'})
        self.run_ssh.assert_not_called()

    def test_disabled_user_effective_on_next_rpc(self):
        self.rpc('list_servers')
        response = self.request(UserView, 'patch', self.admin,
                                {'id': self.user.id, 'is_active': False})
        self.assertFalse(response['error'])
        self.assert_rpc_rejected('execute_script', {'host_id': 1, 'script': 'uptime'})
        self.run_ssh.assert_not_called()
        self.assert_audit_safe()

    def test_soft_deleted_user_effective_on_next_rpc(self):
        self.rpc('list_servers')
        response = self.request(UserView, 'delete', self.admin, {'id': self.user.id})
        self.assertFalse(response['error'])
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_deleted)
        self.assert_rpc_rejected('list_servers')
        self.run_ssh.assert_not_called()

    def test_use_permission_loss_through_real_role_view_invalidates_cached_auth(self):
        self.rpc('list_servers')
        self.assertTrue(cache.get(f'perms_{self.user.id}'))
        response = self.request(RoleView, 'patch', self.admin, {
            'id': self.role.id, 'page_perms': {'system': {'mcp': ['view']}}})
        self.assertFalse(response['error'])
        self.assert_rpc_rejected('execute_script', {'host_id': 1, 'script': 'uptime'})
        self.run_ssh.assert_not_called()
        self.assert_audit_safe()

    def test_host_permission_loss_is_effective_without_reissuing_token(self):
        self.rpc('list_servers')
        response = self.request(RoleView, 'patch', self.admin,
                                {'id': self.role.id, 'group_perms': []})
        self.assertFalse(response['error'])
        token = service.authenticate_token(self.plaintext)
        self.assertEqual(service.list_authorized_hosts(token), [])
        self.assert_rpc_rejected('execute_script', {'host_id': 1, 'script': 'uptime'})
        self.run_ssh.assert_not_called()

    def test_both_token_scope_and_live_user_scope_are_required(self):
        self.group.hosts.add(self.denied)
        self.assert_rpc_rejected('execute_script', {'host_id': 2, 'script': 'uptime'})
        self.run_ssh.assert_not_called()
        self.token.hosts.add(self.denied)
        self.group.hosts.remove(self.denied)
        self.assert_rpc_rejected('execute_script', {'host_id': 2, 'script': 'uptime'})
        self.run_ssh.assert_not_called()
        self.assertEqual([row['id'] for row in service.list_authorized_hosts(self.token)], [1])

    def test_unregistered_host_and_arbitrary_ssh_target_rejected(self):
        self.assert_rpc_rejected('execute_script', {'host_id': 999999, 'script': 'uptime'})
        self.assert_rpc_rejected('check_connection', {'host_id': '192.0.2.200'})
        self.run_ssh.assert_not_called()
        self.ssh_factory.assert_not_called()

    def invalid_host_contract(self, value):
        self.assert_rpc_rejected('execute_script', {'host_id': value, 'script': 'uptime'})
        self.run_ssh.assert_not_called()

    def invalid_create_host_contract(self, value):
        before = McpToken.objects.count()
        response = self.request(TokenView, 'post', body={
            'name': 'invalid-host', 'days': 1, 'host_ids': [value]})
        self.assertTrue(response['error'], 'Malformed host ID accepted by management API')
        self.assertEqual(McpToken.objects.count(), before)

    def invalid_days_contract(self, value):
        before = McpToken.objects.count()
        response = self.request(TokenView, 'post', body={
            'name': 'invalid-days', 'days': value, 'host_ids': [1]})
        self.assertTrue(response['error'], 'Non-enumerated or non-integer lifetime accepted')
        self.assertEqual(McpToken.objects.count(), before)

    def test_creation_rejects_empty_and_unauthorized_host_sets(self):
        for host_ids in ([], [2], [1, 2], [999999]):
            with self.subTest(host_ids=host_ids):
                before = McpToken.objects.count()
                response = self.request(TokenView, 'post', body={
                    'name': 'invalid-scope', 'days': 1, 'host_ids': host_ids})
                self.assertTrue(response['error'])
                self.assertEqual(McpToken.objects.count(), before)

    def invalid_timeout_contract(self, value):
        self.assert_rpc_rejected('execute_script', {
            'host_id': 1, 'script': 'uptime', 'timeout': value})
        self.run_ssh.assert_not_called()

    def test_timeout_exact_limits_are_forwarded(self):
        for timeout in (1, 300):
            with self.subTest(timeout=timeout):
                result = service.execute_script(self.token, 1, 'uptime', timeout=timeout)
                self.assertEqual(result['status'], 'success')
                self.assertEqual(self.run_ssh.call_args.args[2], timeout)

    def test_script_byte_limit_accepts_boundary_rejects_next_byte(self):
        script = 'echo ' + 'x' * (service.MAX_SCRIPT_BYTES - 5)
        result = service.execute_script(self.token, 1, script)
        self.assertEqual(result['status'], 'success')
        self.run_ssh.reset_mock()
        self.assert_rpc_rejected('execute_script', {'host_id': 1, 'script': script + 'x'})
        self.run_ssh.assert_not_called()

    def test_script_limit_counts_utf8_bytes_and_rejects_invalid_types(self):
        for script in ('echo ' + '\u4e2d' * 11000, '', '   ', None, 123, True, ['uptime']):
            with self.subTest(kind=type(script).__name__, length=len(script) if isinstance(script, str) else 0):
                self.assert_rpc_rejected('execute_script', {'host_id': 1, 'script': script})
                self.run_ssh.assert_not_called()

    def test_bearer_in_script_and_output_never_reaches_audit(self):
        self.run_ssh.return_value = (0, 'Authorization: Bearer ' + self.plaintext)
        self.rpc('execute_script', {'host_id': 1, 'script': 'printf ' + self.plaintext})
        self.assertEqual(McpAuditLog.objects.latest('id').status, 'success')
        self.assert_audit_safe()

    def test_bearer_in_execution_exception_never_reaches_audit(self):
        self.run_ssh.side_effect = RuntimeError('Authorization: Bearer ' + self.plaintext)
        self.assert_rpc_rejected('execute_script', {'host_id': 1, 'script': 'uptime'})
        self.assert_audit_safe()

    def test_bearer_in_connection_exception_never_reaches_audit(self):
        self.ssh_factory.side_effect = None
        self.ssh_factory.return_value.ping.side_effect = RuntimeError('peer ' + self.plaintext)
        self.assert_rpc_rejected('check_connection', {'host_id': 1})
        self.assert_audit_safe()

    def test_bearer_in_rejected_dangerous_script_never_reaches_audit(self):
        self.assert_rpc_rejected('execute_script', {
            'host_id': 1, 'script': 'rm -rf / # ' + self.plaintext})
        self.run_ssh.assert_not_called()
        self.assert_audit_safe()

    def test_unknown_bearer_rejection_never_persists_plaintext(self):
        unknown = self.plaintext + '-invalid'
        with self.assertRaises(service.AuthorizationError):
            service.authenticate_token(unknown)
        self.assert_audit_safe(unknown)

    def dangerous_contract(self, script):
        self.assert_rpc_rejected('execute_script', {'host_id': 1, 'script': script})
        self.run_ssh.assert_not_called()
        self.assertEqual(McpAuditLog.objects.latest('id').status, 'rejected')

    def test_output_limit_utf8_boundary_and_nonzero_exit(self):
        for code in (0, 1, 127, -1, None):
            with self.subTest(code=code):
                self.run_ssh.return_value = (code, '\u4e2d' * 30000)
                result = service.execute_script(self.token, 1, 'uptime')
                self.assertEqual(result['status'], 'success' if code == 0 else 'failed')
                self.assertEqual(result['exit_code'], code)
                self.assertTrue(result['truncated'])
                self.assertLessEqual(len(result['output'].encode()), service.MAX_OUTPUT_BYTES)
                audit = McpAuditLog.objects.latest('id')
                self.assertEqual(audit.status, result['status'])
                self.assertEqual(audit.output, result['output'])
                self.assertEqual(audit.exit_code, code)
                if code != 0:
                    self.assertTrue(audit.failure_reason)

    def test_output_exact_boundary_is_not_marked_truncated(self):
        self.run_ssh.return_value = (0, 'a' * service.MAX_OUTPUT_BYTES)
        result = service.execute_script(self.token, 1, 'uptime')
        self.assertEqual(len(result['output'].encode()), service.MAX_OUTPUT_BYTES)
        self.assertFalse(result['truncated'])

    def test_timeout_failure_has_audit_and_releases_capacity(self):
        semaphore = threading.BoundedSemaphore(service.MAX_CONCURRENCY)
        with patch.object(service, '_SEMAPHORE', semaphore):
            self.run_ssh.side_effect = TimeoutError('synthetic deadline')
            with self.assertRaises(TimeoutError):
                service.execute_script(self.token, 1, 'uptime', timeout=1)
            audit = McpAuditLog.objects.latest('id')
            self.assertNotEqual(audit.status, 'success')
            self.assertTrue(audit.failure_reason)
            permits = [semaphore.acquire(blocking=False) for _ in range(service.MAX_CONCURRENCY)]
            self.assertTrue(all(permits))
            self.assertFalse(semaphore.acquire(blocking=False))
            for acquired in permits:
                if acquired:
                    semaphore.release()

    def test_concurrency_saturation_does_not_start_ssh_or_release_another_slot(self):
        semaphore = threading.BoundedSemaphore(service.MAX_CONCURRENCY)
        for _ in range(service.MAX_CONCURRENCY):
            self.assertTrue(semaphore.acquire(blocking=False))
        with patch.object(service, '_SEMAPHORE', semaphore):
            with self.assertRaises(service.OperationError):
                service.execute_script(self.token, 1, 'uptime')
            self.run_ssh.assert_not_called()
            self.assertFalse(semaphore.acquire(blocking=False))
            self.assertNotEqual(McpAuditLog.objects.latest('id').status, 'success')
            semaphore.release()
            self.assertEqual(service.execute_script(self.token, 1, 'uptime')['status'], 'success')
            self.assertTrue(semaphore.acquire(blocking=False))
            self.assertFalse(semaphore.acquire(blocking=False))

    def test_connection_check_shares_concurrency_budget(self):
        semaphore = threading.BoundedSemaphore(service.MAX_CONCURRENCY)
        for _ in range(service.MAX_CONCURRENCY):
            semaphore.acquire(blocking=False)
        self.ssh_factory.side_effect = None
        self.ssh_factory.return_value.ping.return_value = True
        with patch.object(service, '_SEMAPHORE', semaphore):
            self.assert_rpc_rejected('check_connection', {'host_id': 1})
        self.ssh_factory.assert_not_called()

    def test_token_name_upper_bound_is_enforced(self):
        before = McpToken.objects.count()
        response = self.request(TokenView, 'post', body={
            'name': 'n' * 101, 'days': 1, 'host_ids': [1]})
        self.assertTrue(response['error'], 'Token name exceeds model limit')
        self.assertEqual(McpToken.objects.count(), before)

    def seed_foreign_audit(self):
        token, _ = service.create_token(self.admin, 'foreign-token', 1, [2])
        log = McpAuditLog.objects.create(
            token=token, operator=self.admin, operation='execute_script', host=self.denied,
            host_name=self.denied.name, script='private-host-script-marker',
            output='private-host-output-marker', status='success')
        return token, log

    def test_scoped_log_view_hides_other_host_scripts(self):
        _, foreign_log = self.seed_foreign_audit()
        response = self.request(AuditView)
        self.assertFalse(response['error'])
        self.assertFalse(any(row['id'] == foreign_log.id and
                             (row.get('script') or row.get('output')) for row in self.audit_rows(response)),
                         'View-only role exposed unauthorized host script/output')

    def test_scoped_log_view_hides_own_history_after_host_access_revoked(self):
        log = McpAuditLog.objects.create(
            token=self.token, operator=self.user, operation='execute_script', host=self.allowed,
            host_name=self.allowed.name, script='own-private-history', status='success')
        self.group.hosts.clear()
        response = self.request(AuditView)
        self.assertFalse(response['error'])
        self.assertFalse(any(row['id'] == log.id and row.get('script') for row in self.audit_rows(response)),
                         'Historical ownership bypasses current host permissions')

    def test_scoped_token_list_hides_other_owners_and_unauthorized_hosts(self):
        foreign, _ = self.seed_foreign_audit()
        response = self.request(TokenView)
        self.assertFalse(response['error'])
        self.assertNotIn(foreign.id, [row['id'] for row in response['data']['tokens']],
                         'Scoped operator can enumerate another owner token')
        self.assertEqual([row['id'] for row in response['data']['hosts']], [1])

    def test_cannot_revoke_another_owner_token(self):
        foreign, _ = self.seed_foreign_audit()
        response = self.request(TokenView, 'delete', body={'id': foreign.id})
        foreign.refresh_from_db()
        self.assertTrue(response['error'], 'Scoped operator revoked a foreign token')
        self.assertIsNone(foreign.revoked_at)

    def test_cannot_regenerate_foreign_token_even_for_shared_host(self):
        foreign, _ = service.create_token(self.admin, 'shared-host-foreign', 1, [1])
        before = McpToken.objects.count()
        response = self.request(RegenerateView, 'post', body={'id': foreign.id, 'days': 7})
        foreign.refresh_from_db()
        self.assertTrue(response['error'], 'Scoped operator took over another owner token')
        self.assertIsNone(foreign.revoked_at)
        self.assertEqual(McpToken.objects.count(), before)

    def test_active_regeneration_invalidates_existing_rpc_context_immediately(self):
        self.rpc('list_servers')
        replacement, plaintext = service.regenerate_token(self.token, self.user, 7)
        self.assert_rpc_rejected('execute_script', {'host_id': 1, 'script': 'uptime'})
        self.run_ssh.assert_not_called()
        result = self.rpc('execute_script', {'host_id': 1, 'script': 'uptime'},
                          plaintext=plaintext, token=replacement)
        self.assertFalse(getattr(result, 'isError', False))
        self.assertEqual(self.run_ssh.call_count, 1)

    def test_regeneration_cannot_mint_superuser_bearer_for_unauthorized_host(self):
        foreign, _ = self.seed_foreign_audit()
        response = self.request(RegenerateView, 'post', body={'id': foreign.id, 'days': 1})
        if response['error']:
            foreign.refresh_from_db()
            self.assertIsNone(foreign.revoked_at)
            return
        replacement = McpToken.objects.get(pk=response['data']['id'])
        self.assert_rpc_rejected('execute_script', {'host_id': 2, 'script': 'uptime'},
                                 plaintext=response['data']['token'], token=replacement)
        self.run_ssh.assert_not_called()

    def test_superuser_can_inspect_global_audit_and_token_metadata(self):
        foreign, log = self.seed_foreign_audit()
        response = self.request(AuditView, user=self.admin)
        self.assertFalse(response['error'])
        self.assertIn(log.id, [row['id'] for row in self.audit_rows(response)])
        response = self.request(TokenView, user=self.admin)
        self.assertIn(foreign.id, [row['id'] for row in response['data']['tokens']])
        self.assert_no_secret(response)

    def test_http_real_bearer_auth_and_body_size_boundary(self):
        from apps.mcp_ops import mcp_server
        from httpx2 import ASGITransport, AsyncClient

        async def verify():
            app = mcp_server.http_app
            lifespan_app = app
            while not hasattr(lifespan_app, 'router'):
                lifespan_app = lifespan_app.app
            headers = {'Accept': 'application/json, text/event-stream',
                       'Content-Type': 'application/json',
                       'Authorization': 'Bearer ' + self.plaintext}
            payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                       'params': {'name': 'execute_script',
                                  'arguments': {'host_id': 1, 'script': 'uptime'}}}
            async with lifespan_app.router.lifespan_context(lifespan_app):
                async with AsyncClient(transport=ASGITransport(app=app),
                                       base_url='http://127.0.0.1:8000') as client:
                    response = await client.post('/', headers=headers, json=payload)
                    self.assertEqual(response.status_code, 200)
                    self.assertFalse(response.json().get('error'))
                    self.assertFalse(response.json()['result'].get('isError', False))
                    invalid_headers = dict(headers, Authorization='Bearer ' + self.plaintext + '-invalid')
                    rejected = await client.post('/', headers=invalid_headers, json=payload)
                    self.assertEqual(rejected.status_code, 401)
                    oversized = await client.post('/', headers=headers,
                                                  content=' ' * (64 * 1024 + 1))
                    self.assertEqual(oversized.status_code, 413)
                    self.assert_no_secret(response.text)
                    self.assert_no_secret(rejected.text)
            return response

        async_to_sync(verify)()
        self.assertEqual(self.run_ssh.call_count, 1)
        self.assert_audit_safe()
        self.network.assert_not_called()

    def test_audit_pagination_enforces_positive_page_and_maximum_size(self):
        self.seed_foreign_audit()
        for query in ({'page': 0}, {'page': -1}, {'page_size': 0}, {'page_size': 101}):
            with self.subTest(query=query):
                response = self.request(AuditView, user=self.admin, body=query)
                self.assertTrue(response['error'])
        response = self.request(AuditView, user=self.admin, body={'page': 1, 'page_size': 100})
        self.assertEqual(len(self.audit_rows(response)), 1)

    def test_authorized_owner_can_regenerate_and_revoke_via_views(self):
        response = self.request(RegenerateView, 'post', body={'id': self.token.id, 'days': 1})
        self.assertFalse(response['error'])
        self.token.refresh_from_db()
        self.assertIsNotNone(self.token.revoked_at)
        replacement = McpToken.objects.get(pk=response['data']['id'])
        self.assertEqual(replacement.user_id, self.user.id)
        self.assertEqual(service.authenticate_token(response['data']['token']).id, replacement.id)
        response = self.request(TokenView, 'delete', body={'id': replacement.id})
        self.assertFalse(response['error'])
        replacement.refresh_from_db()
        self.assertIsNotNone(replacement.revoked_at)

    def test_page_permission_is_required_for_management_and_logs(self):
        for view, method, body in (
                (TokenView, 'get', None), (AuditView, 'get', None),
                (TokenView, 'post', {'name': 'x', 'days': 1, 'host_ids': [1]}),
                (TokenView, 'delete', {'id': self.token.id}),
                (RegenerateView, 'post', {'id': self.token.id, 'days': 1})):
            with self.subTest(view=view.__name__, method=method):
                response = self.request(view, method, self.other, body)
                self.assertTrue(response['error'])
                self.assertFalse(response['data'])
        self.token.refresh_from_db()
        self.assertIsNone(self.token.revoked_at)


# Separate generated tests give a real per-input result, without printing credentials.
def _case(method, value):
    def test(self):
        method(self, value)
    return test


for _days in (1, 7, 30):
    setattr(SecurityContractTests, f'test_lifetime_{_days}_days_absolute_boundary',
            _case(SecurityContractTests.lifetime_contract, _days))

for _label, _value in (
        ('bool', True), ('float', 1.1), ('integer_float', 1.0),
        ('numeric_string', '1'), ('none', None), ('list', [1]), ('zero', 0), ('negative', -1)):
    setattr(SecurityContractTests, f'test_rpc_host_id_rejects_{_label}',
            _case(SecurityContractTests.invalid_host_contract, _value))
    setattr(SecurityContractTests, f'test_create_host_id_rejects_{_label}',
            _case(SecurityContractTests.invalid_create_host_contract, _value))

for _label, _value in (('bool', True), ('float', 1.9), ('numeric_string', '7'),
                       ('zero', 0), ('two', 2), ('above_max', 31)):
    setattr(SecurityContractTests, f'test_duration_rejects_{_label}',
            _case(SecurityContractTests.invalid_days_contract, _value))

for _label, _value in (('bool', True), ('float', 1.0), ('fractional', 1.5),
                       ('numeric_string', '60'), ('zero', 0), ('negative', -1), ('above_max', 301)):
    setattr(SecurityContractTests, f'test_timeout_rejects_{_label}',
            _case(SecurityContractTests.invalid_timeout_contract, _value))

for _label, _script in (
        ('root_delete', 'rm -rf /'), ('format_disk', 'mkfs.ext4 /dev/test'),
        ('reboot', 'reboot'), ('drop_database', 'DROP DATABASE contract_db'),
        ('docker_prune', 'docker system prune -af'),
        ('root_delete_long_flags', 'rm --recursive --force /'),
        ('root_delete_quoted', "rm -rf '/'"),
        ('quoted_executable', "r''m -rf /"),
        ('split_executable', "a=reb; b=oot; \"$a$b\"")):
    setattr(SecurityContractTests, f'test_dangerous_command_rejects_{_label}',
            _case(SecurityContractTests.dangerous_contract, _script))


class SshBoundaryContractTests(TestCase):
    """Exercise the real channel loop with a deterministic, non-network transport."""
    def setUp(self):
        _require_isolation()
        self.enterContext(patch.object(socket.socket, 'connect',
                                       side_effect=AssertionError('Real network forbidden')))
        self.channel = Mock()
        self.channel.recv_ready.return_value = False
        self.channel.exit_status_ready.return_value = True
        self.channel.recv_exit_status.return_value = 0
        self.ssh = Mock()
        self.ssh.get_client.return_value.get_transport.return_value.open_session.return_value = self.channel
        self.host = Mock()
        self.host.get_ssh.return_value = self.ssh

    def test_real_channel_deadline_closes_channel(self):
        self.channel.exit_status_ready.return_value = False
        with patch.object(service.time, 'monotonic', side_effect=[0, 0.2, 1.1]), \
                patch.object(service.time, 'sleep'):
            with self.assertRaises(TimeoutError):
                service._run_ssh(self.host, 'uptime', 1)
        self.channel.close.assert_called()

    def test_real_channel_unknown_exit_never_converted_to_zero(self):
        self.channel.recv_exit_status.return_value = -1
        code, output = service._run_ssh(self.host, 'uptime', 1)
        self.assertEqual(code, -1)
        self.assertIsInstance(output, str)

    def test_success_closes_channel_and_client(self):
        code, _ = service._run_ssh(self.host, 'uptime', 1)
        self.assertEqual(code, 0)
        self.channel.close.assert_called()
        self.ssh.get_client.return_value.close.assert_called()

    def test_receive_exception_closes_channel_and_client(self):
        self.channel.recv_ready.return_value = True
        self.channel.recv.side_effect = TimeoutError('synthetic recv timeout')
        with self.assertRaises(TimeoutError):
            service._run_ssh(self.host, 'uptime', 1)
        self.channel.close.assert_called()
        self.ssh.get_client.return_value.close.assert_called()
