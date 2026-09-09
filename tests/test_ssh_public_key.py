import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

from libs.ssh import SSH


class LocalShellSSH(SSH):
    """Run the installer in a temporary filesystem; replace only the remote host boundary."""
    def __init__(self, home, banner='SSH-2.0-OpenSSH_9.6', root_openwrt=False):
        super().__init__('unused.invalid')
        self.home = home
        self.root_openwrt = root_openwrt
        self.transport = SimpleNamespace(remote_version=banner)

    def get_client(self):
        return SimpleNamespace(get_transport=lambda: self.transport)

    def exec_command_raw(self, command, environment=None):
        if command.startswith('test '):
            return (0 if self.root_openwrt else 1), ''
        command = command.replace('/etc/dropbear', str(self.home / 'etc/dropbear'))
        result = subprocess.run(
            ['/bin/sh', '-c', command], env={**os.environ, 'HOME': str(self.home)},
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode, result.stdout + result.stderr


class PublicKeyInstallationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='moon-key-test-')
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.key = 'ssh-rsa TEST_PUBLIC_KEY moon'

    def test_openwrt_root_dropbear_uses_system_authorized_keys(self):
        ssh = LocalShellSSH(self.home, 'SSH-2.0-dropbear', root_openwrt=True)
        ssh.add_public_key(self.key)
        target = self.home / 'etc/dropbear/authorized_keys'
        self.assertTrue(target.is_file())
        self.assertIn(self.key, target.read_text().splitlines())
        self.assertFalse((self.home / '.ssh/authorized_keys').exists())

    def test_openwrt_with_openssh_keeps_home_authorized_keys(self):
        ssh = LocalShellSSH(self.home, root_openwrt=True)
        ssh.add_public_key(self.key)
        self.assertIn(self.key, (self.home / '.ssh/authorized_keys').read_text().splitlines())
        self.assertFalse((self.home / 'etc/dropbear').exists())

    def test_other_dropbear_users_keep_home_authorized_keys(self):
        ssh = LocalShellSSH(self.home, 'SSH-2.0-dropbear', root_openwrt=False)
        ssh.add_public_key(self.key)
        self.assertIn(self.key, (self.home / '.ssh/authorized_keys').read_text().splitlines())
        self.assertFalse((self.home / 'etc/dropbear').exists())

    def test_existing_directory_permissions_are_corrected(self):
        directory = self.home / '.ssh'
        directory.mkdir()
        directory.chmod(0o777)
        LocalShellSSH(self.home).add_public_key(self.key)
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual((directory / 'authorized_keys').stat().st_mode & 0o777, 0o600)

    def test_key_without_final_newline_is_preserved_on_its_own_line(self):
        directory = self.home / '.ssh'
        directory.mkdir()
        target = directory / 'authorized_keys'
        target.write_text('ssh-ed25519 EXISTING_USER_KEY')
        LocalShellSSH(self.home).add_public_key(self.key)
        self.assertEqual(target.read_text().splitlines(), ['ssh-ed25519 EXISTING_USER_KEY', self.key])

    def test_repeated_installation_does_not_duplicate_keys(self):
        ssh = LocalShellSSH(self.home)
        ssh.add_public_key(self.key)
        target = self.home / '.ssh/authorized_keys'
        first = target.read_bytes()
        ssh.add_public_key(self.key)
        self.assertEqual(target.read_bytes(), first)
        self.assertEqual(target.read_text().splitlines().count(self.key), 1)

    def test_key_comment_is_not_executed_by_the_shell(self):
        key = 'ssh-rsa TEST_PUBLIC_KEY "$(touch "$HOME/injected")" it\'s safe'
        LocalShellSSH(self.home).add_public_key(key)
        self.assertFalse((self.home / 'injected').exists())
        self.assertIn(key, (self.home / '.ssh/authorized_keys').read_text().splitlines())

    def test_rejects_multiple_keys_before_writing(self):
        with self.assertRaises(ValueError):
            LocalShellSSH(self.home).add_public_key(self.key + '\nssh-rsa SECOND_KEY')
        self.assertFalse((self.home / '.ssh').exists())


if __name__ == '__main__':
    unittest.main()
