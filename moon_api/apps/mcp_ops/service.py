import hashlib
import re
import secrets
import shlex
import threading
import time
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.ai.risk import check_command
from apps.host.models import Host
from apps.mcp_ops.models import McpAuditLog, McpToken

TOKEN_DAYS = (1, 7, 30, 180, 365)
MAX_OUTPUT_BYTES = 64 * 1024
MAX_SCRIPT_BYTES = 32 * 1024
MAX_TIMEOUT = 300
MAX_CONCURRENCY = 4
_CREDENTIAL_RE = re.compile(
    r'''(?i)(password|passwd|token|secret|api[_-]?key)\s*[:=]\s*(?:"[^"]*"|'[^']*'|[^\s;]+)''')
_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENCY)


class AuthorizationError(Exception):
    pass


class OperationError(Exception):
    pass


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _redact(value, sensitive_values=()):
    text = str(value or '').replace('\x00', '')
    for sensitive in sensitive_values:
        if sensitive:
            text = text.replace(sensitive, '[REDACTED]')
    text = re.sub(r'moon_[A-Za-z0-9_-]{32,}', '[REDACTED]', text)
    text = re.sub(r'(?i)(authorization\s*:\s*bearer\s+)\S+', r'\1[REDACTED]', text)
    text = re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----',
                  '[REDACTED PRIVATE KEY]', text, flags=re.DOTALL)
    return _CREDENTIAL_RE.sub(lambda match: f'{match.group(1)}=[REDACTED]', text)


def _truncate(value):
    data = (value or '').encode('utf-8', errors='replace')
    return data[:MAX_OUTPUT_BYTES].decode('utf-8', errors='ignore'), len(data) > MAX_OUTPUT_BYTES


def _audit(token=None, operation='authenticate', ip='', host=None, script=None,
           status='rejected', exit_code=None, output=None, duration_ms=0, failure_reason=None,
           operator=None):
    return McpAuditLog.objects.create(
        token=token, operator=operator or (token.user if token else None),
        operation=operation, ip=_redact(ip)[:50], host=host,
        host_name=_redact(host.name)[:100] if host else None,
        script=_redact(script)[:MAX_SCRIPT_BYTES] if script else None,
        status=status, exit_code=exit_code,
        output=_truncate(_redact(output))[0] if output is not None else None,
        duration_ms=duration_ms, failure_reason=_redact(failure_reason)[:255] if failure_reason else None)


def _valid_id(value):
    return type(value) is int and 0 < value <= 2 ** 63 - 1


def _validate_days(days):
    if type(days) is not int or days not in TOKEN_DAYS:
        raise ValueError('令牌有效期只能是 1、7、30 天、6 个月（180 天）或 1 年（365 天）')


def _new_secret():
    plaintext = f'moon_{secrets.token_urlsafe(32)}'
    return plaintext, plaintext[:12], _digest(plaintext)


def _validate_name(name):
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        raise ValueError('令牌名称须为 1 到 100 个字符')
    return name.strip()


def _validate_level(level, actor):
    if level not in (McpToken.LEVEL_NORMAL, McpToken.LEVEL_SUPER):
        raise ValueError('令牌级别只能是 normal（普通）或 super（超管）')
    if level == McpToken.LEVEL_SUPER and not actor.is_supper:
        raise AuthorizationError('只有超级管理员可以授予超管 Key')
    return level


def is_unrestricted(token):
    """A super key skips script risk checks and file path whitelists, but only while its owner is still a super admin."""
    return token.level == McpToken.LEVEL_SUPER and bool(token.user.is_supper)


@transaction.atomic
def create_token(user, name, days, level=McpToken.LEVEL_NORMAL):
    """Create a token that may operate every registered host while its owner keeps MCP use permission."""
    _validate_days(days)
    name = _validate_name(name)
    level = _validate_level(level, user)
    if not user.is_active or user.is_deleted or user.type != 'default':
        raise AuthorizationError('用户已禁用')
    plaintext, prefix, digest = _new_secret()
    token = McpToken.objects.create(
        name=name, level=level, token_prefix=prefix, token_digest=digest,
        user=user, created_by=user, expires_at=timezone.now() + timedelta(days=days))
    # Anchor expiration to the stored creation timestamp, never to last use.
    token.expires_at = token.created_at + timedelta(days=days)
    token.save(update_fields=['expires_at'])
    return token, plaintext


