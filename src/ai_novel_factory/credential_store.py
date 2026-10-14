"""Stage 62: user-scoped offline secret vault and non-secret connection settings.

Windows uses native DPAPI CurrentUser, never plaintext secret files. No cloud,
HTTP, token transmission or automatic provider execution occurs in this module.
Other platforms fail closed for persistent secrets unless a test protector is
explicitly injected. Encrypted files remain sensitive and must not be shared.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Protocol


class CredentialError(ValueError):
    """Public errors deliberately omit credentials, paths and subprocess output."""


class Protector(Protocol):
    def protect(self, value: bytes) -> bytes: ...
    def unprotect(self, value: bytes) -> bytes: ...


class WindowsDPAPI:
    """DPAPI CurrentUser with UI disabled. Only available on real Windows."""

    def __init__(self) -> None:
        if sys.platform != 'win32':
            raise CredentialError('Windows user protection is unavailable')

    @staticmethod
    def _operate(data: bytes, *, decrypt: bool) -> bytes:
        if sys.platform != 'win32':
            raise CredentialError('Windows user protection is unavailable')
        from ctypes import wintypes

        class DataBlob(ctypes.Structure):
            _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]

        if not isinstance(data, bytes) or not data or len(data) > 65536:
            raise CredentialError('invalid credential payload')
        input_buffer = ctypes.create_string_buffer(data)
        input_blob = DataBlob(len(data), ctypes.cast(input_buffer, ctypes.POINTER(ctypes.c_ubyte)))
        output_blob = DataBlob()
        crypt = ctypes.WinDLL('crypt32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        # CryptProtectData/UnprotectData use BOOL and pointer-sized arguments.
        function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
        if decrypt:
            function.argtypes = [ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.c_void_p,
                                 ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                                 ctypes.POINTER(DataBlob)]
            args = (ctypes.byref(input_blob), None, None, None, None, 0x1,
                    ctypes.byref(output_blob))
        else:
            function.argtypes = [ctypes.POINTER(DataBlob), wintypes.LPCWSTR,
                                 ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                 wintypes.DWORD, ctypes.POINTER(DataBlob)]
            args = (ctypes.byref(input_blob), 'AI Novel Factory local secret', None,
                    None, None, 0x1, ctypes.byref(output_blob))
        function.restype = wintypes.BOOL
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        if not function(*args):
            raise CredentialError('Windows user protection operation failed')
        try:
            if output_blob.cbData > 65536:
                raise CredentialError('invalid protected credential size')
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            kernel.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))

    def protect(self, value: bytes) -> bytes:
        return self._operate(value, decrypt=False)

    def unprotect(self, value: bytes) -> bytes:
        return self._operate(value, decrypt=True)


_ALIAS = re.compile(r'[a-z][a-z0-9_-]{0,63}\Z')


def _alias(name: str) -> str:
    if type(name) is not str or not _ALIAS.fullmatch(name):
        raise CredentialError('invalid credential identifier')
    return name


def _directory(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise CredentialError('unsafe credential directory')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise CredentialError('unsafe credential directory')
    if os.name == 'posix':
        path.chmod(0o700)


def _atomic_private_write(path: Path, content: bytes) -> None:
    """Replace a single file without opening a symlink target for writing."""
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise CredentialError('unsafe credential file')
    temporary: str | None = None
    try:
        fd, temporary = tempfile.mkstemp(prefix='.anf-', dir=str(path.parent))
        with os.fdopen(fd, 'wb') as stream:
            if os.name == 'posix':
                os.fchmod(stream.fileno(), stat.S_IRUSR | stat.S_IWUSR)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError:
        raise CredentialError('secure local file operation failed') from None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


class CredentialVault:
    """Explicit storage of DPAPI-encrypted tokens; no plaintext in settings/logs."""

    def __init__(self, directory: str | Path, *, protector: Protector | None = None):
        self._root = Path(directory).absolute()
        self._protector = protector if protector is not None else WindowsDPAPI()
        if not callable(getattr(self._protector, 'protect', None)) or not callable(getattr(self._protector, 'unprotect', None)):
            raise CredentialError('invalid credential protection backend')

    def _path(self, name: str) -> Path:
        name = _alias(name)
        return self._root / (hashlib.sha256(name.encode('ascii')).hexdigest() + '.secret')

    def store(self, name: str, secret: str, *, explicitly_allowed: bool = False) -> None:
        path = self._path(name)
        if explicitly_allowed is not True:
            raise CredentialError('explicit credential storage approval required')
        if type(secret) is not str or not secret.strip() or len(secret) > 8192 or any(ch in secret for ch in '\x00\r\n'):
            raise CredentialError('invalid credential')
        try:
            protected = self._protector.protect(secret.encode('utf-8'))
            if not isinstance(protected, bytes) or not protected or len(protected) > 65536:
                raise CredentialError('invalid protected credential')
            _directory(self._root)
            _atomic_private_write(path, protected)
        except CredentialError:
            raise
        except Exception:
            raise CredentialError('credential protection failed') from None

    def retrieve(self, name: str, *, explicitly_allowed: bool = False) -> str | None:
        path = self._path(name)
        if explicitly_allowed is not True:
            raise CredentialError('explicit credential access approval required')
        if not self._root.exists():
            return None
        if self._root.is_symlink() or not self._root.is_dir() or path.is_symlink():
            raise CredentialError('unsafe credential storage')
        try:
            if not path.exists():
                return None
            if not path.is_file() or path.stat().st_size > 65536:
                raise CredentialError('invalid protected credential file')
            plaintext = self._protector.unprotect(path.read_bytes())
            if not isinstance(plaintext, bytes) or len(plaintext) > 8192:
                raise CredentialError('invalid decrypted credential')
            return plaintext.decode('utf-8')
        except CredentialError:
            raise
        except Exception:
            raise CredentialError('credential access failed') from None

    def delete(self, name: str, *, explicitly_allowed: bool = False) -> bool:
        path = self._path(name)
        if explicitly_allowed is not True:
            raise CredentialError('explicit credential deletion approval required')
        if self._root.is_symlink() or path.is_symlink():
            raise CredentialError('unsafe credential storage')
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError:
            raise CredentialError('credential deletion failed') from None

    def status(self, name: str) -> dict[str, bool | str]:
        path = self._path(name)
        if self._root.is_symlink() or path.is_symlink():
            raise CredentialError('unsafe credential storage')
        return {'identifier': name, 'stored': path.is_file()}


@dataclass(frozen=True, slots=True)
class LocalConnectionSettings:
    """Non-secret, non-network connection configuration; default disabled."""
    provider: str = 'disabled'
    executable: str = ''
    arguments: tuple[str, ...] = ()
    timeout_seconds: float = 15.0
    # Deliberately no api_key, token, URI, endpoint, or permanent approval field.

    def __post_init__(self) -> None:
        if self.provider not in ('disabled', 'mock', 'local-executable'):
            raise CredentialError('remote providers are not supported')
        if type(self.executable) is not str or '\x00' in self.executable or len(self.executable) > 4096:
            raise CredentialError('invalid local executable')
        if type(self.arguments) is not tuple or len(self.arguments) > 32 or any(
            type(item) is not str or '\x00' in item or len(item) > 4096 for item in self.arguments
        ):
            raise CredentialError('invalid local arguments')
        if type(self.timeout_seconds) not in (int, float) or not 0 < self.timeout_seconds <= 120:
            raise CredentialError('invalid local timeout')
        # Arguments are written to JSON and may appear in process listings.
        # Never allow a key/token/password/secret flag into persistent settings.
        if any(re.search(r'(?i)(?:api[-_]?key|token|password|secret|credential)', item)
               for item in self.arguments):
            raise CredentialError('secret-bearing local arguments are prohibited')
        if self.provider == 'local-executable':
            if not Path(self.executable).is_absolute():
                raise CredentialError('absolute local executable path required')
        elif self.executable or self.arguments:
            raise CredentialError('executable only available for local provider')

    def safe_status(self) -> dict[str, bool | str]:
        return {'provider': self.provider, 'local_executable_configured': bool(self.executable),
                'requires_explicit_run_approval': self.provider == 'local-executable'}


def save_connection_settings(path: str | Path, settings: LocalConnectionSettings) -> None:
    if not isinstance(settings, LocalConnectionSettings):
        raise CredentialError('invalid connection settings')
    target = Path(path).absolute()
    if target.parent.is_symlink():
        raise CredentialError('unsafe settings directory')
    _directory(target.parent)
    data = {'schema': 1, 'provider': settings.provider, 'executable': settings.executable,
            'arguments': list(settings.arguments), 'timeout_seconds': settings.timeout_seconds}
    _atomic_private_write(target, (json.dumps(data, ensure_ascii=False) + '\n').encode('utf-8'))


def load_connection_settings(path: str | Path) -> LocalConnectionSettings:
    target = Path(path).absolute()
    if target.is_symlink():
        raise CredentialError('unsafe settings file')
    if not target.exists():
        return LocalConnectionSettings()
    try:
        if target.stat().st_size > 32768:
            raise CredentialError('oversized connection settings')
        data = json.loads(target.read_text(encoding='utf-8'))
        if type(data) is not dict or set(data) != {'schema', 'provider', 'executable', 'arguments', 'timeout_seconds'} or type(data['schema']) is not int or data['schema'] != 1 or type(data['arguments']) is not list:
            raise CredentialError('invalid connection settings format')
        return LocalConnectionSettings(data['provider'], data['executable'],
                                       tuple(data['arguments']), data['timeout_seconds'])
    except CredentialError:
        raise
    except Exception:
        raise CredentialError('invalid connection settings file') from None


def connect_local_provider(settings: LocalConnectionSettings, *, explicitly_allowed: bool = False):
    """Return local adapter; this does not generate content or make a network call."""
    from .local_models import LocalExecutableProvider, MockSceneProvider
    if not isinstance(settings, LocalConnectionSettings):
        raise CredentialError('invalid connection settings')
    if settings.provider == 'disabled':
        raise CredentialError('model connection is disabled')
    if settings.provider == 'mock':
        return MockSceneProvider()
    if explicitly_allowed is not True:
        raise CredentialError('local executable approval required')
    try:
        return LocalExecutableProvider(settings.executable, arguments=settings.arguments,
                                       timeout_seconds=settings.timeout_seconds,
                                       explicitly_allowed=True)
    except Exception:
        raise CredentialError('invalid local model connection') from None
