"""Author-triggered, local append-only receipts for interrupted longform batches.

This is a *receipt*, not a checkpoint of model execution, not an automatic
restart and not an approval token. The manuscript SQLite is authoritative.
No manuscript, source work, model executable path or model arguments are stored.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import os
from uuid import uuid4

from .database.episodes import EpisodeStore
from .auto_resume_plan import preview_resume


class BatchJournalError(ValueError):
    """Path- and manuscript-free diagnostics."""


MAX_JOURNAL_BYTES = 256 * 1024
MAX_JOURNALS_TO_SHOW = 100
_VERSION = 1
_FINAL = frozenset({'FINISHED', 'STOPPED', 'FAILED'})


def _hash(value: str) -> str:
    return sha256(value.encode('utf-8')).hexdigest()


def _canonical(data: dict) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _identity(database_path: str | Path, project_id: str) -> tuple[str, str]:
    path = Path(database_path)
    if not path.is_absolute() or not project_id:
        raise BatchJournalError('작품 DB와 작품을 먼저 직접 선택해야 합니다.')
    return _hash(str(path.resolve(strict=False))), _hash(project_id)


def _write_new(path: Path, data: bytes) -> None:
    if not path.is_absolute() or path.suffix != '.jsonl' or path.is_symlink():
        raise BatchJournalError('로컬 작업 기록 저장 위치가 올바르지 않습니다.')
    if len(data) > 4096:
        raise BatchJournalError('작업 기록이 허용 크기를 초과했습니다.')
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except (OSError, ValueError) as exc:
        raise BatchJournalError('새 로컬 작업 기록을 안전하게 생성하지 못했습니다.') from None


def _signed_line(payload: dict, previous: str) -> tuple[bytes, str]:
    body = dict(payload, prev=previous)
    digest = sha256(_canonical(body)).hexdigest()
    return _canonical(dict(body, digest=digest)) + b'\n', digest


@dataclass(frozen=True)
class SessionReceipt:
    path: Path
    session_id: str
    database_hash: str
    project_hash: str
    settings_hash: str
    through_episode: int
    state: str
    events: int
    last_digest: str
    needs_fresh_author_approval: bool = True


@dataclass(frozen=True)
class RecoveryPreview:
    session_id: str
    recorded_state: str
    current_state: str
    through_episode: int
    already_saved: tuple[int, ...]
    missing_episodes: tuple[int, ...]
    existing_without_draft: tuple[int, ...]
    author_must_approve_new_run: bool = True
    old_run_auto_resumed: bool = False
    publication_approved: bool = False


def begin_session(journal_directory: str | Path, *, database_path: str | Path,
                  project_id: str, through_episode: int, target_chars: int,
                  scenes_per_episode: int, reference_paths: tuple[str, ...] = ()) -> SessionReceipt:
    """Only call AFTER the user approves this exact local-model batch in GUI."""
    if (type(through_episode) is not int or not 1 <= through_episode <= 1000
            or type(target_chars) is not int or not 50 <= target_chars <= 50000
            or type(scenes_per_episode) is not int or not 1 <= scenes_per_episode <= 20
            or type(reference_paths) is not tuple or len(reference_paths) > 100
            or any(type(item) is not str for item in reference_paths)):
        raise BatchJournalError('이번 실행의 회차·분량·참고작 설정이 올바르지 않습니다.')
    database_hash, project_hash = _identity(database_path, project_id)
    reference_hash = _hash('\x00'.join(reference_paths))
    settings_hash = _hash(_canonical({
        'through': through_episode, 'target_chars': target_chars,
        'scenes': scenes_per_episode, 'reference_hash': reference_hash,
        'reference_count': len(reference_paths),
    }).decode('utf-8'))
    directory = Path(journal_directory)
    if not directory.is_absolute() or directory.is_symlink():
        raise BatchJournalError('작업 기록은 명시된 로컬 폴더에만 저장할 수 있습니다.')
    session_id = uuid4().hex
    path = directory / (project_hash[:16] + '_' + session_id + '.jsonl')
    line, digest = _signed_line({
        'version': _VERSION, 'seq': 0, 'kind': 'BEGIN', 'session': session_id,
        'database_hash': database_hash, 'project_hash': project_hash,
        'settings_hash': settings_hash, 'through': through_episode,
        'created_at': _now(), 'state': 'RUNNING',
        'model_approval_persisted': False, 'publisher_called': False,
    }, '')
    _write_new(path, line)
    return SessionReceipt(path, session_id, database_hash, project_hash,
                          settings_hash, through_episode, 'RUNNING', 1, digest)


def read_session(path: str | Path) -> SessionReceipt:
    path = Path(path)
    if not path.is_absolute() or path.suffix != '.jsonl' or path.is_symlink():
        raise BatchJournalError('작업 기록 경로가 올바르지 않습니다.')
    try:
        if path.stat().st_size > MAX_JOURNAL_BYTES:
            raise BatchJournalError('작업 기록 크기가 허용 범위를 벗어났습니다.')
        raw = path.read_bytes()
        if not raw.endswith(b'\n') or not raw:
            raise BatchJournalError('작업 기록이 완결되지 않았습니다.')
        rows = [json.loads(line) for line in raw.splitlines()]
    except BatchJournalError:
        raise
    except (OSError, ValueError, UnicodeError, TypeError):
        raise BatchJournalError('작업 기록을 안전하게 읽지 못했습니다.') from None
    previous = ''
    session = None
    for seq, row in enumerate(rows):
        if not isinstance(row, dict) or row.get('seq') != seq:
            raise BatchJournalError('작업 기록의 순서가 손상되었습니다.')
        digest = row.get('digest')
        body = {k: v for k, v in row.items() if k != 'digest'}
        if (row.get('prev') != previous or not isinstance(digest, str)
                or sha256(_canonical(body)).hexdigest() != digest):
            raise BatchJournalError('작업 기록 무결성이 확인되지 않습니다.')
        if seq == 0:
            if (row.get('kind') != 'BEGIN' or row.get('version') != _VERSION
                    or row.get('state') != 'RUNNING'
                    or row.get('model_approval_persisted') is not False
                    or row.get('publisher_called') is not False):
                raise BatchJournalError('작업 기록 시작 형식이 올바르지 않습니다.')
            session = row
        else:
            if (row.get('kind') != 'END' or row.get('session') != session['session']
                    or row.get('state') not in _FINAL or seq != 1):
                raise BatchJournalError('작업 기록 종료 형식이 올바르지 않습니다.')
        previous = digest
    if len(rows) > 2:
        raise BatchJournalError('작업 기록에 알 수 없는 이벤트가 있습니다.')
    return SessionReceipt(path, session['session'], session['database_hash'],
                          session['project_hash'], session['settings_hash'],
                          session['through'], rows[-1]['state'], len(rows), previous)


def end_session(path: str | Path, session_id: str, *, state: str) -> SessionReceipt:
    """Append only; never overwrite a prior receipt or convert it into approval."""
    if state not in _FINAL:
        raise BatchJournalError('작업 종료 상태가 올바르지 않습니다.')
    receipt = read_session(path)
    if receipt.session_id != session_id or receipt.state != 'RUNNING':
        raise BatchJournalError('이미 종료되었거나 다른 작업의 기록입니다.')
    line, _ = _signed_line({'version': _VERSION, 'seq': receipt.events,
                            'kind': 'END', 'session': session_id,
                            'state': state, 'created_at': _now(),
                            'publisher_called': False}, receipt.last_digest)
    if receipt.path.stat().st_size + len(line) > MAX_JOURNAL_BYTES:
        raise BatchJournalError('작업 기록 크기 제한을 초과했습니다.')
    try:
        flags = os.O_WRONLY | os.O_APPEND
        if hasattr(os, 'O_NOFOLLOW'):
            flags |= os.O_NOFOLLOW
        fd = os.open(str(receipt.path), flags)
        with os.fdopen(fd, 'ab') as handle:
            if handle.write(line) != len(line):
                raise OSError('short append')
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        raise BatchJournalError('로컬 작업 종료 기록을 저장하지 못했습니다.') from None
    return read_session(receipt.path)


def list_project_sessions(journal_directory: str | Path, *,
                          database_path: str | Path, project_id: str) -> tuple[SessionReceipt, ...]:
    """Read-only discovery. Unknown/corrupt journals never grant run permission."""
    database_hash, project_hash = _identity(database_path, project_id)
    directory = Path(journal_directory)
    if not directory.is_absolute() or not directory.exists() or directory.is_symlink():
        return ()
    try:
        paths = sorted(directory.glob(project_hash[:16] + '_*.jsonl'),
                       key=lambda p: p.stat().st_mtime, reverse=True)[:MAX_JOURNALS_TO_SHOW]
        found = []
        for path in paths:
            receipt = read_session(path)
            if (receipt.database_hash == database_hash
                    and receipt.project_hash == project_hash):
                found.append(receipt)
        return tuple(found)
    except (OSError, BatchJournalError):
        raise BatchJournalError('작업 기록 목록 중 확인되지 않은 항목이 있습니다.') from None


def preview_recovery(store: EpisodeStore, database_path: str | Path,
                     project_id: str, receipt: SessionReceipt) -> RecoveryPreview:
    """Always inspect real SQLite, not optimistic 'completed' journal events."""
    if not isinstance(store, EpisodeStore):
        raise BatchJournalError('기존 작품 DB를 열어야 합니다.')
    database_hash, project_hash = _identity(database_path, project_id)
    if (receipt.database_hash != database_hash or receipt.project_hash != project_hash):
        raise BatchJournalError('현재 작품과 다른 작업 기록입니다.')
    plan = preview_resume(store, project_id, through_episode=receipt.through_episode)
    status = 'NO_MISSING_EPISODES' if not plan.missing_episodes else 'NEEDS_FRESH_APPROVAL'
    if plan.existing_without_draft:
        status = 'MANUAL_REVIEW_REQUIRED'
    if receipt.state == 'RUNNING':
        status = 'INTERRUPTED_OR_RUNNING_UNCONFIRMED'
    return RecoveryPreview(receipt.session_id, receipt.state, status,
                           receipt.through_episode, plan.existing_episodes,
                           plan.missing_episodes, plan.existing_without_draft)