@transaction.atomic
def regenerate_token(token, actor, days):
    """Refresh a token in place: the old secret stops working immediately, the record and audit links stay."""
    _validate_days(days)
    current = McpToken.objects.select_for_update().select_related('user').get(pk=token.pk)
    if not actor.is_supper and current.user_id != actor.id:
        raise AuthorizationError('无权管理其他用户的令牌')
    if current.revoked_at:
        raise ValueError('已撤销的历史令牌不能刷新，请删除后重新创建')
    plaintext, prefix, digest = _new_secret()
    current.token_prefix, current.token_digest = prefix, digest
    current.expires_at = timezone.now() + timedelta(days=days)
    current.last_used_at = None
    current.save(update_fields=['token_prefix', 'token_digest', 'expires_at', 'last_used_at'])
    return current, plaintext


@transaction.atomic
def update_token(token, actor, name, level):
    """Edit name and level in place; the secret, expiry and audit links stay unchanged."""
    current = McpToken.objects.select_for_update().select_related('user').get(pk=token.pk)
    if not actor.is_supper and current.user_id != actor.id:
        raise AuthorizationError('无权管理其他用户的令牌')
    current.name = _validate_name(name)
    current.level = _validate_level(level, actor)
    current.save(update_fields=['name', 'level'])
    return current


def delete_token(token, actor):
    if not actor.is_supper and token.user_id != actor.id:
        raise AuthorizationError('无权管理其他用户的令牌')
    McpToken.objects.filter(pk=token.pk).delete()


def audit_auth_rejection(plaintext, ip, reason):
    token = McpToken.objects.select_related('user').filter(token_digest=_digest(plaintext)).first()
    _audit(token=token, ip=ip, failure_reason=reason)


def _assert_usable(token):
    if token.revoked_at:
        raise AuthorizationError('令牌已撤销')
    if token.expires_at <= timezone.now():
        raise AuthorizationError('令牌已过期')
    if not token.user.is_active or token.user.is_deleted or token.user.type != 'default':
        raise AuthorizationError('用户已禁用')
    if not token.user.has_perms(['system.mcp.use']):
        raise AuthorizationError('用户不再具有 MCP 操作权限')


def authenticate_token(plaintext, ip='', audit=True):
    token = McpToken.objects.select_related('user').filter(token_digest=_digest(plaintext)).first()
    try:
        if not token:
            raise AuthorizationError('无效令牌')
        _assert_usable(token)
    except AuthorizationError as exc:
        if audit:
            _audit(token=token, ip=ip, failure_reason=str(exc))
        raise
    token.last_used_at = timezone.now()
    token.save(update_fields=['last_used_at'])
    return token


def authorized_host_queryset(token):
    token = McpToken.objects.select_related('user').get(pk=token.pk)
    _assert_usable(token)
    # Tokens are no longer scoped: every registered host is reachable, including hosts added later.
    return Host.objects.all().order_by('id')


def list_authorized_hosts(token, ip=None):
    records = [{'id': item.id, 'name': item.name, 'hostname': item.hostname,
                'port': item.port, 'username': item.username,
                'is_verified': item.is_verified} for item in authorized_host_queryset(token)]
    if ip is not None:
        _audit(token, 'list_servers', ip, status='success')
    return records


def _get_authorized_host(token, host_id):
    if not _valid_id(host_id):
        raise AuthorizationError('服务器 ID 必须是正整数')
    host = authorized_host_queryset(token).filter(pk=host_id).first()
    if not host:
        raise AuthorizationError('主机未登记')
    return host


def _script_risk(script):
    risk = check_command(script, 'repair')
    if risk:
        return risk
    # Unattended execution must not expand an uninspectable command at runtime.
    if '$' in script or '`' in script:
        return '动态 Shell 展开需要通过交互式终端人工确认'
    try:
        words = shlex.split(script, comments=True, posix=True)
    except ValueError:
        return '无法安全解析脚本，请通过交互式终端确认'
    normalized = ' '.join(words)
    risk = check_command(normalized, 'repair')
    if risk:
        return risk
    if re.search(r'\brm\b[^;|&\n]*\s/(?:\s|$|\*)', normalized):
        return '高危命令，需要人工确认'
    if re.search(r'\b(eval|exec|bash|dash|zsh|sh|python[23]?|perl|ruby|node|php)\b', normalized):
        return '间接脚本执行需要通过交互式终端人工确认'
    return None


