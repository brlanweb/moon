import hashlib
import re
import secrets
import shlex
import threading
import time
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.account.utils import get_host_perms
from apps.ai.risk import check_command
from apps.host.models import Host
from apps.mcp_ops.models import McpAuditLog, McpToken

TOKEN_DAYS = (1, 7, 30)
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


def _validate_hosts(user, host_ids):
    if type(host_ids) is not list or not host_ids or not all(_valid_id(item) for item in host_ids):
        raise ValueError('请授权有效的服务器整数 ID')
    ids = set(host_ids)
    existing = set(Host.objects.filter(id__in=ids).values_list('id', flat=True))
    permitted = existing if user.is_supper else existing.intersection(get_host_perms(user))
    if permitted != ids:
        raise AuthorizationError('只能授权当前用户有权访问的已登记主机')
    return ids


@transaction.atomic
def create_token(user, name, days, host_ids):
    if type(days) is not int or days not in TOKEN_DAYS:
        raise ValueError('令牌有效期只能是 1、7 或 30 天')
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        raise ValueError('令牌名称须为 1 到 100 个字符')
    if not user.is_active or user.is_deleted or user.type != 'default':
        raise AuthorizationError('用户已禁用')
    ids = _validate_hosts(user, host_ids)
    plaintext = f'moon_{secrets.token_urlsafe(32)}'
    token = McpToken.objects.create(
        name=name.strip(), token_prefix=plaintext[:12], token_digest=_digest(plaintext),
        user=user, created_by=user, expires_at=timezone.now() + timedelta(days=days))
    # Anchor expiration to the stored creation timestamp, never to last use.
    token.expires_at = token.created_at + timedelta(days=days)
    token.save(update_fields=['expires_at'])
    token.hosts.set(ids)
    return token, plaintext


@transaction.atomic
def regenerate_token(token, actor, days):
    current = McpToken.objects.select_for_update().select_related('user').get(pk=token.pk)
    if not actor.is_supper and current.user_id != actor.id:
        raise AuthorizationError('无权管理其他用户的令牌')
    if current.revoked_at:
        raise ValueError('已撤销令牌不能重新生成')
    owner = current.user
    replacement, plaintext = create_token(owner, current.name, days,
                                          list(current.hosts.values_list('id', flat=True)))
    replacement.created_by = actor
    replacement.save(update_fields=['created_by'])
    current.revoked_at = timezone.now()
    current.replaced_by = replacement
    current.save(update_fields=['revoked_at', 'replaced_by'])
    return replacement, plaintext


def revoke_token(token):
    McpToken.objects.filter(pk=token.pk, revoked_at__isnull=True).update(revoked_at=timezone.now())


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
    token_ids = set(token.hosts.values_list('id', flat=True))
    current_ids = token_ids if token.user.is_supper else token_ids.intersection(get_host_perms(token.user))
    return Host.objects.filter(id__in=current_ids).order_by('id')


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
        raise AuthorizationError('主机未登记、未授权或用户权限已撤销')
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
        risk = _script_risk(script)
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
