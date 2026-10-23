"""Opt-in, private scene checkpoints for interrupted local AI generation.

These are newly generated, unapproved AI drafts, NOT the user's manuscript.
No source work, GGUF, SQLite row, publication approval, or model permission is
written or changed here. A new explicit model-run approval is always required.
Checkpoints have a digest for accidental corruption detection, not a signature.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any


MAX_STAGE_BYTES = 500_000
MAX_STAGE_FILE_BYTES = 800_000
MAX_SCENES = 20


class SceneCheckpointError(ValueError):
    """Sanitized errors: never include local paths or generated prose."""


def _digest(value: object) -> str:
    return sha256(repr(value).encode('utf-8', 'surrogatepass')).hexdigest()


def _identity(database_path: str | Path, project_id: str) -> str:
    path = Path(database_path)
    if not path.is_absolute() or path.is_symlink() or not project_id:
        raise SceneCheckpointError('현재 작품 DB의 로컬 위치를 확인할 수 없습니다.')
    return _digest((str(path.resolve()), project_id))


def _root(value: str | Path, *, create: bool) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.is_symlink():
        raise SceneCheckpointError('장면 임시 저장 폴더를 확인할 수 없습니다.')
    if create:
        try:
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError:
            raise SceneCheckpointError('로컬 장면 임시 저장 폴더를 만들지 못했습니다.') from None
    if not path.is_dir() or path.is_symlink():
        raise SceneCheckpointError('장면 임시 저장 폴더를 확인할 수 없습니다.')
    return path


@dataclass(frozen=True)
class SceneCheckpointOverview:
    episode: int
    checkpoint_sets: int
    unverified_stage_files: int
    recovered_or_approved: bool = False


@dataclass(frozen=True)
class SceneCheckpointStore:
    """Append-only stage files. Existing stages are never silently replaced."""
    root: Path = field(repr=False)
    database_path: Path = field(repr=False)
    project_id: str = field(repr=False)
    episode: int
    consent_fingerprint: str = field(repr=False)
    source_stamp: object = field(repr=False)
    plan_stamp: object = field(repr=False)
    _key: str = field(init=False, repr=False)
    _identity: dict[str, Any] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if (type(self.episode) is not int or not 1 <= self.episode <= 1000
                or type(self.consent_fingerprint) is not str
                or len(self.consent_fingerprint) != 64
                or any(c not in '0123456789abcdef' for c in self.consent_fingerprint)):
            raise SceneCheckpointError('장면 재개 승인 정보가 올바르지 않습니다.')
        project_hash = _identity(self.database_path, self.project_id)
        identity = dict(
            version=1, project=project_hash, episode=self.episode,
            source=_digest(self.source_stamp), plan=_digest(self.plan_stamp),
            consent=self.consent_fingerprint,
        )
        payload = json.dumps(identity, sort_keys=True, separators=(',', ':'))
        key = sha256(payload.encode('ascii')).hexdigest()
        object.__setattr__(self, '_key', key)
        object.__setattr__(self, '_identity', identity)

    @property
    def directory(self) -> Path:
        # Directory name contains hashes and episode number only.
        return self.root / (self._identity['project'][:20]
                            + f'_{self.episode:04d}_' + self._key[:32])

    def _stage_path(self, stage: int) -> Path:
        if type(stage) is not int or not 0 <= stage <= MAX_SCENES:
            raise SceneCheckpointError('장면 번호가 올바르지 않습니다.')
        return self.directory / f'{stage:02d}.json'

    def load_stage(self, stage: int) -> str | None:
        """Fail closed for corrupt, stale, symlinked, or mismatched stages."""
        path = self._stage_path(stage)
        if not path.exists() and not path.is_symlink():
            return None
        if path.is_symlink() or not path.is_file():
            raise SceneCheckpointError('임시 장면 파일을 신뢰할 수 없습니다.')
        try:
            if path.stat().st_size > MAX_STAGE_FILE_BYTES:
                raise SceneCheckpointError('임시 장면 파일 크기가 올바르지 않습니다.')
            flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
            fd = os.open(path, flags)
            with os.fdopen(fd, 'rb') as stream:
                raw = stream.read(MAX_STAGE_FILE_BYTES + 1)
            if len(raw) > MAX_STAGE_FILE_BYTES:
                raise SceneCheckpointError('임시 장면 파일 크기가 올바르지 않습니다.')
            item = json.loads(raw.decode('utf-8'))
            text = item.get('text')
            if (type(item) is not dict or item.get('identity') != self._identity
                    or item.get('stage') != stage or type(text) is not str
                    or not text.strip() or len(text.encode('utf-8')) > MAX_STAGE_BYTES
                    or item.get('text_sha256') != sha256(text.encode('utf-8')).hexdigest()
                    or item.get('approval') != 'UNAPPROVED_AI_DRAFT'):
                raise SceneCheckpointError('임시 장면 무결성 또는 설정이 일치하지 않습니다.')
            return text
        except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
            raise SceneCheckpointError('임시 장면을 확인할 수 없어 자동 재개를 차단했습니다.') from None

    def save_stage(self, stage: int, text: str) -> None:
        """Create one immutable stage after the caller rechecks author state."""
        path = self._stage_path(stage)
        if type(text) is not str or not text.strip() or len(text.encode('utf-8')) > MAX_STAGE_BYTES:
            raise SceneCheckpointError('로컬 생성 장면의 저장 크기 제한을 초과했습니다.')
        if path.exists() or path.is_symlink():
            if self.load_stage(stage) == text:
                return
            raise SceneCheckpointError('이미 저장된 임시 장면이 다릅니다. 자동 덮어쓰지 않습니다.')
        parent = _root(self.root, create=True)
        directory = self.directory
        try:
            directory.mkdir(mode=0o700, exist_ok=True)
            if directory.is_symlink() or not directory.is_dir() or directory.parent != parent:
                raise SceneCheckpointError('임시 장면 저장 폴더를 신뢰할 수 없습니다.')
            record = dict(identity=self._identity, stage=stage, text=text,
                          text_sha256=sha256(text.encode('utf-8')).hexdigest(),
                          approval='UNAPPROVED_AI_DRAFT')
            raw = json.dumps(record, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':')).encode('utf-8')
            if len(raw) > MAX_STAGE_FILE_BYTES:
                raise SceneCheckpointError('임시 장면 저장 크기 제한을 초과했습니다.')
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
            fd = os.open(path, flags, 0o600)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException:
                path.unlink(missing_ok=True)
                raise
        except SceneCheckpointError:
            raise
        except (OSError, ValueError):
            raise SceneCheckpointError('임시 장면 저장에 실패했습니다. 원고 DB는 변경하지 않았습니다.') from None


def list_checkpoint_overviews(root: str | Path, *, database_path: str | Path,
                              project_id: str) -> tuple[SceneCheckpointOverview, ...]:
    """Show only counts. Never expose cached text or treat a file as valid."""
    project_prefix = _identity(database_path, project_id)[:20]
    directory = Path(root)
    if not directory.exists():
        return ()
    _root(directory, create=False)
    counts: dict[int, list[int]] = {}
    try:
        for folder in directory.glob(project_prefix + '_*'):
            if folder.is_symlink() or not folder.is_dir():
                continue
            parts = folder.name.split('_')
            if len(parts) != 3 or len(parts[1]) != 4 or not parts[1].isdigit():
                continue
            episode = int(parts[1])
            if not 1 <= episode <= 1000:
                continue
            rows = counts.setdefault(episode, [0, 0])
            rows[0] += 1
            rows[1] += sum(1 for file in folder.glob('[0-2][0-9].json')
                           if file.is_file() and not file.is_symlink())
        return tuple(SceneCheckpointOverview(n, *counts[n]) for n in sorted(counts))
    except OSError:
        raise SceneCheckpointError('임시 장면 목록을 확인하지 못했습니다.') from None
