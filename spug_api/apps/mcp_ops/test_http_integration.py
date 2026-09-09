"""Official SDK over real HTTP; temporary database and synthetic SSH only."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path

import anyio
import httpx2


def wait_ready(port, process):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(process.stderr.read())
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1', port)) == 0:
                return
        time.sleep(0.05)
    raise RuntimeError('MCP test server did not start')


def main():
    with tempfile.TemporaryDirectory(prefix='moon-mcp-http-') as directory:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env = {**os.environ, 'SPUG_DEBUG': 'true',
               'DJANGO_SETTINGS_MODULE': 'apps.mcp_ops.test_http_settings',
               'MOON_MCP_TEST_DB': os.path.join(directory, 'test.sqlite3'),
               'MOON_MCP_RESOURCE_URL': f'http://127.0.0.1:{port}/mcp',
               'MOON_MCP_ISSUER_URL': f'http://127.0.0.1:{port}'}
        root = Path(__file__).resolve().parents[2]
        subprocess.run([sys.executable, 'manage.py', 'migrate', '--noinput'], cwd=root,
                       env=env, check=True, stdout=subprocess.DEVNULL, timeout=60)
        os.environ.update(env)
        credentials = seed()
        process = subprocess.Popen([
            sys.executable, '-m', 'uvicorn', 'apps.mcp_ops.http_test_app:application',
            '--host', '127.0.0.1', '--port', str(port), '--lifespan', 'on', '--log-level', 'warning',
        ], cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            wait_ready(port, process)
            anyio.run(run_client_checks, port, credentials)
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def seed():
    import django
    django.setup()
    from apps.account.models import Role, User
    from apps.host.models import Group, Host
    from apps.mcp_ops.service import create_token, revoke_token
    from django.utils import timezone
    user = User.objects.create(username='http-operator', nickname='HTTP Operator', password_hash='x',
                               type='default', is_active=True, is_deleted=False)
    host = Host.objects.create(name='HTTP Synthetic Host', hostname='192.0.2.10', port=22,
                               username='test', is_verified=True, created_by=user)
    group = Group.objects.create(name='HTTP Synthetic Group')
    group.hosts.add(host)
    role = Role.objects.create(name='mcp-http', page_perms={'system': {'mcp': ['use']}},
                               group_perms=[group.id])
    user.roles.add(role)
    credentials = {'host_id': host.id}
    for name in ('active', 'expired', 'revoked'):
        token, plaintext = create_token(user, name, 1, [host.id])
        if name == 'expired':
            token.expires_at = timezone.now() - timedelta(seconds=1)
            token.save(update_fields=['expires_at'])
        elif name == 'revoked':
            revoke_token(token)
        credentials[name] = plaintext
        credentials[name + '_id'] = token.id
    return credentials


async def run_client_checks(port, credentials):
    from asgiref.sync import sync_to_async
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client
    from apps.mcp_ops.models import McpAuditLog, McpToken
    from apps.mcp_ops.service import regenerate_token
    url = f'http://127.0.0.1:{port}/mcp/'
    async with httpx2.AsyncClient(headers={
        'Authorization': 'Bearer ' + credentials['active'], 'X-Moon-Client-IP': '198.51.100.8'
    }) as transport:
        async with Client(streamable_http_client(url, http_client=transport)) as client:
            tools = await client.list_tools()
            names = {item.name for item in tools.tools}
            assert names == {'list_servers', 'check_connection', 'execute_script'}
            result = await client.call_tool('list_servers', {})
            assert not result.is_error and result.structured_content['result'][0]['id'] == credentials['host_id']
            checked = await client.call_tool('check_connection', {'host_id': credentials['host_id']})
            assert not checked.is_error and json.loads(checked.content[0].text)['connected']
            executed = await client.call_tool('execute_script', {
                'host_id': credentials['host_id'], 'script': 'printf test', 'timeout': 1})
            assert not executed.is_error
            execution = json.loads(executed.content[0].text)
            assert execution['exit_code'] == 0 and execution['output'] == 'mock SSH output'
    payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}}
    headers = {'Accept': 'application/json, text/event-stream', 'Content-Type': 'application/json',
               'X-Moon-Client-IP': '198.51.100.9'}
    async with httpx2.AsyncClient() as client:
        metadata = await client.get(f'http://127.0.0.1:{port}/.well-known/oauth-protected-resource/mcp')
        assert metadata.status_code == 200 and metadata.json()['resource'] == url.rstrip('/')
        assert (await client.post(url, headers=headers, json=payload)).status_code == 401
        for name in ('expired', 'revoked'):
            response = await client.post(url, headers={**headers, 'Authorization': 'Bearer ' + credentials[name]}, json=payload)
            assert response.status_code == 401
        expired = await sync_to_async(McpToken.objects.select_related('user').get)(pk=credentials['expired_id'])
        replacement, plaintext = await sync_to_async(regenerate_token)(expired, expired.user, 7)
        response = await client.post(url, headers={**headers, 'Authorization': 'Bearer ' + plaintext}, json=payload)
        assert response.status_code == 200
        response = await client.post(url, headers={**headers, 'Authorization': 'Bearer ' + credentials['expired']}, json=payload)
        assert response.status_code == 401
    logs = await sync_to_async(list)(McpAuditLog.objects.values())
    serialized = json.dumps(logs, default=str)
    assert all(value not in serialized for value in [credentials[name] for name in ('active', 'expired', 'revoked')] + [plaintext])
    for name, reason in [('expired', '令牌已过期'), ('revoked', '令牌已撤销')]:
        assert any(row['token_id'] == credentials[name + '_id'] and row['failure_reason'] == reason and
                   row['ip'] == '198.51.100.9' for row in logs)
    assert any(row['operation'] == 'execute_script' and row['status'] == 'success' for row in logs)
    print(json.dumps({'tools': sorted(names), 'http_tools_executed': 3, 'ssh': 'mocked',
                      'unauthorized': 401, 'expired': 401, 'revoked': 401,
                      'regenerated': 200, 'old_after_regeneration': 401, 'audit_secret_free': True}))


if __name__ == '__main__':
    main()
