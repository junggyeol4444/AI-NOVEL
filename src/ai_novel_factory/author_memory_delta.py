"""Explicit, offline, append-only author memory-change ledger for long novels.

Memory deltas describe author-entered developments supported by an EXISTING saved
final chapter. They are not automatically inferred facts or QC certifications.
All mutations require a direct one-time action and create ONLY a new JSON file
in a user-selected, already existing local directory. Manuscripts/DB unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
from time import time_ns
from uuid import uuid4

from .database.episodes import EpisodeStore


class AuthorMemoryDeltaError(ValueError):
    """Sanitized; never quote manuscript or disk path."""


_ALLOWED = frozenset(('character', 'relationship', 'plot', 'foreshadow',
                      'timeline', 'world', 'style'))
_MAX_FILES = 4000
_MAX_FILE_BYTES = 12288
_MAX_TEXT_BYTES = 1024
_PREFIX = 'anf-memory-'


@dataclass(frozen=True)
class AuthorMemoryDelta:
    delta_id: str
    project_id: str
    source_episode: int
    source_revision: int
    source_sha256: str
    valid_from: int
    valid_through: int
    category: str
    subject: str
    change: str
    retracted: bool = False
    publication_approved: bool = False
    quality_certified: bool = False


def _directory(folder: str | Path) -> Path:
    path = Path(folder)
    if (not path.is_absolute() or path.is_symlink() or not path.is_dir()
            or str(path).startswith(('\\\\', '//'))):
        raise AuthorMemoryDeltaError('기존 로컬 기억 기록 폴더를 직접 선택해야 합니다.')
    return path


def _files(folder: Path) -> tuple[Path, ...]:
    items = sorted(folder.glob(_PREFIX + '*.json'))
    if len(items) > _MAX_FILES:
        raise AuthorMemoryDeltaError('작가 기억 기록 개수 제한을 초과했습니다.')
    if any(p.is_symlink() or not p.is_file() or p.stat().st_size > _MAX_FILE_BYTES
           for p in items):
        raise AuthorMemoryDeltaError('작가 기억 기록 파일을 안전하게 읽을 수 없습니다.')
    return tuple(items)


def _number(n: int) -> int:
    if type(n) is not int or not 1 <= n <= 1000:
        raise AuthorMemoryDeltaError('기억 기록의 회차 범위가 올바르지 않습니다.')
    return n


def _words(value: str, max_bytes: int = _MAX_TEXT_BYTES) -> str:
    if type(value) is not str or not value.strip():
        raise AuthorMemoryDeltaError('작가 기억 기록의 문구가 올바르지 않습니다.')
    if (len(value.encode('utf-8')) > max_bytes or '\x00' in value
            or any(ord(ch) < 32 and ch not in '\n\t' for ch in value)):
        raise AuthorMemoryDeltaError('작가 기억 기록의 길이나 문자가 올바르지 않습니다.')
    return value.strip()


def _read(folder: Path) -> tuple[dict, ...]:
    rows = []
    for path in _files(folder):
        try:
            with path.open('rb') as fp:
                raw = fp.read(_MAX_FILE_BYTES + 1)
            if len(raw) > _MAX_FILE_BYTES:
                raise ValueError('oversized')
            value = json.loads(raw.decode('utf-8'))
            if (type(value) is not dict or value.get('format') != 'anf_memory_delta_v1'
                    or value.get('event') not in ('ADD', 'RETRACT')
                    or type(value.get('delta_id')) is not str
                    or len(value['delta_id']) != 32
                    or type(value.get('project_id')) is not str
                    or len(value['project_id']) > 128
                    or value.get('publication_approved') is not False):
                raise ValueError('invalid')
            if value['event'] == 'ADD':
                if (value.get('category') not in _ALLOWED
                        or type(value.get('source_revision')) is not int
                        or value['source_revision'] < 1
                        or type(value.get('source_sha256')) is not str
                        or len(value['source_sha256']) != 64):
                    raise ValueError('invalid add')
                s, a, b = (_number(value[key]) for key in
                           ('source_episode', 'valid_from', 'valid_through'))
                if not s < a <= b:
                    raise ValueError('invalid chronology')
                _words(value['subject'], 180)
                _words(value['change'], _MAX_TEXT_BYTES)
            rows.append(value)
        except (OSError, UnicodeError, ValueError, KeyError, TypeError):
            raise AuthorMemoryDeltaError('작가 기억 기록의 형식 또는 무결성이 올바르지 않습니다.') from None
    return tuple(rows)


def memory_delta_fingerprint(folder: str | Path) -> str:
    """Full original file bytes; never treat an empty folder as approved memory."""
    directory = _directory(folder)
    h = sha256()
    for path in _files(directory):
        h.update(path.name.encode('ascii'))
        h.update(b'\x00')
        h.update(path.read_bytes())
        h.update(b'\x00')
    return h.hexdigest()


def list_author_memory_deltas(folder: str | Path, project_id: str) -> tuple[AuthorMemoryDelta, ...]:
    rows = _read(_directory(folder))
    entries: dict[str, AuthorMemoryDelta] = {}
    for row in rows:
        if row['project_id'] != project_id:
            continue
        ident = row['delta_id']
        if row['event'] == 'ADD':
            if ident in entries:
                raise AuthorMemoryDeltaError('중복된 기억 기록을 발견했습니다.')
            entries[ident] = AuthorMemoryDelta(
                ident, project_id, row['source_episode'], row['source_revision'],
                row['source_sha256'], row['valid_from'], row['valid_through'],
                row['category'], row['subject'], row['change'])
        else:
            if ident not in entries or entries[ident].retracted:
                raise AuthorMemoryDeltaError('기억 기록 철회 순서가 올바르지 않습니다.')
            old = entries[ident]
            entries[ident] = AuthorMemoryDelta(
                old.delta_id, old.project_id, old.source_episode, old.source_revision,
                old.source_sha256, old.valid_from, old.valid_through, old.category,
                old.subject, old.change, True)
    return tuple(entries.values())


def _append(folder: Path, event: dict) -> None:
    content = json.dumps(event, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode('utf-8')
    if len(content) > _MAX_FILE_BYTES:
        raise AuthorMemoryDeltaError('새 기억 기록 크기 제한을 초과했습니다.')
    name = _PREFIX + f'{time_ns():020d}-' + uuid4().hex + '.json'
    fd = -1
    try:
        fd = os.open(folder / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as fp:
            fd = -1
            fp.write(content)
            fp.flush()
            os.fsync(fp.fileno())
    except OSError:
        if fd != -1:
            os.close(fd)
        raise AuthorMemoryDeltaError('작가 기억 기록을 새 파일에 저장하지 못했습니다.') from None


def add_author_memory_delta(store: EpisodeStore, project_id: str, *, folder: str | Path,
                            source_episode: int, valid_from: int, valid_through: int,
                            category: str, subject: str, change: str,
                            explicit_author_save: bool) -> str:
    if explicit_author_save is not True:
        raise AuthorMemoryDeltaError('이번 기억 변경 기록 저장을 작가가 직접 승인해야 합니다.')
    if not isinstance(store, EpisodeStore):
        raise AuthorMemoryDeltaError('기존 SQLite 작품이 필요합니다.')
    directory = _directory(folder)
    source_episode, valid_from, valid_through = map(
        _number, (source_episode, valid_from, valid_through))
    if not source_episode < valid_from <= valid_through or category not in _ALLOWED:
        raise AuthorMemoryDeltaError('기억 기록 범위 또는 분류가 올바르지 않습니다.')
    subject, change = _words(subject, 180), _words(change)
    if len(_files(directory)) >= _MAX_FILES:
        raise AuthorMemoryDeltaError('새 기억 기록을 추가할 수 없습니다.')
    source = store.get_episode(project_id, source_episode)
    if not source.final_text.strip():
        raise AuthorMemoryDeltaError('근거가 되는 과거 회차 최종본이 저장되지 않았습니다.')
    for item in list_author_memory_deltas(directory, project_id):
        if (not item.retracted and item.category == category
                and item.subject.casefold() == subject.casefold()
                and max(item.valid_from, valid_from) <= min(item.valid_through, valid_through)):
            raise AuthorMemoryDeltaError('같은 대상의 활성 기억 기록 범위가 겹칩니다. 작가 확인이 필요합니다.')
    ident = uuid4().hex
    _append(directory, {
        'format': 'anf_memory_delta_v1', 'event': 'ADD', 'delta_id': ident,
        'project_id': project_id, 'source_episode': source_episode,
        'source_revision': source.revision,
        'source_sha256': sha256(source.final_text.encode('utf-8')).hexdigest(),
        'valid_from': valid_from, 'valid_through': valid_through,
        'category': category, 'subject': subject, 'change': change,
        'publication_approved': False,
    })
    return ident


def retract_author_memory_delta(folder: str | Path, project_id: str, delta_id: str,
                                *, explicit_author_retract: bool) -> None:
    if explicit_author_retract is not True:
        raise AuthorMemoryDeltaError('이번 기억 기록 철회를 직접 승인해야 합니다.')
    directory = _directory(folder)
    if not any(item.delta_id == delta_id and not item.retracted
               for item in list_author_memory_deltas(directory, project_id)):
        raise AuthorMemoryDeltaError('철회할 활성 기억 기록을 찾을 수 없습니다.')
    _append(directory, {'format': 'anf_memory_delta_v1', 'event': 'RETRACT',
                        'delta_id': delta_id, 'project_id': project_id,
                        'publication_approved': False})
