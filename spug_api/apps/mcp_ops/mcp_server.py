from urllib.parse import urlsplit

from asgiref.sync import sync_to_async
from mcp.server.transport_security import TransportSecuritySettings
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.context import Context
from pydantic import AnyHttpUrl, StrictInt, StrictStr

from apps.mcp_ops.service import (
    AuthorizationError,
    audit_auth_rejection,
    authenticate_token,
    check_connection as check_host_connection,
    execute_script as execute_host_script,
    list_authorized_hosts,
)

RESOURCE_URL = __import__('os').environ.get('MOON_MCP_RESOURCE_URL', 'http://127.0.0.1:8000/mcp')
ISSUER_URL = __import__('os').environ.get('MOON_MCP_ISSUER_URL', 'http://127.0.0.1:8000')
_CLIENT_IP = __import__('contextvars').ContextVar('moon_mcp_client_ip', default='')
_TOKEN_VALUE = __import__('contextvars').ContextVar('moon_mcp_token_value', default='')


class MoonTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str):
        try:
            item = await sync_to_async(authenticate_token, thread_sensitive=True)(token, _CLIENT_IP.get(), True)
        except AuthorizationError:
            return None
        _TOKEN_VALUE.set(token)
        return AccessToken(
            token=token, client_id=f'moon-token-{item.id}', scopes=['mcp:operate'],
            expires_at=int(item.expires_at.timestamp()), resource=RESOURCE_URL,
            subject=str(item.user_id), claims={'token_id': item.id})


def _request_ip(context):
    headers = context.headers or {}
    # Nginx overwrites this header with its trusted peer address. Do not read
    # X-Forwarded-For here because clients can prepend arbitrary values.
    return (headers.get('x-moon-client-ip') or '').strip()[:50]


def _token_id(ip=''):
    access_token = get_access_token()
    if not access_token or not access_token.claims:
        raise AuthorizationError('缺少认证上下文')
    try:
        item = authenticate_token(_TOKEN_VALUE.get(), ip)
    except AuthorizationError:
        raise
    if item.id != access_token.claims['token_id']:
        raise AuthorizationError('认证上下文不一致')
    return item.id


server = MCPServer(
    'Moon Operations', version='1.0.0', token_verifier=MoonTokenVerifier(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(ISSUER_URL),
        resource_server_url=AnyHttpUrl(RESOURCE_URL),
        required_scopes=['mcp:operate'], validate_token_resource=True))


async def _current_token(context):
    from apps.mcp_ops.models import McpToken
    ip = _request_ip(context)
    token_id = await sync_to_async(_token_id, thread_sensitive=True)(ip)
    return await sync_to_async(McpToken.objects.select_related('user').get, thread_sensitive=True)(pk=token_id)


@server.tool(description='列出当前令牌授权且操作者当前仍有权限的 Moon 已登记服务器。')
async def list_servers(context: Context) -> list[dict]:
    token = await _current_token(context)
    return await sync_to_async(list_authorized_hosts, thread_sensitive=True)(token, _request_ip(context))


@server.tool(description='检查一台已登记、已授权且当前仍有权限的服务器 SSH 连接。')
async def check_connection(host_id: StrictInt, context: Context) -> dict:
    token = await _current_token(context)
    return await sync_to_async(check_host_connection, thread_sensitive=True)(
        token, host_id, _request_ip(context), (_TOKEN_VALUE.get(),))


@server.tool(description='在一台已登记、已授权且当前仍有权限的服务器执行受限脚本；高危脚本拒绝，超时最多 300 秒，输出最多 64 KiB。')
async def execute_script(host_id: StrictInt, script: StrictStr, context: Context, timeout: StrictInt = 60) -> dict:
    token = await _current_token(context)
    return await sync_to_async(execute_host_script, thread_sensitive=True)(
        token, host_id, script, _request_ip(context), timeout, (_TOKEN_VALUE.get(),))


class ClientIpMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        headers = {key.decode('latin1').lower(): value.decode('latin1')
                   for key, value in scope.get('headers', [])}
        peer = (scope.get('client') or ('', 0))[0]
        ip = headers.get('x-moon-client-ip', '') or peer
        context_token = _CLIENT_IP.set(ip[:50])
        try:
            if scope.get('type') == 'http' and scope.get('method') in ('GET', 'POST', 'DELETE'):
                authorization = headers.get('authorization', '')
                if not authorization.lower().startswith('bearer ') or not authorization[7:].strip():
                    await sync_to_async(audit_auth_rejection, thread_sensitive=True)(
                        '', ip[:50], '缺少有效 Bearer 令牌')
            return await self.app(scope, receive, send)
        finally:
            _CLIENT_IP.reset(context_token)


_resource = urlsplit(RESOURCE_URL)
_transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=['127.0.0.1:*', 'localhost:*', '[::1]:*', _resource.netloc, _resource.hostname],
    allowed_origins=['http://127.0.0.1:*', 'http://localhost:*', 'http://[::1]:*',
                     f'{_resource.scheme}://{_resource.netloc}'],
)
_mcp_http_app = server.streamable_http_app(
    streamable_http_path='/', stateless_http=True, json_response=True,
    transport_security=_transport_security,
    max_request_body_size=64 * 1024, max_sessions=100,
    session_idle_timeout=300)
http_app = ClientIpMiddleware(_mcp_http_app)
