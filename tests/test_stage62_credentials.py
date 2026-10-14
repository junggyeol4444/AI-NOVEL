"""Stage 62: offline secret protection and safe connection management."""
from dataclasses import replace
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory.credential_store import (
    CredentialError, CredentialVault, WindowsDPAPI, LocalConnectionSettings,
    save_connection_settings, load_connection_settings, connect_local_provider,
)
from ai_novel_factory.local_models import MockSceneProvider, LocalExecutableProvider


class TestProtector:
    """Reversible test stub, deliberately NOT cryptographically secure."""
    def protect(self, data):
        return b'FAKE-PROTECTED:' + bytes(value ^ 0x55 for value in data)

    def unprotect(self, data):
        if not data.startswith(b'FAKE-PROTECTED:'):
            raise ValueError('test decode failure WITH SECRET IN IT')
        return bytes(value ^ 0x55 for value in data[len(b'FAKE-PROTECTED:'):])


class SecretStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'secrets'
        self.vault = CredentialVault(self.root, protector=TestProtector())

    def test_default_vault_fails_closed_without_windows(self):
        if sys.platform != 'win32':
            with self.assertRaises(CredentialError):
                CredentialVault(self.root)
            with self.assertRaises(CredentialError):
                WindowsDPAPI()

    def test_explicit_opt_in_for_store_read_delete(self):
        with self.assertRaises(CredentialError):
            self.vault.store('model_key', 'secret')
        self.vault.store('model_key', 'secret', explicitly_allowed=True)
        with self.assertRaises(CredentialError):
            self.vault.retrieve('model_key')
        with self.assertRaises(CredentialError):
            self.vault.delete('model_key')
        self.assertEqual(self.vault.retrieve('model_key', explicitly_allowed=True), 'secret')
        self.assertTrue(self.vault.delete('model_key', explicitly_allowed=True))
        self.assertFalse(self.vault.delete('model_key', explicitly_allowed=True))

    def test_encrypted_on_disk_without_plaintext_or_name(self):
        token = 'sk-super-sensitive-고유값'
        self.vault.store('provider_token', token, explicitly_allowed=True)
        files = list(self.root.iterdir())
        self.assertEqual(len(files), 1)
        self.assertNotIn('provider_token', files[0].name)
        self.assertNotIn(token.encode('utf8'), files[0].read_bytes())
        self.assertEqual(self.vault.retrieve('provider_token', explicitly_allowed=True), token)
        self.assertEqual(self.vault.status('provider_token'), {'identifier':'provider_token','stored':True})

    def test_reopen_and_replace(self):
        self.vault.store('a', 'first', explicitly_allowed=True)
        other = CredentialVault(self.root, protector=TestProtector())
        self.assertEqual(other.retrieve('a', explicitly_allowed=True), 'first')
        other.store('a', 'second', explicitly_allowed=True)
        self.assertEqual(self.vault.retrieve('a', explicitly_allowed=True), 'second')

    def test_missing_read_does_not_create_directory(self):
        self.assertIsNone(self.vault.retrieve('missing', explicitly_allowed=True))
        self.assertFalse(self.root.exists())
        self.assertEqual(self.vault.status('missing')['stored'], False)

    def test_rejects_bad_aliases_without_path_traversal(self):
        for alias in ('../escape', 'x/y', '.env', 'UPPER', '', 'a'*65, None, 'a\\b', 'a\x00b'):
            with self.subTest(alias=alias), self.assertRaises(CredentialError):
                self.vault.store(alias, 'secret', explicitly_allowed=True)
        self.assertFalse(self.root.exists())

    def test_rejects_blank_controls_or_overlong(self):
        for secret in ('', ' ', 'abc\nxyz', 'abc\rxyz', 'abc\x00xyz', 'x'*8193, None):
            with self.subTest(), self.assertRaises(CredentialError):
                self.vault.store('a', secret, explicitly_allowed=True)

    def test_protected_file_is_private_on_posix(self):
        self.vault.store('a', 'token', explicitly_allowed=True)
        if os.name == 'posix':
            self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
            self.assertEqual(next(self.root.iterdir()).stat().st_mode & 0o777, 0o600)

    def test_rejects_symlink_directory(self):
        try:
            self.root.symlink_to(self.temp.name, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('symlinks unavailable')
        with self.assertRaises(CredentialError):
            self.vault.store('a', 'secret', explicitly_allowed=True)

    def test_rejects_symlink_secret(self):
        self.root.mkdir()
        target = Path(self.temp.name) / 'do-not-touch'
        target.write_text('intact')
        try:
            self.vault._path('a').symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest('symlinks unavailable')
        with self.assertRaises(CredentialError):
            self.vault.store('a', 'secret', explicitly_allowed=True)
        with self.assertRaises(CredentialError):
            self.vault.retrieve('a', explicitly_allowed=True)
        self.assertEqual(target.read_text(), 'intact')

    def test_corrupt_ciphertext_raises_without_leaking(self):
        self.vault.store('a', 'SECRET-LEAK-CHECK', explicitly_allowed=True)
        self.vault._path('a').write_bytes(b'broken')
        with self.assertRaises(CredentialError) as ctx:
            self.vault.retrieve('a', explicitly_allowed=True)
        self.assertNotIn('SECRET', str(ctx.exception))
        self.assertNotIn('test decode failure', str(ctx.exception))

    def test_backend_errors_sanitized_and_no_plaintext_files(self):
        class Faulty:
            def protect(self, value):
                raise RuntimeError('YOUR-SECRET-IN-ERROR')
            def unprotect(self, value):
                raise RuntimeError('YOUR-SECRET-IN-ERROR')
        vault = CredentialVault(self.root, protector=Faulty())
        with self.assertRaises(CredentialError) as ctx:
            vault.store('a', 'token', explicitly_allowed=True)
        self.assertNotIn('YOUR-SECRET', str(ctx.exception))
        self.assertFalse(self.root.exists())

    def test_binary_oversized_protected_block_rejected(self):
        class TooLarge(TestProtector):
            def protect(self, data): return b'a' * 65537
        with self.assertRaises(CredentialError):
            CredentialVault(self.root, protector=TooLarge()).store('a','secret',explicitly_allowed=True)

    def test_offline_operations_do_not_invoke_socket(self):
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('no network')):
            self.vault.store('a', 'secret', explicitly_allowed=True)
            self.assertEqual(self.vault.retrieve('a', explicitly_allowed=True), 'secret')
            self.vault.delete('a', explicitly_allowed=True)


class ConnectionSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'settings' / 'model.json'

    def test_default_disabled_and_no_connection(self):
        conf = load_connection_settings(self.path)
        self.assertEqual(conf.provider, 'disabled')
        self.assertFalse(self.path.exists())
        with self.assertRaises(CredentialError):
            connect_local_provider(conf)

    def test_mock_round_trip_without_secrets(self):
        settings = LocalConnectionSettings(provider='mock')
        save_connection_settings(self.path, settings)
        self.assertEqual(load_connection_settings(self.path), settings)
        self.assertIsInstance(connect_local_provider(settings), MockSceneProvider)
        data = self.path.read_text()
        self.assertNotIn('api_key', data)
        self.assertNotIn('token', data)
        self.assertNotIn('approval', data)

    def test_local_executable_requires_fresh_approval(self):
        settings = LocalConnectionSettings(provider='local-executable', executable=str(Path(sys.executable).resolve()),
                                           arguments=('-c','print(123)'), timeout_seconds=5)
        save_connection_settings(self.path, settings)
        loaded = load_connection_settings(self.path)
        self.assertEqual(loaded, settings)
        self.assertTrue(loaded.safe_status()['requires_explicit_run_approval'])
        with self.assertRaises(CredentialError):
            connect_local_provider(loaded)
        self.assertIsInstance(connect_local_provider(loaded, explicitly_allowed=True), LocalExecutableProvider)

    def test_remote_endpoints_rejected(self):
        for name in ('https', 'openai', 'remote', 'api', 'custom'):
            with self.subTest(name=name), self.assertRaises(CredentialError):
                LocalConnectionSettings(provider=name)

    def test_url_cannot_be_executable(self):
        with self.assertRaises(CredentialError):
            LocalConnectionSettings(provider='local-executable', executable='https://example.org/api')

    def test_malformed_config_and_unexpected_key_fail_closed(self):
        self.path.parent.mkdir()
        for data in ('not JSON', '{}', json.dumps({'schema':1,'provider':'mock','executable':'',
                'arguments':[],'timeout_seconds':15,'api_key':'plaintext'}),
                json.dumps({'schema':2,'provider':'mock','executable':'','arguments':[], 'timeout_seconds':15})):
            self.path.write_text(data)
            with self.subTest(data=data[:20]), self.assertRaises(CredentialError):
                load_connection_settings(self.path)

    def test_bad_arguments_timeouts_rejected(self):
        for options in ({'arguments':['-V']}, {'arguments':('x\x00y',)},
                        {'timeout_seconds':True}, {'timeout_seconds':0},
                        {'timeout_seconds':121}, {'arguments':('a',)*33}):
            with self.subTest(options=options), self.assertRaises(CredentialError):
                LocalConnectionSettings(provider='mock', **options)

    def test_secret_bearing_command_arguments_rejected(self):
        for argument in ('--api-key=veryprivate', '--TOKEN', '--password', '--secret-file'):
            with self.subTest(argument=argument), self.assertRaises(CredentialError):
                LocalConnectionSettings(provider='local-executable',
                                        executable=str(Path(sys.executable).resolve()),
                                        arguments=(argument,))

    def test_only_local_provider_may_have_executable(self):
        with self.assertRaises(CredentialError):
            LocalConnectionSettings(provider='disabled', executable=str(Path(sys.executable).resolve()))

    def test_symlink_config_rejected(self):
        target = Path(self.temp.name) / 'target'
        target.write_text('original')
        self.path.parent.mkdir()
        try:
            self.path.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest('symlinks unavailable')
        with self.assertRaises(CredentialError):
            save_connection_settings(self.path, LocalConnectionSettings(provider='mock'))
        with self.assertRaises(CredentialError):
            load_connection_settings(self.path)
        self.assertEqual(target.read_text(), 'original')

    def test_settings_are_private_on_posix(self):
        save_connection_settings(self.path, LocalConnectionSettings(provider='mock'))
        if os.name == 'posix':
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)

    def test_invalid_provider_not_executed(self):
        with self.assertRaises(CredentialError):
            connect_local_provider(object())

    def test_no_network_when_settings_loaded_and_mock_connected(self):
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('network called')):
            save_connection_settings(self.path, LocalConnectionSettings(provider='mock'))
            connect_local_provider(load_connection_settings(self.path))
