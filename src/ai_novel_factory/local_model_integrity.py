"""Explicit, offline executable/GGUF byte binding for one local authoring launch.

Only an author click may compute/approve this identity. Never invokes the model,
installs software, downloads weights, modifies project data or grants publishing
rights. The fingerprint is memory-only; private paths are excluded from repr.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
import json
import os
import shlex


class ModelIntegrityError(ValueError):
    """Public errors never contain paths, model arguments or private text."""


@dataclass(frozen=True)
class LocalModelArtifact:
    path: Path = field(repr=False)
    size: int
    sha256_hex: str = field(repr=False)
    kind: str


@dataclass(frozen=True)
class LocalModelIdentity:
    executable: LocalModelArtifact = field(repr=False)
    gguf: LocalModelArtifact = field(repr=False)
    arguments: tuple[str, ...] = field(repr=False)
    fingerprint: str = field(repr=False)
    model_downloaded: bool = False
    model_executed: bool = False
    quality_certified: bool = False
    publication_approved: bool = False


class ApprovedModelLaunch:
    """An in-memory, single-use lease, scoped to a selected existing project."""
    def __init__(self, identity: LocalModelIdentity, database_path: str,
                 project_id: str):
        self.identity = identity
        self.database_path = _absolute_local(database_path)
        if type(project_id) is not str or not project_id:
            raise ModelIntegrityError('기존 작품을 먼저 선택해야 합니다.')
        self.project_id = project_id
        self.used = False

    def consume(self, executable: str, arguments: str,
                database_path: str, project_id: str) -> None:
        if self.used or self.project_id != project_id:
            raise ModelIntegrityError('이번 로컬 모델 실행을 다시 승인해야 합니다.')
        if self.database_path != _absolute_local(database_path):
            raise ModelIntegrityError('작품 SQLite 선택이 변경되었습니다.')
        verify_local_model_identity(self.identity, executable, arguments)
        # Mark as used BEFORE constructing the worker; failures cannot reuse it.
        self.used = True


def _absolute_local(raw: str) -> Path:
    if type(raw) is not str or not raw or '\\x00' in raw or raw.startswith(
            ('\\\\\\\\', '//', 'file:', 'http:', 'https:')):
        raise ModelIntegrityError('사용자가 직접 선택한 로컬 절대 경로가 필요합니다.')
    path = Path(raw)
    if not path.is_absolute() or path.is_symlink():
        raise ModelIntegrityError('심볼릭 링크가 아닌 로컬 절대 경로를 선택하세요.')
    return path.resolve(strict=False)


def _parse_args(raw: str) -> tuple[str, ...]:
    if type(raw) is not str or len(raw) > 8192:
        raise ModelIntegrityError('로컬 실행 인수 형식이 올바르지 않습니다.')
    try:
        values = tuple(shlex.split(raw, posix=False if os.name == 'nt' else True))
    except ValueError:
        raise ModelIntegrityError('로컬 실행 인수 형식이 올바르지 않습니다.') from None
    if len(values) > 100:
        raise ModelIntegrityError('로컬 실행 인수가 너무 많습니다.')
    return values


def _gguf_arg(args: tuple[str, ...]) -> str:
    choices = []
    for i, arg in enumerate(args):
        if arg == '--gguf':
            if i + 1 >= len(args):
                raise ModelIntegrityError('GGUF 파일 경로를 직접 선택해야 합니다.')
            choices.append(args[i + 1])
        elif arg.startswith('--gguf='):
            choices.append(arg.partition('=')[2])
    if len(choices) != 1:
        raise ModelIntegrityError('이번 실행에 승인할 GGUF 파일을 정확히 하나 선택하세요.')
    return choices[0].strip('"')


def _digest_file(raw: str, *, kind: str, limit: int) -> LocalModelArtifact:
    path = _absolute_local(raw)
    if not path.is_file():
        raise ModelIntegrityError('선택한 로컬 모델 파일을 찾을 수 없습니다.')
    try:
        first = path.stat()
        if first.st_size < 1 or first.st_size > limit:
            raise ModelIntegrityError('선택한 파일 크기가 허용 범위를 벗어났습니다.')
        digest = sha256()
        total = 0
        with path.open('rb') as stream:
            while True:
                chunk = stream.read(4 * 1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise ModelIntegrityError('선택한 파일 크기 제한을 초과했습니다.')
                digest.update(chunk)
        last = path.stat()
    except OSError:
        raise ModelIntegrityError('선택한 로컬 파일을 읽을 수 없습니다.') from None
    if (total != first.st_size or total != last.st_size
            or first.st_mtime_ns != last.st_mtime_ns
            or first.st_ino != last.st_ino):
        raise ModelIntegrityError('모델 파일이 확인 도중 변경되었습니다.')
    return LocalModelArtifact(path, total, digest.hexdigest(), kind)


def capture_local_model_identity(executable: str, arguments: str) -> LocalModelIdentity:
    args = _parse_args(arguments)
    gguf = _gguf_arg(args)
    exe = _digest_file(executable, kind='EXECUTABLE', limit=2 * 1024**3)
    model = _digest_file(gguf, kind='GGUF', limit=64 * 1024**3)
    if model.path.suffix.lower() != '.gguf' or exe.path == model.path:
        raise ModelIntegrityError('선택한 GGUF/실행 파일을 구분할 수 없습니다.')
    # Full paths are used ONLY for the private in-memory lease, not displayed.
    payload = (str(exe.path), exe.size, exe.sha256_hex,
               str(model.path), model.size, model.sha256_hex, args)
    fingerprint = sha256(json.dumps(payload, ensure_ascii=False,
        separators=(',', ':')).encode('utf-8')).hexdigest()
    return LocalModelIdentity(exe, model, args, fingerprint)


def verify_local_model_identity(identity: LocalModelIdentity,
                                executable: str, arguments: str) -> None:
    if type(identity) is not LocalModelIdentity:
        raise ModelIntegrityError('현재 실행할 로컬 GGUF의 새 확인이 필요합니다.')
    current = capture_local_model_identity(executable, arguments)
    if current.fingerprint != identity.fingerprint:
        raise ModelIntegrityError('승인한 실행 파일 또는 GGUF 바이트가 변경되었습니다.')
