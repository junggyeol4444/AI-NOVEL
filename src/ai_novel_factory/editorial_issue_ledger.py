"""Author-owned local editorial issue history for saved final manuscripts.

Each explicit action creates a NEW private JSON file in an existing author-chosen
folder. Manuscript SQLite, reference originals and existing files are untouched.
This ledger is not QC, a signature, a literary-quality verdict or publication
approval. All previously raised issues remain visible across revisions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import os
import re
from uuid import uuid4

from .database.episodes import EpisodeStore


class EditorialIssueError(ValueError):
    """Errors intentionally omit manuscript text, notes and private paths."""


_CATEGORIES = frozenset({
    'continuity', 'character_knowledge', 'timeline', 'foreshadowing',
    'plot_logic', 'reference_similarity', 'style', 'language', 'other',
})
_FILE_RE = re.compile(r'^anf_editorial_[0-9a-f]{32}\.json$')
_ID_RE = re.compile(r'^[0-9a-f]{32}$')
_MAX_EVENTS = 20000
_MAX_EVENT_BYTES = 8192


@dataclass(frozen=True)
class EditorialIssue:
    issue_id: str
    episode: int
    category: str
    note: str
    opened_revision: int
    status: str
    current_revision: int
    created_at: str
    closed_at: str = ''
    publication_approved: bool = False


def _directory(folder: str | Path) -> Path:
    if not isinstance(folder, (str, Path)):
        raise EditorialIssueError('작가가 선택한 로컬 편집 기록 폴더가 필요합니다.')
    path = Path(folder)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise EditorialIssueError('기존 로컬 편집 기록 폴더를 직접 선택하세요.')
    return path


def _final_snapshot(store: EpisodeStore, project_id: str, episode: int):
    if not isinstance(store, EpisodeStore) or not isinstance(project_id, str) or not project_id:
        raise EditorialIssueError('현재 저장된 작품을 먼저 열어야 합니다.')
    if type(episode) is not int or not 1 <= episode <= 1000:
        raise EditorialIssueError('회차는 1~1000화만 지원합니다.')
    try:
        saved = store.get_episode(project_id, episode)
    except (ValueError, LookupError):
        raise EditorialIssueError('저장된 회차를 선택해야 합니다.') from None
    if not saved.final_text.strip():
        raise EditorialIssueError('저장된 최종본이 있어야 편집 기록을 남길 수 있습니다.')
    return saved.revision, sha256(saved.final_text.encode('utf-8')).hexdigest()


def _read_events(folder: str | Path) -> list[dict]:
    directory = _directory(folder)
    paths = sorted(p for p in directory.iterdir() if _FILE_RE.fullmatch(p.name))
    if len(paths) > _MAX_EVENTS:
        raise EditorialIssueError('로컬 편집 기록의 개수 제한을 초과했습니다.')
    events = []
    for path in paths:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_EVENT_BYTES:
            raise EditorialIssueError('로컬 편집 기록을 안전하게 읽을 수 없습니다.')
        try:
            raw = path.read_bytes()
            record = json.loads(raw.decode('utf-8'))
        except (OSError, UnicodeError, ValueError):
            raise EditorialIssueError('로컬 편집 기록이 손상되었습니다.') from None
        if (type(record) is not dict or record.get('format') != 'anf_editorial_issue_v1'
                or record.get('kind') not in {'OPEN', 'CLOSE'}
                or not isinstance(record.get('project_id'), str)
                or type(record.get('episode')) is not int
                or type(record.get('revision')) is not int
                or not isinstance(record.get('final_sha256'), str)
                or not re.fullmatch(r'[0-9a-f]{64}', record['final_sha256'])
                or not isinstance(record.get('event_id'), str)
                or not _ID_RE.fullmatch(record['event_id'])
                or not isinstance(record.get('issue_id'), str)
                or not _ID_RE.fullmatch(record['issue_id'])
                or not isinstance(record.get('created_at'), str)
                or record['event_id'] != path.stem.removeprefix('anf_editorial_')):
            raise EditorialIssueError('로컬 편집 기록의 구조가 올바르지 않습니다.')
        if record['kind'] == 'OPEN':
            if (record['issue_id'] != record['event_id']
                    or record.get('category') not in _CATEGORIES
                    or type(record.get('note')) is not str
                    or not 1 <= len(record['note'].strip()) <= 1000):
                raise EditorialIssueError('로컬 편집 기록의 최초 입력이 올바르지 않습니다.')
        events.append(record)
    return events


def _save_new_event(folder: str | Path, event: dict) -> None:
    directory = _directory(folder)
    payload = json.dumps(event, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode('utf-8')
    if len(payload) > _MAX_EVENT_BYTES:
        raise EditorialIssueError('편집 기록 크기 제한을 초과했습니다.')
    path = directory / ('anf_editorial_' + event['event_id'] + '.json')
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        raise EditorialIssueError('새 편집 기록을 저장하지 못했습니다. 기존 파일은 변경하지 않았습니다.') from None


def _event(project_id: str, episode: int, revision: int,
           final_sha256: str, *, kind: str, issue_id: str, **extra) -> dict:
    return dict(format='anf_editorial_issue_v1', event_id=uuid4().hex,
                project_id=project_id, episode=episode, revision=revision,
                final_sha256=final_sha256, kind=kind, issue_id=issue_id,
                created_at=datetime.now(timezone.utc).isoformat(),
                publication_approved=False, **extra)


def list_editorial_issues(store: EpisodeStore, project_id: str, episode: int,
                          *, folder: str | Path) -> tuple[EditorialIssue, ...]:
    """Read all events; an issue closed for an old revision becomes stale again."""
    revision, digest = _final_snapshot(store, project_id, episode)
    opens = {}
    closes = {}
    for event in _read_events(folder):
        if event['project_id'] != project_id or event['episode'] != episode:
            continue
        issue_id = event['issue_id']
        if event['kind'] == 'OPEN':
            if issue_id in opens:
                raise EditorialIssueError('중복된 편집 이슈 기록을 발견했습니다.')
            opens[issue_id] = event
        else:
            closes.setdefault(issue_id, []).append(event)
    if any(issue_id not in opens for issue_id in closes):
        raise EditorialIssueError('원본 이슈가 없는 종료 기록을 발견했습니다.')
    rows = []
    for issue_id, opening in opens.items():
        closed = sorted(closes.get(issue_id, []),
                        key=lambda item: (item['created_at'], item['event_id']))
        latest = closed[-1] if closed else None
        if latest is not None and (latest['revision'] == revision
                                   and latest['final_sha256'] == digest):
            status = 'CLOSED_CURRENT'
        elif latest is not None:
            status = 'CLOSED_STALE'
        elif opening['revision'] != revision or opening['final_sha256'] != digest:
            status = 'OPEN_STALE'
        else:
            status = 'OPEN_CURRENT'
        rows.append(EditorialIssue(issue_id, episode, opening['category'],
                                   opening['note'], opening['revision'], status,
                                   revision, opening['created_at'],
                                   latest['created_at'] if latest else ''))
    return tuple(sorted(rows, key=lambda row: (row.created_at, row.issue_id)))


def open_editorial_issue(store: EpisodeStore, project_id: str, episode: int,
                         *, folder: str | Path, category: str, note: str,
                         expected_revision: int, expected_final_sha256: str,
                         explicit_author_save: bool) -> tuple[EditorialIssue, ...]:
    if explicit_author_save is not True:
        raise EditorialIssueError('편집 이슈 저장을 직접 승인해야 합니다.')
    if category not in _CATEGORIES or type(note) is not str or not 1 <= len(note.strip()) <= 1000:
        raise EditorialIssueError('편집 항목과 메모는 1~1000자로 작성해야 합니다.')
    if any(ord(ch) < 32 and ch not in '\n\t' for ch in note):
        raise EditorialIssueError('편집 메모에 허용되지 않는 문자가 있습니다.')
    revision, digest = _final_snapshot(store, project_id, episode)
    if revision != expected_revision or digest != expected_final_sha256:
        raise EditorialIssueError('원고가 변경되어 편집 기록을 저장하지 않았습니다.')
    _read_events(folder)  # Refuse to append alongside malformed history.
    event = _event(project_id, episode, revision, digest, kind='OPEN', issue_id='',
                   category=category, note=note.strip())
    event['issue_id'] = event['event_id']
    _save_new_event(folder, event)
    return list_editorial_issues(store, project_id, episode, folder=folder)


def close_editorial_issue(store: EpisodeStore, project_id: str, episode: int,
                          *, folder: str | Path, issue_id: str,
                          expected_revision: int, expected_final_sha256: str,
                          explicit_author_read_current: bool) -> tuple[EditorialIssue, ...]:
    if explicit_author_read_current is not True or not isinstance(issue_id, str):
        raise EditorialIssueError('현재 최종본을 직접 읽고 종료할 이슈를 선택해야 합니다.')
    revision, digest = _final_snapshot(store, project_id, episode)
    if revision != expected_revision or digest != expected_final_sha256:
        raise EditorialIssueError('원고가 변경되어 종료 기록을 저장하지 않았습니다.')
    issues = list_editorial_issues(store, project_id, episode, folder=folder)
    selected = next((issue for issue in issues if issue.issue_id == issue_id), None)
    if selected is None or selected.status == 'CLOSED_CURRENT':
        raise EditorialIssueError('현재 미해결 상태의 이슈만 종료할 수 있습니다.')
    event = _event(project_id, episode, revision, digest, kind='CLOSE', issue_id=issue_id)
    _save_new_event(folder, event)
    return list_editorial_issues(store, project_id, episode, folder=folder)


def current_final_identity(store: EpisodeStore, project_id: str, episode: int) -> tuple[int, str]:
    """Public read-only snapshot for explicit GUI actions."""
    return _final_snapshot(store, project_id, episode)
