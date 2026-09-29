"""One-time SFTP transfer links for the Moon MCP service.

An MCP tool call creates a short-lived link bound to (token, host, path, mode). The link itself is the
credential for a single HTTP request (PUT/POST upload or GET download) and is consumed on first use.
Only paths inside the globally configured whitelist (``MOON_MCP_FILE_DIRS``) are reachable, checked
lexically when the link is created and again against the remote real path (symlinks resolved) when
the transfer runs.
"""
import hashlib
import os
import posixpath
import secrets
import stat
import threading
import time
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from apps.mcp_ops.models import McpToken
from apps.mcp_ops.service import (
    AuthorizationError, OperationError, _assert_usable, _audit, _get_authorized_host, _redact,
)

LINK_TTL = 30 * 60
MAX_FILE_BYTES = 1024 * 1024 * 1024
MAX_PATH_LENGTH = 1024
MAX_FILE_CONCURRENCY = 2
CHUNK_SIZE = 1024 * 1024
DOWNLOAD_WINDOW = 4 * 1024 * 1024
DEFAULT_DIRS = '/tmp,/opt,/srv,/data,/home,/root'
_CACHE_PREFIX = 'mcp:file-link:'
_FILE_SEMAPHORE = threading.BoundedSemaphore(MAX_FILE_CONCURRENCY)
UPLOAD, DOWNLOAD = 'upload', 'download'


