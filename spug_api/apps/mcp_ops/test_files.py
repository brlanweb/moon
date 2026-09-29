"""File transfer link contract tests with an in-memory fake SFTP server (no network)."""
import hashlib
import posixpath
import socket
import stat
from types import SimpleNamespace
from unittest.mock import Mock, patch

from asgiref.sync import async_to_sync
from django.core.cache import cache
from django.test import TestCase

from apps.account.models import Role, User
from apps.host.models import Host
from apps.mcp_ops import files, service
from apps.mcp_ops.models import McpAuditLog
from apps.mcp_ops.test_security_contract import _require_isolation


class FakeFile:
    def __init__(self, fs, path, mode):
        self.fs, self.path, self.mode = fs, path, mode
        if 'w' in mode:
            fs.files[path] = b''

    def set_pipelined(self, value):
        pass

    def write(self, data):
        self.fs.files[self.path] += data

    def readv(self, chunks):
        data = self.fs.files[self.path]
        return [data[offset:offset + size] for offset, size in chunks]

    def close(self):
        pass


class FakeSftp:
    """Minimal POSIX-like tree: dirs, regular files and symlinks."""

    def __init__(self):
        self.dirs = {'/', '/tmp', '/tmp/sub', '/etc', '/data'}
        self.files = {'/tmp/a.txt': b'hello', '/etc/passwd': b'root'}
        self.links = {'/tmp/evil': '/etc', '/tmp/link.txt': '/etc/passwd'}
        self.closed = False

    def get_channel(self):
        return Mock()

    def normalize(self, path):
        parts, out = path.strip('/').split('/'), '/'
        for part in parts:
            if not part:
                continue
            out = posixpath.join(out, part)
            for _ in range(8):
                if out in self.links:
                    out = self.links[out]
        if out not in self.dirs and out not in self.files:
            raise IOError('missing')
        return out

    def _attr(self, path, follow):
        if not follow and path in self.links:
            return SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_size=0)
        if follow and path in self.links:
            path = self.normalize(path)
        if path in self.dirs:
            return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_size=0)
        if path in self.files:
            return SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_size=len(self.files[path]))
        raise IOError('missing')

    def stat(self, path):
        return self._attr(path, True)

    def lstat(self, path):
        return self._attr(path, False)

    def open(self, path, mode):
        return FakeFile(self, path, mode)

    def posix_rename(self, src, dst):
        self.files[dst] = self.files.pop(src)

    rename = posix_rename

    def remove(self, path):
        self.files.pop(path, None)

    def close(self):
        self.closed = True


