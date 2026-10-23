"""Author-controlled, append-only local continuity facts for the existing novel.

Facts are explicitly authored metadata, not inferred truth, model output,
source-novel excerpts, QC approval or permission to publish. This module never
changes the existing manuscript SQLite, GGUF model or reference originals.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
import json
import os

from .database.episodes import EpisodeStore

FACT_TYPES = frozenset({'인물지식', '인물관계', '복선', '시간선', '세계관', '사건'})
_MAX_EVENTS = 2000
_MAX_FILE = 4096


class AuthorFactError(ValueError):
    """Sanitized failure; never print private text, paths or manuscripts."""


@dataclass(frozen=True)
class AuthorFact:
    fact_id: str
    project_id: str
    source_episode: int
    source_revision: int
    source_sha256: str
    valid_from: int
    valid_until: int
    kind: str
    subject: str
    predicate: str
    value: str
    retracted: bool = False


def _folder(path: str | Path) -> Path:
    folder = Path(path)
    if not folder.is_absolute() or folder.is_symlink() or not folder.is_dir():
        raise AuthorFactError('작가가 선택한 기존 로컬 기록 폴더가 필요합니다.')
    return folder


def _label(value: str, *, limit: int) -> str:
    if (type(value) is not str or not value.strip()
            or len(value) > limit or len(value.encode('utf-8')) > limit * 4
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise AuthorFactError('구조화 사실의 입력 형식이 올바르지 않습니다.')
    return value.strip()


def _episode_number(number: int) -> int:
    if type(number) is not int or not 1 <= number <= 1000:
        raise AuthorFactError('회차 범위는 1~1000화입니다.')
    return number


def _source(store: EpisodeStore, project_id: str, number: int):
    if not isinstance(store, EpisodeStore) or type(project_id) is not str or not project_id:
        raise AuthorFactError('기존 작품을 먼저 열어야 합니다.')
    _episode_number(number)
    store.get_project(project_id)
    item = next((e for e in store.list_episodes(project_id)
                 if e.episode == number), None)
    if item is None or not item.final_text.strip():
        raise AuthorFactError('근거 회차의 저장된 최종 원고가 필요합니다.')
    return item


def _event_files(folder: Path) -> tuple[Path, ...]:
    files = []
    for entry in folder.iterdir():
        if entry.name.startswith('anf-fact-') and entry.name.endswith('.json'):
            if entry.is_symlink() or not entry.is_file():
                raise AuthorFactError('구조화 사실 기록에 허용되지 않는 파일이 있습니다.')
            files.append(entry)
            if len(files) > _MAX_EVENTS:
                raise AuthorFactError('구조화 사실 기록 개수 제한을 초과했습니다.')
    return tuple(sorted(files, key=lambda p: p.name))


def _load_events(folder: Path) -> list[dict]:
    events = []
    for path in _event_files(folder):
        try:
            if path.stat().st_size > _MAX_FILE:
                raise AuthorFactError('구조화 사실 기록의 크기가 올바르지 않습니다.')
            data = json.loads(path.read_bytes().decode('utf-8'))
        except (OSError, UnicodeError, ValueError):
            raise AuthorFactError('구조화 사실 기록을 읽을 수 없습니다.') from None
        if (type(data) is not dict or data.get('format') != 'anf_author_fact_v1'
                or data.get('event') not in {'ADD', 'RETRACT'}
                or type(data.get('project_id')) is not str
                or type(data.get('fact_id')) is not str
                or len(data['fact_id']) != 32):
            raise AuthorFactError('구조화 사실 기록의 형식이 올바르지 않습니다.')
        events.append(data)
    return events


def read_author_facts(folder: str | Path, project_id: str) -> tuple[AuthorFact, ...]:
    """Read all author facts without touching any project or model data."""
    if type(project_id) is not str or not project_id:
        raise AuthorFactError('작품을 먼저 선택해야 합니다.')
    events = _load_events(_folder(folder))
    additions: dict[str, dict] = {}
    retractions: set[str] = set()
    for item in events:
        if item['project_id'] != project_id:
            continue
        ident = item['fact_id']
        if item['event'] == 'ADD':
            if ident in additions:
                raise AuthorFactError('구조화 사실 기록에 중복 식별자가 있습니다.')
            additions[ident] = item
        else:
            if ident in retractions:
                raise AuthorFactError('동일 사실에 대한 중복 철회 기록이 있습니다.')
            retractions.add(ident)
    if not retractions.issubset(additions):
        raise AuthorFactError('존재하지 않는 사실을 철회한 기록이 있습니다.')
    facts = []
    for ident, item in sorted(additions.items()):
        try:
            source = _episode_number(item['source_episode'])
            start = _episode_number(item['valid_from'])
            end = _episode_number(item['valid_until'])
            revision = item['source_revision']
            digest = item['source_sha256']
            kind = item['kind']
            if (source > start or start > end
                    or type(revision) is not int or revision < 1
                    or type(digest) is not str or len(digest) != 64
                    or kind not in FACT_TYPES):
                raise ValueError
            subject = _label(item['subject'], limit=100)
            predicate = _label(item['predicate'], limit=100)
            value = _label(item['value'], limit=400)
        except (KeyError, TypeError, ValueError, AuthorFactError):
            raise AuthorFactError('구조화 사실 기록의 내용이 손상되었습니다.') from None
        facts.append(AuthorFact(ident, project_id, source, revision, digest,
                                start, end, kind, subject, predicate, value,
                                ident in retractions))
    return tuple(facts)


def ledger_fingerprint(folder: str | Path) -> str:
    """Bind a model run to immutable bytes of all locally selected fact events."""
    directory = _folder(folder)
    digest = sha256()
    for path in _event_files(directory):
        try:
            raw = path.read_bytes()
        except OSError:
            raise AuthorFactError('구조화 사실 기록을 다시 읽을 수 없습니다.') from None
        if len(raw) > _MAX_FILE:
            raise AuthorFactError('구조화 사실 기록 크기 제한을 초과했습니다.')
        digest.update(path.name.encode('utf-8') + b'\0')
        digest.update(len(raw).to_bytes(8, 'big') + raw)
    return digest.hexdigest()


def _exclusive_event(folder: Path, data: dict) -> str:
    """Create exactly one NEW local file; never replace an existing file."""
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True,
                     separators=(',', ':')).encode('utf-8')
    if len(raw) > _MAX_FILE:
        raise AuthorFactError('구조화 사실 기록의 크기 제한을 초과했습니다.')
    path = folder / ('anf-fact-' + uuid4().hex + '.json')
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        raise AuthorFactError('새 구조화 사실 파일을 저장하지 못했습니다.') from None
    return data['fact_id']


def add_author_fact(store: EpisodeStore, project_id: str, *,
                    folder: str | Path, source_episode: int,
                    valid_from: int, valid_until: int, kind: str,
                    subject: str, predicate: str, value: str,
                    explicit_author_save: bool) -> str:
    if explicit_author_save is not True:
        raise AuthorFactError('작가가 이번 구조화 사실 저장을 직접 승인해야 합니다.')
    directory = _folder(folder)
    if len(_event_files(directory)) >= _MAX_EVENTS:
        raise AuthorFactError('구조화 사실 기록 개수 제한을 초과했습니다.')
    source = _source(store, project_id, source_episode)
    _episode_number(valid_from)
    _episode_number(valid_until)
    if source_episode > valid_from or valid_from > valid_until:
        raise AuthorFactError('미래의 사건을 과거 회차의 사실로 등록할 수 없습니다.')
    if kind not in FACT_TYPES:
        raise AuthorFactError('구조화 사실의 종류가 올바르지 않습니다.')
    data = {
        'format': 'anf_author_fact_v1', 'event': 'ADD',
        'fact_id': uuid4().hex, 'project_id': project_id,
        'source_episode': source_episode, 'source_revision': source.revision,
        'source_sha256': sha256(source.final_text.encode('utf-8')).hexdigest(),
        'valid_from': valid_from, 'valid_until': valid_until, 'kind': kind,
        'subject': _label(subject, limit=100),
        'predicate': _label(predicate, limit=100),
        'value': _label(value, limit=400),
        'publication_approved': False,
    }
    return _exclusive_event(directory, data)


def retract_author_fact(folder: str | Path, project_id: str, fact_id: str, *,
                        explicit_author_retract: bool) -> None:
    if explicit_author_retract is not True:
        raise AuthorFactError('작가가 이번 구조화 사실 철회를 직접 승인해야 합니다.')
    directory = _folder(folder)
    found = next((fact for fact in read_author_facts(directory, project_id)
                  if fact.fact_id == fact_id), None)
    if found is None or found.retracted:
        raise AuthorFactError('현재 유효한 구조화 사실 기록을 선택해야 합니다.')
    _exclusive_event(directory, {
        'format': 'anf_author_fact_v1', 'event': 'RETRACT',
        'fact_id': fact_id, 'project_id': project_id,
        'publication_approved': False,
    })
