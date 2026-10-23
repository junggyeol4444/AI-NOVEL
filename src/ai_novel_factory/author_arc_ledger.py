"""Local author-written long-form arcs; append-only event files, never manuscript edits.

An arc is a planning aid, not a continuity proof, QC PASS, verified literary
quality, approval to run a model, or permission to publish. Nothing loads a
remote resource. Only an explicit author action writes a NEW local event.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
import json
import os
import time

from .database.episodes import EpisodeStore


class AuthorArcError(ValueError):
    """Messages never contain filenames, manuscripts or private arc text."""


@dataclass(frozen=True)
class AuthorArc:
    arc_id: str
    project_id: str
    start: int
    end: int
    title: str
    objective: str
    conflict: str
    foreshadow: str
    resolution: str
    canon_sha256: str
    version: int
    withdrawn: bool = False


_MAX_EVENTS = 3000
_MAX_EVENT_BYTES = 8192


def _folder(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise AuthorArcError('작가가 직접 선택한 기존 로컬 계획 폴더가 필요합니다.')
    return path


def _number(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 1000:
        raise AuthorArcError('장편 아크의 회차 범위는 1~1000화입니다.')
    return value


def _text(value: str, limit: int) -> str:
    if (type(value) is not str or not value.strip() or len(value) > limit
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise AuthorArcError('아크 이름·목표·갈등·복선·결말을 확인하세요.')
    return value.strip()


def _files(folder: Path) -> tuple[Path, ...]:
    paths = []
    for path in folder.iterdir():
        if path.name.startswith('anf-arc-') and path.name.endswith('.json'):
            if path.is_symlink() or not path.is_file():
                raise AuthorArcError('아크 기록 폴더에 올바르지 않은 항목이 있습니다.')
            paths.append(path)
            if len(paths) > _MAX_EVENTS:
                raise AuthorArcError('아크 기록 개수가 제한을 초과했습니다.')
    return tuple(sorted(paths, key=lambda x: x.name))


def canon_fingerprint(store: EpisodeStore, project_id: str) -> str:
    """Fingerprint the saved author rules; do not create or change any rule."""
    if not isinstance(store, EpisodeStore) or type(project_id) is not str or not project_id:
        raise AuthorArcError('기존 작품을 열어야 합니다.')
    try:
        project = store.get_project(project_id)
        if project is None:
            raise AuthorArcError('기존 작품을 찾을 수 없습니다.')
        rules = sorted((x.key, x.value) for x in store.list_rules(project_id)
                       if x.key != 'ai_story_outline_preview')
        body = json.dumps([project_id, rules], ensure_ascii=False,
                          separators=(',', ':')).encode('utf-8')
    except (OSError, ValueError, TypeError):
        raise AuthorArcError('저장된 작품 설정을 읽을 수 없습니다.') from None
    return sha256(body).hexdigest()


def _read_all(folder: Path) -> tuple[dict, ...]:
    events = []
    for file in _files(folder):
        try:
            if file.stat().st_size > _MAX_EVENT_BYTES:
                raise AuthorArcError('아크 기록 크기 제한을 초과했습니다.')
            data = json.loads(file.read_bytes().decode('utf-8'))
        except (OSError, ValueError, UnicodeError):
            raise AuthorArcError('아크 기록 파일을 읽지 못했습니다.') from None
        if (type(data) is not dict or data.get('format') != 'anf_author_arc_v1'
                or data.get('action') not in ('SET', 'WITHDRAW')
                or type(data.get('project_id')) is not str
                or type(data.get('arc_id')) is not str
                or len(data['arc_id']) != 32 or type(data.get('version')) is not int):
            raise AuthorArcError('아크 기록 형식이 올바르지 않습니다.')
        events.append(data)
    # Sort by the exact creation name; no mutable record is ever overwritten.
    return tuple(events)


def read_author_arcs(folder: str | Path, project_id: str) -> tuple[AuthorArc, ...]:
    if type(project_id) is not str or not project_id:
        raise AuthorArcError('작품 선택이 필요합니다.')
    versions: dict[str, AuthorArc] = {}
    for entry in _read_all(_folder(folder)):
        if entry['project_id'] != project_id:
            continue
        arc_id = entry['arc_id']
        previous = versions.get(arc_id)
        version = entry['version']
        if version < 1 or (previous is None and version != 1) or (
            previous is not None and version != previous.version + 1
        ):
            raise AuthorArcError('아크 이력의 버전이 올바르지 않습니다.')
        if entry['action'] == 'WITHDRAW':
            if previous is None or previous.withdrawn:
                raise AuthorArcError('유효하지 않은 아크 철회 기록입니다.')
            versions[arc_id] = AuthorArc(**{
                **previous.__dict__, 'version': version, 'withdrawn': True,
            })
        else:
            if previous is not None and previous.withdrawn:
                raise AuthorArcError('철회한 아크를 재사용할 수 없습니다.')
            try:
                start, end = _number(entry['start']), _number(entry['end'])
                if start > end:
                    raise AuthorArcError('아크 시작과 종료 회차가 올바르지 않습니다.')
                digest = entry['canon_sha256']
                if type(digest) is not str or len(digest) != 64:
                    raise AuthorArcError('아크 작품 설정 지문이 올바르지 않습니다.')
                arc = AuthorArc(arc_id, project_id, start, end,
                    _text(entry['title'], 100), _text(entry['objective'], 400),
                    _text(entry['conflict'], 400), _text(entry['foreshadow'], 400),
                    _text(entry['resolution'], 400), digest, version)
            except (KeyError, TypeError, ValueError):
                raise AuthorArcError('아크 기록 내용이 올바르지 않습니다.') from None
            versions[arc_id] = arc
    active = tuple(sorted((x for x in versions.values() if not x.withdrawn),
                          key=lambda x: (x.start, x.end, x.arc_id)))
    for first, second in zip(active, active[1:]):
        if second.start <= first.end:
            raise AuthorArcError('아크 계획에 중복 회차 범위가 있습니다.')
    return tuple(sorted(versions.values(), key=lambda x: (x.start, x.arc_id)))


def arc_ledger_fingerprint(folder: str | Path) -> str:
    h = sha256()
    for file in _files(_folder(folder)):
        try:
            data = file.read_bytes()
        except OSError:
            raise AuthorArcError('아크 기록을 다시 확인할 수 없습니다.') from None
        if len(data) > _MAX_EVENT_BYTES:
            raise AuthorArcError('아크 기록의 크기 제한을 초과했습니다.')
        h.update(file.name.encode('utf-8') + b'\0' + len(data).to_bytes(8, 'big') + data)
    return h.hexdigest()


def _append(folder: Path, event: dict) -> None:
    raw = json.dumps(event, ensure_ascii=False, sort_keys=True,
                     separators=(',', ':')).encode('utf-8')
    if len(raw) > _MAX_EVENT_BYTES or len(_files(folder)) >= _MAX_EVENTS:
        raise AuthorArcError('아크 기록 용량을 초과했습니다.')
    filename = 'anf-arc-' + f'{time.time_ns():020d}' + '-' + uuid4().hex + '.json'
    try:
        fd = os.open(folder / filename, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        raise AuthorArcError('새 아크 기록을 저장할 수 없습니다.') from None


def add_author_arc(store: EpisodeStore, project_id: str, *, folder: str | Path,
                   start: int, end: int, title: str, objective: str,
                   conflict: str, foreshadow: str, resolution: str,
                   explicit_author_save: bool) -> str:
    """Create one new event after the author explicitly approves this plan."""
    if explicit_author_save is not True:
        raise AuthorArcError('이번 아크 저장을 작가가 직접 승인해야 합니다.')
    start, end = _number(start), _number(end)
    if start > end:
        raise AuthorArcError('아크 시작·종료 회차가 올바르지 않습니다.')
    directory = _folder(folder)
    if any(not arc.withdrawn and start <= arc.end and arc.start <= end
           for arc in read_author_arcs(directory, project_id)):
        raise AuthorArcError('이미 다른 작가 아크가 지정된 회차입니다.')
    fingerprint = canon_fingerprint(store, project_id)
    arc_id = uuid4().hex
    _append(directory, {'format': 'anf_author_arc_v1', 'action': 'SET',
        'arc_id': arc_id, 'project_id': project_id, 'version': 1,
        'start': start, 'end': end, 'title': _text(title, 100),
        'objective': _text(objective, 400), 'conflict': _text(conflict, 400),
        'foreshadow': _text(foreshadow, 400), 'resolution': _text(resolution, 400),
        'canon_sha256': fingerprint, 'publication_approved': False})
    return arc_id


def withdraw_author_arc(folder: str | Path, project_id: str, arc_id: str, *,
                        explicit_author_withdraw: bool) -> None:
    if explicit_author_withdraw is not True:
        raise AuthorArcError('이번 아크 철회를 작가가 직접 승인해야 합니다.')
    directory = _folder(folder)
    arc = next((a for a in read_author_arcs(directory, project_id)
                if a.arc_id == arc_id and not a.withdrawn), None)
    if arc is None:
        raise AuthorArcError('철회할 활성 아크를 찾을 수 없습니다.')
    _append(directory, {'format': 'anf_author_arc_v1', 'action': 'WITHDRAW',
        'arc_id': arc.arc_id, 'project_id': project_id,
        'version': arc.version + 1, 'publication_approved': False})