class TransferError(Exception):
    """A client-facing transfer failure with an HTTP status code."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def allowed_dirs():
    """Return normalized whitelist roots from ``MOON_MCP_FILE_DIRS`` (comma or colon separated)."""
    raw = os.environ.get('MOON_MCP_FILE_DIRS', DEFAULT_DIRS)
    roots = []
    for item in raw.replace(':', ',').split(','):
        item = item.strip()
        if not item.startswith('/') or '..' in item.split('/'):
            continue
        item = '/' + posixpath.normpath(item).lstrip('/')
        if item != '/' and item not in roots:
            roots.append(item)
    return roots


def _within(path, root):
    return path.startswith(root.rstrip('/') + '/')


def normalize_path(path):
    """Lexically validate a remote file path and return its normalized form."""
    if not isinstance(path, str) or not path.strip():
        raise AuthorizationError('远程路径不能为空')
    if len(path) > MAX_PATH_LENGTH or any(ch in path for ch in '\x00\r\n'):
        raise AuthorizationError('远程路径过长或包含无效字符')
    if not path.startswith('/'):
        raise AuthorizationError('远程路径必须是绝对路径')
    if '..' in path.split('/'):
        raise AuthorizationError('远程路径不能包含 ..')
    if path.endswith('/'):
        raise AuthorizationError('远程路径必须指向文件而不是目录')
    normalized = '/' + posixpath.normpath(path).lstrip('/')
    roots = allowed_dirs()
    if not any(_within(normalized, root) for root in roots):
        raise AuthorizationError(f'远程路径不在允许的目录内，允许目录：{", ".join(roots) or "无"}')
    return normalized


def _link_key(secret):
    return _CACHE_PREFIX + hashlib.sha256(secret.encode()).hexdigest()


def _public_base():
    from apps.mcp_ops.mcp_server import RESOURCE_URL
    return RESOURCE_URL.rstrip('/') + '/files/'


def create_link(token, host_id, remote_path, mode, ip='', sensitive_values=()):
    operation = f'create_{mode}_link'
    host = None
    try:
        host = _get_authorized_host(token, host_id)
        path = normalize_path(remote_path)
        with _connect(host) as sftp:
            if mode == UPLOAD:
                _inspect_upload(sftp, path)
            else:
                _inspect_download(sftp, path)
        secret = f'mft_{secrets.token_urlsafe(32)}'
        expires_at = timezone.now() + timedelta(seconds=LINK_TTL)
        cache.set(_link_key(secret), {
            'token_id': token.id, 'host_id': host.id, 'path': path, 'mode': mode,
        }, LINK_TTL)
        _audit(token, operation, ip, host, f'{mode} {path}', status='success')
        url = _public_base() + secret
        if mode == UPLOAD:
            usage = f'curl -fsS -T <本地文件> "{url}"'
        else:
            usage = f'curl -fsS -o <本地文件> "{url}"'
        return {'host_id': host.id, 'remote_path': path, 'method': 'PUT' if mode == UPLOAD else 'GET',
                'url': url, 'expires_at': expires_at.isoformat(), 'max_bytes': MAX_FILE_BYTES,
                'one_time': True, 'usage': usage}
    except Exception as exc:
        reason = _redact(str(exc), sensitive_values)
        _audit(token, operation, ip, host, f'{mode} {_redact(remote_path)[:MAX_PATH_LENGTH]}',
               failure_reason=reason)
        if isinstance(exc, (AuthorizationError, OperationError)):
            raise
        raise OperationError(reason) from None


def peek_link(secret):
    if not isinstance(secret, str) or not secret.startswith('mft_') or len(secret) > 128:
        return None
    return cache.get(_link_key(secret))


def claim_link(secret, mode, ip=''):
    """Consume a link exactly once and return (token, host, path)."""
    operation = f'{mode}_file'
    data = peek_link(secret)
    # Deleting is the atomic claim: under concurrency only one caller gets a truthy result.
    if not data or data.get('mode') != mode or not cache.delete(_link_key(secret)):
        _audit(None, operation, ip, failure_reason='传输链接无效、已使用或已过期')
        raise TransferError('传输链接无效、已使用或已过期', 404)
    token = McpToken.objects.select_related('user').filter(pk=data['token_id']).first()
    if not token:
        _audit(None, operation, ip, failure_reason='令牌已删除')
        raise TransferError('令牌已删除', 403)
    try:
        _assert_usable(token)
        host = _get_authorized_host(token, data['host_id'])
    except AuthorizationError as exc:
        _audit(token, operation, ip, failure_reason=str(exc))
        raise TransferError(str(exc), 403) from None
    return token, host, data['path']


def finish_audit(token, mode, ip, host, path, status, size, duration_ms, reason=None, digest=None):
    summary = f'{size} bytes' + (f', sha256={digest}' if digest else '')
    _audit(token, f'{mode}_file', ip, host, f'{mode} {path}', status=status,
           output=summary, duration_ms=duration_ms, failure_reason=reason)


class _connect:
    """Context manager yielding an SFTP client; holds a file-transfer concurrency slot."""

    def __init__(self, host):
        self.host = host
        self.ssh = None

    def __enter__(self):
        if not _FILE_SEMAPHORE.acquire(blocking=False):
            raise OperationError('文件传输并发已达上限，请稍后重试')
        try:
            self.ssh = self.host.get_ssh()
            if isinstance(self.ssh.arguments, dict):
                self.ssh.arguments.update(timeout=10, banner_timeout=10, auth_timeout=10)
            sftp = self.ssh.get_client().open_sftp()
            sftp.get_channel().settimeout(120)
            self.ssh.sftp = sftp
            return sftp
        except Exception:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        try:
            if self.ssh is not None:
                if getattr(self.ssh, 'sftp', None) is not None:
                    self.ssh.sftp.close()
                if getattr(self.ssh, 'client', None) is not None:
                    self.ssh.client.close()
        finally:
            self.ssh = None
            _FILE_SEMAPHORE.release()


def _real_roots(sftp):
    roots = []
    for root in allowed_dirs():
        try:
            real = sftp.normalize(root)
        except IOError:
            continue
        if real != '/' and real not in roots:
            roots.append(real)
    return roots


def _check_real(sftp, real_path):
    if not any(_within(real_path, root) for root in _real_roots(sftp)):
        raise AuthorizationError('远程真实路径（解析符号链接后）不在允许的目录内')


def _inspect_upload(sftp, path):
    """Return the real target path for an upload after validating its parent directory."""
    parent, name = posixpath.split(path)
    try:
        real_parent = sftp.normalize(parent)
        parent_attr = sftp.stat(real_parent)
    except IOError:
        raise OperationError(f'目标目录不存在：{parent}') from None
    if not stat.S_ISDIR(parent_attr.st_mode):
        raise OperationError(f'目标上级路径不是目录：{parent}')
    target = posixpath.join(real_parent, name)
    _check_real(sftp, target)
    try:
        attr = sftp.lstat(target)
    except IOError:
        return target
    if stat.S_ISLNK(attr.st_mode):
        raise AuthorizationError('目标文件是符号链接，拒绝覆盖')
    if not stat.S_ISREG(attr.st_mode):
        raise OperationError('目标路径已存在且不是普通文件')
    return target


def _inspect_download(sftp, path):
    """Return (real_path, size) for a downloadable regular file."""
    try:
        real = sftp.normalize(path)
        attr = sftp.stat(real)
    except IOError:
        raise OperationError(f'远程文件不存在：{path}') from None
    _check_real(sftp, real)
    if not stat.S_ISREG(attr.st_mode):
        raise OperationError('远程路径不是普通文件')
    if attr.st_size > MAX_FILE_BYTES:
        raise OperationError('远程文件超过 1 GiB 下载上限')
    return real, attr.st_size


class Upload:
    """Streams into a hidden temp file and atomically renames it over the target on commit."""

    def __init__(self, host, path):
        self._conn = _connect(host)
        self._sftp = self._conn.__enter__()
        self._file = None
        try:
            self.target = _inspect_upload(self._sftp, path)
            parent, name = posixpath.split(self.target)
            self.temp = posixpath.join(parent, f'.{name}.moon-{secrets.token_hex(6)}.part')
            self._file = self._sftp.open(self.temp, 'wb')
            self._file.set_pipelined(True)
        except Exception:
            self.close()
            raise
        self._hash = hashlib.sha256()
        self.size = 0

    def write(self, data):
        self.size += len(data)
        if self.size > MAX_FILE_BYTES:
            raise TransferError('上传文件超过 1 GiB 上限', 413)
        self._hash.update(data)
        self._file.write(data)

    @property
    def sha256(self):
        return self._hash.hexdigest()

    def commit(self):
        self._file.close()
        self._file = None
        try:
            self._sftp.posix_rename(self.temp, self.target)
        except IOError:
            # Servers without posix-rename@openssh.com cannot overwrite; replace explicitly.
            try:
                self._sftp.remove(self.target)
            except IOError:
                pass
            self._sftp.rename(self.temp, self.target)
        self.temp = None

    def close(self):
        try:
            if self._file is not None:
                self._file.close()
            if getattr(self, 'temp', None):
                try:
                    self._sftp.remove(self.temp)
                except IOError:
                    pass
        finally:
            self._file = None
            if self._conn is not None:
                self._conn.__exit__(None, None, None)
                self._conn = None


class Download:
    def __init__(self, host, path):
        self._conn = _connect(host)
        self._sftp = self._conn.__enter__()
        self._file = None
        try:
            self.real, self.size = _inspect_download(self._sftp, path)
            self.name = posixpath.basename(self.real)
            self._file = self._sftp.open(self.real, 'rb')
        except Exception:
            self.close()
            raise
        self.sent = 0

    def read(self, size=DOWNLOAD_WINDOW):
        # readv pipelines 32 KiB SFTP requests for one bounded window; whole-file prefetch would
        # buffer up to 1 GiB in memory when the HTTP client reads slowly.
        remaining = self.size - self.sent
        if remaining <= 0:
            return b''
        data = b''.join(self._file.readv([(self.sent, min(size, remaining))]))
        if not data:
            raise OperationError('远程文件在下载过程中被截断')
        self.sent += len(data)
        return data

    def close(self):
        try:
            if self._file is not None:
                self._file.close()
        finally:
            self._file = None
            if self._conn is not None:
                self._conn.__exit__(None, None, None)
                self._conn = None


def monotonic_ms(started):
    return int((time.monotonic() - started) * 1000)
