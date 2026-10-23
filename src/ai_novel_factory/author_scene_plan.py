"""Author-entered per-episode scene beats; local append-only planning only.

No AI generation, SQLite updates, manuscript rewrites, quality PASS or publishing.
A new event is written only after a separate author approval for that action.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
import json
import os
import time

from .database.episodes import EpisodeStore
from .author_arc_ledger import canon_fingerprint, arc_ledger_fingerprint


class AuthorScenePlanError(ValueError):
    """Never interpolate private manuscripts, file paths or beat text."""


@dataclass(frozen=True)
class SceneBeat:
    goal: str
    conflict: str
    place: str
    must_include: str
    avoid: str


@dataclass(frozen=True)
class AuthorScenePlan:
    plan_id: str
    project_id: str = field(repr=False)
    episode: int
    beats: tuple[SceneBeat, ...] = field(repr=False)
    canon_sha256: str = field(repr=False)
    arc_sha256: str | None = field(repr=False)
    version: int = 1
    revoked: bool = False
    quality_certified: bool = False
    publication_approved: bool = False


MAX_EVENTS = 5000
MAX_EVENT_BYTES = 32768


def _folder(value: str | Path, *, database_path: str | Path | None = None) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise AuthorScenePlanError('작가가 선택한 기존 로컬 장면 계획 폴더가 필요합니다.')
    if database_path is not None:
        db = Path(database_path)
        if not db.is_absolute() or path.resolve() == db.parent.resolve():
            raise AuthorScenePlanError('장면 계획은 원고 DB와 분리된 기존 폴더에 저장해야 합니다.')
    return path


def _text(value: object, limit: int) -> str:
    if (type(value) is not str or not value.strip() or len(value) > limit
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)):
        raise AuthorScenePlanError('장면별 목표·갈등·장소·필수 사건·금지 사건을 확인하세요.')
    return value.strip()


def _episode(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 1000:
        raise AuthorScenePlanError('장면 계획은 1~1000화만 지원합니다.')
    return value


def _beat(value: object) -> SceneBeat:
    if type(value) is not dict or set(value) != {'goal','conflict','place','must_include','avoid'}:
        raise AuthorScenePlanError('장면 계획 필드가 올바르지 않습니다.')
    return SceneBeat(_text(value['goal'], 220), _text(value['conflict'], 220),
                     _text(value['place'], 120), _text(value['must_include'], 220),
                     _text(value['avoid'], 220))


def _event_files(folder: Path) -> tuple[Path, ...]:
    items = []
    for path in folder.iterdir():
        if path.name.startswith('anf-scene-beat-') and path.name.endswith('.json'):
            if path.is_symlink() or not path.is_file():
                raise AuthorScenePlanError('장면 계획 폴더에 허용되지 않은 파일이 있습니다.')
            items.append(path)
            if len(items) > MAX_EVENTS:
                raise AuthorScenePlanError('장면 계획 기록 개수가 제한을 초과했습니다.')
    return tuple(sorted(items, key=lambda p: p.name))


def scene_plan_fingerprint(folder: str | Path) -> str:
    digest = sha256()
    for path in _event_files(_folder(folder)):
        try:
            data = path.read_bytes()
        except OSError:
            raise AuthorScenePlanError('장면 계획 기록을 다시 읽지 못했습니다.') from None
        if len(data) > MAX_EVENT_BYTES:
            raise AuthorScenePlanError('장면 계획 기록이 용량을 초과했습니다.')
        digest.update(path.name.encode('utf-8') + b'\0' + len(data).to_bytes(8, 'big') + data)
    return digest.hexdigest()


def read_author_scene_plans(folder: str | Path, project_id: str) -> tuple[AuthorScenePlan, ...]:
    if type(project_id) is not str or not project_id:
        raise AuthorScenePlanError('작품을 먼저 선택하세요.')
    active: dict[str, AuthorScenePlan] = {}
    for path in _event_files(_folder(folder)):
        try:
            raw = path.read_bytes()
            if len(raw) > MAX_EVENT_BYTES:
                raise AuthorScenePlanError('장면 계획 파일 크기가 초과됐습니다.')
            event = json.loads(raw.decode('utf-8'))
        except (OSError, UnicodeError, ValueError):
            raise AuthorScenePlanError('장면 계획 기록을 읽지 못했습니다.') from None
        if (type(event) is not dict or event.get('format') != 'anf_scene_plan_v1'
                or event.get('action') not in ('SET', 'REVOKE')
                or type(event.get('project_id')) is not str
                or type(event.get('plan_id')) is not str
                or len(event['plan_id']) != 32
                or type(event.get('version')) is not int):
            raise AuthorScenePlanError('장면 계획 기록 형식이 올바르지 않습니다.')
        if event['project_id'] != project_id:
            continue
        pid = event['plan_id']
        old = active.get(pid)
        if event['action'] == 'SET':
            if old is not None or event['version'] != 1:
                raise AuthorScenePlanError('장면 계획 버전이 올바르지 않습니다.')
            try:
                episode = _episode(event['episode'])
                raw_beats = event['beats']
                if type(raw_beats) is not list or not 1 <= len(raw_beats) <= 20:
                    raise AuthorScenePlanError('장면 계획 개수가 올바르지 않습니다.')
                beats = tuple(_beat(item) for item in raw_beats)
                canon = event['canon_sha256']
                arc = event.get('arc_sha256')
                if (type(canon) is not str or len(canon) != 64
                        or (arc is not None and (type(arc) is not str or len(arc) != 64))):
                    raise AuthorScenePlanError('작품 설정 지문이 올바르지 않습니다.')
            except (KeyError, TypeError, ValueError):
                raise AuthorScenePlanError('장면 계획 내용이 올바르지 않습니다.') from None
            active[pid] = AuthorScenePlan(pid, project_id, episode, beats, canon, arc)
        else:
            if old is None or old.revoked or event['version'] != old.version + 1:
                raise AuthorScenePlanError('장면 계획 철회 이력이 올바르지 않습니다.')
            active[pid] = AuthorScenePlan(old.plan_id, old.project_id, old.episode,
                old.beats, old.canon_sha256, old.arc_sha256, event['version'], True)
    current = [item for item in active.values() if not item.revoked]
    if len({p.episode for p in current}) != len(current):
        raise AuthorScenePlanError('한 회차에 여러 활성 장면 계획이 있습니다.')
    return tuple(sorted(active.values(), key=lambda x: (x.episode, x.plan_id)))


def _append(folder: Path, event: dict) -> None:
    raw = json.dumps(event, ensure_ascii=False, sort_keys=True,
                     separators=(',', ':')).encode('utf-8')
    if len(raw) > MAX_EVENT_BYTES or len(_event_files(folder)) >= MAX_EVENTS:
        raise AuthorScenePlanError('장면 계획 저장 용량을 초과했습니다.')
    name = 'anf-scene-beat-' + f'{time.time_ns():020d}' + '-' + uuid4().hex + '.json'
    try:
        fd = os.open(folder / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
    except OSError:
        raise AuthorScenePlanError('새 장면 계획 기록을 저장하지 못했습니다.') from None


def save_author_scene_plan(store: EpisodeStore, project_id: str, *,
                           database_path: str | Path, folder: str | Path,
                           episode: int, beats: tuple[dict, ...],
                           arc_folder: str | Path | None = None,
                           explicit_author_save: bool = False) -> str:
    if explicit_author_save is not True:
        raise AuthorScenePlanError('이번 장면 계획 저장을 작가가 직접 승인해야 합니다.')
    if not isinstance(store, EpisodeStore):
        raise AuthorScenePlanError('기존 작품을 먼저 열어야 합니다.')
    episode = _episode(episode)
    if type(beats) is not tuple or not 1 <= len(beats) <= 20:
        raise AuthorScenePlanError('장면 수는 1~20개여야 합니다.')
    values = tuple(_beat(beat) for beat in beats)
    directory = _folder(folder, database_path=database_path)
    if any(p.episode == episode and not p.revoked
           for p in read_author_scene_plans(directory, project_id)):
        raise AuthorScenePlanError('이 회차에 이미 활성 장면 계획이 있습니다. 먼저 철회하세요.')
    canon = canon_fingerprint(store, project_id)
    arc = arc_ledger_fingerprint(arc_folder) if arc_folder is not None else None
    pid = uuid4().hex
    _append(directory, {'format':'anf_scene_plan_v1','action':'SET',
        'plan_id':pid,'project_id':project_id,'episode':episode,'version':1,
        'canon_sha256':canon,'arc_sha256':arc,
        'beats':[dict(goal=b.goal,conflict=b.conflict,place=b.place,
                      must_include=b.must_include,avoid=b.avoid) for b in values],
        'quality_certified':False,'publication_approved':False})
    return pid


def revoke_author_scene_plan(folder: str | Path, project_id: str, plan_id: str, *,
                             explicit_author_revoke: bool = False) -> None:
    if explicit_author_revoke is not True:
        raise AuthorScenePlanError('이번 장면 계획 철회를 작가가 직접 승인해야 합니다.')
    directory = _folder(folder)
    old = next((p for p in read_author_scene_plans(directory, project_id)
                if p.plan_id == plan_id and not p.revoked), None)
    if old is None:
        raise AuthorScenePlanError('철회할 활성 장면 계획이 없습니다.')
    _append(directory, {'format':'anf_scene_plan_v1','action':'REVOKE',
        'plan_id':plan_id,'project_id':project_id,'version':old.version+1,
        'quality_certified':False,'publication_approved':False})