class FileTransferTests(TestCase):
    def setUp(self):
        _require_isolation()
        cache.clear()
        self.enterContext(patch.object(socket.socket, 'connect',
                                       side_effect=AssertionError('Real network forbidden')))
        self.enterContext(patch.dict('os.environ', {'MOON_MCP_FILE_DIRS': '/tmp,/data'}))
        self.fs = FakeSftp()
        ssh = SimpleNamespace(arguments={}, client=Mock(), sftp=None)
        ssh.get_client = Mock(return_value=SimpleNamespace(open_sftp=lambda: self.fs))
        self.get_ssh = self.enterContext(patch.object(Host, 'get_ssh', return_value=ssh))
        self.user = User.objects.create(username='file-op', nickname='F', password_hash='x',
                                        type='default', is_active=True, is_deleted=False)
        role = Role.objects.create(name='file-role', page_perms={'system': {'mcp': ['use']}},
                                   group_perms=[])
        self.user.roles.add(role)
        self.host = Host.objects.create(name='files', hostname='192.0.2.30', port=22,
                                        username='test', is_verified=True, created_by=self.user)
        self.token, self.plaintext = service.create_token(self.user, 'files', 1)

    def link(self, path, mode):
        return files.create_link(self.token, self.host.id, path, mode, '203.0.113.1')

    def http(self, method, url, content=None, headers=None):
        path = '/mcp/files/' + url.rsplit('/files/', 1)[1]
        return async_to_sync(_call)(method, path, content, headers)

    def test_path_whitelist_and_traversal_rejected(self):
        for path in ('/etc/passwd', '/tmp/../etc/passwd', 'tmp/a.txt', '/tmp/', '/tmp',
                     '', '/tmp/a\n.txt', '/' + 'a' * 2000):
            with self.subTest(path=path):
                with self.assertRaises(service.AuthorizationError):
                    files.normalize_path(path)
        self.assertEqual(files.normalize_path('/tmp//sub/./x'), '/tmp/sub/x')

    def test_symlink_escape_rejected_at_link_creation(self):
        with self.assertRaises(service.AuthorizationError):
            self.link('/tmp/evil/passwd', files.DOWNLOAD)
        with self.assertRaises(service.AuthorizationError):
            self.link('/tmp/link.txt', files.DOWNLOAD)
        with self.assertRaises(service.AuthorizationError):
            self.link('/tmp/link.txt', files.UPLOAD)
        self.assertFalse(McpAuditLog.objects.filter(status='success').exists())
        self.assertTrue(McpAuditLog.objects.filter(operation='create_download_link',
                                                   status='rejected').exists())

    def test_missing_parent_and_oversize_download_rejected(self):
        with self.assertRaises(service.OperationError):
            self.link('/tmp/nope/x.txt', files.UPLOAD)
        self.fs.files['/tmp/big'] = b''
        with patch.object(files, 'MAX_FILE_BYTES', 0), self.assertRaises(service.OperationError):
            self.fs.files['/tmp/big'] = b'x'
            self.link('/tmp/big', files.DOWNLOAD)

    def test_upload_then_download_roundtrip_is_one_time_and_audited(self):
        up = self.link('/tmp/sub/new.bin', files.UPLOAD)
        self.assertEqual(up['method'], 'PUT')
        self.assertTrue(up['one_time'])
        self.assertNotIn(self.plaintext, str(up))
        body = b'moon-file-' * 1000
        response = self.http('PUT', up['url'], body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['sha256'], hashlib.sha256(body).hexdigest())
        self.assertEqual(self.fs.files['/tmp/sub/new.bin'], body)
        self.assertFalse(any('.part' in name for name in self.fs.files))
        self.assertEqual(self.http('PUT', up['url'], b'again').status_code, 404)

        down = self.link('/tmp/sub/new.bin', files.DOWNLOAD)
        self.assertEqual(self.http('HEAD', down['url']).status_code, 405)
        response = self.http('GET', down['url'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, body)
        self.assertIn("filename*=UTF-8''new.bin", response.headers['content-disposition'])
        self.assertEqual(self.http('GET', down['url']).status_code, 404)

        ops = set(McpAuditLog.objects.filter(status='success').values_list('operation', flat=True))
        self.assertTrue({'create_upload_link', 'upload_file', 'create_download_link',
                         'download_file'} <= ops)
        for log in McpAuditLog.objects.all():
            self.assertNotIn(up['url'].rsplit('/', 1)[1], str(log.__dict__))
            self.assertNotIn(down['url'].rsplit('/', 1)[1], str(log.__dict__))

    def test_mode_mismatch_and_garbage_links_rejected(self):
        up = self.link('/tmp/x.bin', files.UPLOAD)
        self.assertEqual(self.http('GET', up['url']).status_code, 404)
        self.assertEqual(self.http('GET', 'http://t/mcp/files/mft_garbage').status_code, 404)
        self.assertEqual(self.http('PUT', 'http://t/mcp/files/not-a-link', b'x').status_code, 404)

    def test_link_expiry_uses_30_minute_ttl(self):
        with patch.object(files.cache, 'set', wraps=files.cache.set) as setter:
            self.link('/tmp/x.bin', files.UPLOAD)
        self.assertEqual(setter.call_args.args[2], 30 * 60)
        cache.clear()  # simulate expiry
        # A link whose cache entry expired is indistinguishable from a used one.
        self.assertIsNone(files.peek_link('mft_anything'))

    def test_oversize_and_multipart_rejected_before_consuming_link(self):
        up = self.link('/tmp/x.bin', files.UPLOAD)
        response = self.http('PUT', up['url'], b'x',
                             headers={'Content-Length': str(files.MAX_FILE_BYTES + 1)})
        self.assertEqual(response.status_code, 413)
        response = self.http('POST', up['url'], b'x',
                             headers={'Content-Type': 'multipart/form-data; boundary=a'})
        self.assertEqual(response.status_code, 415)
        self.assertEqual(self.http('PUT', up['url'], b'ok').status_code, 200)

    def test_streamed_upload_over_limit_leaves_no_partial_file(self):
        up = self.link('/tmp/x.bin', files.UPLOAD)
        with patch.object(files, 'MAX_FILE_BYTES', 4):
            response = self.http('PUT', up['url'], b'123456')
        self.assertEqual(response.status_code, 413)
        self.assertNotIn('/tmp/x.bin', self.fs.files)
        self.assertFalse(any('.part' in name for name in self.fs.files))

    def test_deleted_or_expired_token_cannot_use_link(self):
        up = self.link('/tmp/x.bin', files.UPLOAD)
        service.delete_token(self.token, self.user)
        self.assertEqual(self.http('PUT', up['url'], b'x').status_code, 403)
        self.assertNotIn('/tmp/x.bin', self.fs.files)

    def test_permission_loss_blocks_claim(self):
        up = self.link('/tmp/x.bin', files.UPLOAD)
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.http('PUT', up['url'], b'x').status_code, 403)


async def _call(method, path, content, headers):
    from httpx2 import ASGITransport, AsyncClient
    from starlette.applications import Starlette
    from apps.mcp_ops.files_http import routes
    async with AsyncClient(transport=ASGITransport(app=Starlette(routes=routes)),
                           base_url='http://testserver') as client:
        return await client.request(method, path, content=content, headers=headers)