def _run_ssh(host, script, timeout):
    ssh = host.get_ssh()
    client = channel = None
    try:
        if isinstance(ssh.arguments, dict):
            ssh.arguments.update(timeout=min(timeout, 10), banner_timeout=min(timeout, 10),
                                 auth_timeout=min(timeout, 10))
        client = ssh.get_client()
        channel = client.get_transport().open_session(timeout=timeout)
        channel.set_combine_stderr(True)
        channel.settimeout(timeout)
        channel.exec_command(script)
        output = bytearray()
        deadline = time.monotonic() + timeout
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError(f'执行超过 {timeout} 秒')
            if channel.recv_ready():
                chunk = channel.recv(4096)
                remaining = MAX_OUTPUT_BYTES + 1 - len(output)
                if remaining > 0:
                    output.extend(chunk[:remaining])
            elif channel.exit_status_ready():
                break
            else:
                time.sleep(0.02)
        return channel.recv_exit_status(), bytes(output).decode('utf-8', errors='replace')
    finally:
        if channel is not None:
            channel.close()
        client = client or getattr(ssh, 'client', None)
        if client is not None:
            client.close()


def _raise_safe(exc, sensitive_values):
    reason = _redact(str(exc), sensitive_values)
    error_type = type(exc) if isinstance(exc, (AuthorizationError, OperationError, TimeoutError)) else OperationError
    raise error_type(reason) from None


def check_connection(token, host_id, ip='', sensitive_values=()):
    started = time.monotonic()
    host = None
    try:
        host = _get_authorized_host(token, host_id)
        if not _SEMAPHORE.acquire(blocking=False):
            raise OperationError('MCP 执行并发已达上限')
        ssh = None
        try:
            ssh = host.get_ssh()
            if isinstance(ssh.arguments, dict):
                ssh.arguments.update(timeout=10, banner_timeout=10, auth_timeout=10)
            ssh.ping()
        finally:
            if ssh is not None and getattr(ssh, 'client', None) is not None:
                ssh.client.close()
            _SEMAPHORE.release()
        _audit(token, 'check_connection', ip, host, status='success',
               duration_ms=int((time.monotonic() - started) * 1000))
        return {'host_id': host.id, 'connected': True}
    except Exception as exc:
        _audit(token, 'check_connection', ip, host, failure_reason=_redact(str(exc), sensitive_values),
               duration_ms=int((time.monotonic() - started) * 1000))
        _raise_safe(exc, sensitive_values)


def execute_script(token, host_id, script, ip='', timeout=60, sensitive_values=()):
    started = time.monotonic()
    host = None
    try:
        if not isinstance(script, str) or not script.strip():
            raise AuthorizationError('脚本不能为空')
        if len(script.encode()) > MAX_SCRIPT_BYTES or '\x00' in script:
            raise AuthorizationError('脚本超过 32 KiB 限制或包含无效字符')
        if type(timeout) is not int or not 1 <= timeout <= MAX_TIMEOUT:
            raise AuthorizationError('超时范围必须是 1 到 300 秒')
        host = _get_authorized_host(token, host_id)
        risk = None if is_unrestricted(token) else _script_risk(script)
        if risk:
            raise AuthorizationError(risk)
        if not _SEMAPHORE.acquire(blocking=False):
            raise OperationError('MCP 执行并发已达上限')
        try:
            exit_code, output = _run_ssh(host, script, timeout)
        finally:
            _SEMAPHORE.release()
        output, truncated = _truncate(_redact(output, sensitive_values))
        status = 'success' if exit_code == 0 else 'failed'
        _audit(token, 'execute_script', ip, host, _redact(script, sensitive_values), status, exit_code,
               output, int((time.monotonic() - started) * 1000),
               None if exit_code == 0 else f'退出码 {exit_code}')
        return {'host_id': host.id, 'status': status, 'exit_code': exit_code,
                'output': output, 'truncated': truncated}
    except Exception as exc:
        audit_script = '[BLOCKED DANGEROUS SCRIPT]' if isinstance(exc, AuthorizationError) else _redact(script, sensitive_values)
        _audit(token, 'execute_script', ip, host, audit_script,
               status='rejected' if isinstance(exc, (AuthorizationError, OperationError)) else 'failed',
               failure_reason=_redact(str(exc), sensitive_values),
               duration_ms=int((time.monotonic() - started) * 1000))
        _raise_safe(exc, sensitive_values)
