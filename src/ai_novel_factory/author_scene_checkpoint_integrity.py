"""기존 로컬 장면 임시 초고의 읽기 전용 파일 형식·변경 지문 확인.

파일 자체의 SHA 및 내부 초고 SHA가 맞아도 현재 작가 자료·모델 동의가
일치한다는 뜻은 아니다. 자동 재개, QC 합격, 출판 승인은 이 모듈에 없다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from .database.episodes import EpisodeStore
from .scene_checkpoint_store import (
    MAX_SCENES, MAX_STAGE_BYTES, MAX_STAGE_FILE_BYTES,
    _identity as checkpoint_project_identity,
)


class SceneIntegrityError(ValueError):
    """로컬 경로와 원고를 출력하지 않는 실패 메시지."""


@dataclass(frozen=True)
class SceneIntegrityChapter:
    episode: int
    stored_state: str
    revision: int | None
    checkpoint_sets: int
    stage_files: int
    format_valid_files: int
    invalid_files: int
    reuse_approved: bool = False


@dataclass(frozen=True)
class SceneIntegrityAudit:
    project_id: str = field(repr=False)
    database_path: str = field(repr=False)
    checkpoint_root: str = field(repr=False)
    through_episode: int = 0
    chapters: tuple[SceneIntegrityChapter, ...] = ()
    fingerprint: str = field(default='', repr=False)
    model_approved: bool = False
    manuscript_approved: bool = False
    publication_approved: bool = False

    @property
    def invalid_files(self) -> int:
        return sum(row.invalid_files for row in self.chapters)

    @property
    def stage_files(self) -> int:
        return sum(row.stage_files for row in self.chapters)


_HEX64 = re.compile(r'^[0-9a-f]{64}$')
_STAGE = re.compile(r'^(0[0-9]|1[0-9]|20)\.json$')


def _read_file(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise SceneIntegrityError('장면 임시 파일 경로를 신뢰할 수 없습니다.')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, 'rb') as stream:
            if os.fstat(stream.fileno()).st_size > MAX_STAGE_FILE_BYTES:
                raise SceneIntegrityError('임시 장면 파일 크기가 제한을 초과했습니다.')
            data = stream.read(MAX_STAGE_FILE_BYTES + 1)
    except OSError:
        raise SceneIntegrityError('장면 임시 파일을 읽지 못했습니다.') from None
    if len(data) > MAX_STAGE_FILE_BYTES:
        raise SceneIntegrityError('장면 임시 파일 크기가 제한을 초과했습니다.')
    return data


def _record_valid(data: bytes, *, expected_project: str,
                  episode: int, stage: int, suffix: str) -> bool:
    try:
        item = json.loads(data.decode('utf-8'))
        if type(item) is not dict or type(item.get('identity')) is not dict:
            return False
        ident = item['identity']
        if set(ident) != {'version', 'project', 'episode', 'source', 'plan', 'consent'}:
            return False
        if (type(ident['version']) is not int or ident['version'] != 1
                or ident['project'] != expected_project
                or type(ident['episode']) is not int or ident['episode'] != episode
                or any(type(ident[key]) is not str or not _HEX64.fullmatch(ident[key])
                       for key in ('project', 'source', 'plan', 'consent'))):
            return False
        key = sha256(json.dumps(ident, sort_keys=True, separators=(',', ':'))
                     .encode('ascii')).hexdigest()
        text = item.get('text')
        if (suffix != key[:32] or type(item.get('stage')) is not int
                or item['stage'] != stage or type(text) is not str
                or not text.strip() or len(text.encode('utf-8')) > MAX_STAGE_BYTES
                or item.get('text_sha256') != sha256(text.encode('utf-8')).hexdigest()
                or item.get('approval') != 'UNAPPROVED_AI_DRAFT'):
            return False
        return True
    except (ValueError, UnicodeError, TypeError, KeyError, AttributeError):
        return False


def audit_scene_checkpoints(store: EpisodeStore, database_path: str | Path,
                            project_id: str, *, through_episode: int,
                            checkpoint_root: str | Path) -> SceneIntegrityAudit:
    """선택 작품의 저장 원고와 임시 장면 원본을 읽기 전용으로 전수 확인."""
    database = Path(database_path)
    root = Path(checkpoint_root)
    if (not isinstance(store, EpisodeStore) or type(project_id) is not str
            or not project_id or not database.is_absolute() or database.is_symlink()
            or not root.is_absolute() or root.is_symlink()
            or type(through_episode) is not int or not 1 <= through_episode <= 1000):
        raise SceneIntegrityError('현재 작품과 로컬 폴더 및 1~1000화 범위를 확인하세요.')
    try:
        project_hash = checkpoint_project_identity(database, project_id)
        saved = {row.episode: row for row in store.list_episodes(project_id)
                 if row.episode <= through_episode}
        counts = {n: [0, 0, 0, 0] for n in range(1, through_episode + 1)}
        files = []
        if root.exists():
            if not root.is_dir() or root.is_symlink():
                raise SceneIntegrityError('임시 장면 폴더를 신뢰할 수 없습니다.')
            prefix = project_hash[:20] + '_'
            folders = sorted(root.glob(prefix + '*'), key=lambda p: p.name)
            if len(folders) > 1000:
                raise SceneIntegrityError('임시 장면 묶음 수가 조회 한도를 초과했습니다.')
            for folder in folders:
                if folder.is_symlink() or not folder.is_dir():
                    raise SceneIntegrityError('임시 장면 하위 폴더를 신뢰할 수 없습니다.')
                match = re.fullmatch(re.escape(prefix) + r'(\d{4})_([0-9a-f]{32})',
                                     folder.name)
                if match is None:
                    raise SceneIntegrityError('임시 장면 폴더 이름이 올바르지 않습니다.')
                number, suffix = int(match.group(1)), match.group(2)
                if not 1 <= number <= 1000:
                    raise SceneIntegrityError('임시 장면 회차가 올바르지 않습니다.')
                if number > through_episode:
                    continue
                counts[number][0] += 1
                entries = sorted(folder.iterdir(), key=lambda p: p.name)
                if not entries:
                    counts[number][3] += 1
                for path in entries:
                    if len(files) >= 25000:
                        raise SceneIntegrityError('임시 장면 파일 수가 조회 한도를 초과했습니다.')
                    if path.is_symlink() or not path.is_file():
                        raise SceneIntegrityError('임시 장면 파일 경로를 신뢰할 수 없습니다.')
                    counts[number][1] += 1
                    stage_match = _STAGE.fullmatch(path.name)
                    data = _read_file(path)
                    valid = bool(stage_match and _record_valid(
                        data, expected_project=project_hash, episode=number,
                        stage=int(stage_match.group(1)), suffix=suffix))
                    counts[number][2 if valid else 3] += 1
                    files.append((folder.name, path.name, sha256(data).hexdigest(), valid))
        chapters = []
        saved_stamp = []
        for number in range(1, through_episode + 1):
            row = saved.get(number)
            state = ('MISSING' if row is None else
                     'FINAL_SAVED' if row.final_text.strip() else
                     'DRAFT_ONLY' if row.draft.strip() else 'EMPTY_SAVED')
            revision = row.revision if row else None
            saved_stamp.append((number, revision, state,
                                sha256(repr((row.plot, row.draft, row.final_text,
                                             row.summary)).encode('utf-8')).hexdigest()
                                if row else None))
            chapters.append(SceneIntegrityChapter(number, state, revision,
                                                  *counts[number]))
        fingerprint = sha256(repr((str(database.resolve()), project_id,
                                   str(root.resolve()), through_episode,
                                   tuple(saved_stamp), tuple(files))).encode('utf-8')).hexdigest()
        return SceneIntegrityAudit(project_id, str(database.resolve()),
                                   str(root.resolve()), through_episode,
                                   tuple(chapters), fingerprint)
    except SceneIntegrityError:
        raise
    except (OSError, ValueError, TypeError, LookupError):
        raise SceneIntegrityError('원고 또는 임시 장면 원본을 안전하게 읽지 못했습니다.') from None


def require_current_scene_checkpoint_audit(snapshot: SceneIntegrityAudit,
                                            store: EpisodeStore,
                                            database_path: str | Path,
                                            project_id: str) -> None:
    """작가가 두 번째 클릭할 때 SQLite와 임시 파일 바이트를 다시 확인."""
    if not isinstance(snapshot, SceneIntegrityAudit):
        raise SceneIntegrityError('이전 임시 장면 조회가 없습니다.')
    current = audit_scene_checkpoints(
        store, database_path, project_id,
        through_episode=snapshot.through_episode,
        checkpoint_root=snapshot.checkpoint_root)
    if (current.fingerprint != snapshot.fingerprint
            or current.project_id != snapshot.project_id
            or current.database_path != snapshot.database_path):
        raise SceneIntegrityError('저장 원고나 임시 장면이 변경됐습니다. 다시 조회하세요.')

@dataclass(frozen=True)
class SceneStageChoice:
    """작가가 직접 선택할 임시 장면 파일의 읽기 전용 지문."""
    episode: int
    folder_name: str = field(repr=False)
    stage: int = 0
    file_sha256: str = field(default='', repr=False)
    characters: int = 0
    status: str = 'UNAPPROVED_DRAFT_REVIEW_ONLY'
    publication_approved: bool = False


def list_author_scene_stage_choices(
        audit: SceneIntegrityAudit, store: EpisodeStore,
        database_path: str | Path, project_id: str, *,
        episode: int) -> tuple[SceneStageChoice, ...]:
    """검증된 장면 파일만 작가의 명시적 선택 목록에 표시한다."""
    if (type(audit) is not SceneIntegrityAudit or type(episode) is not int
            or not 1 <= episode <= audit.through_episode):
        raise SceneIntegrityError('조회한 작품·회차를 다시 선택하세요.')
    require_current_scene_checkpoint_audit(audit, store, database_path, project_id)
    root = Path(audit.checkpoint_root)
    prefix = checkpoint_project_identity(database_path, project_id)[:20] + f'_{episode:04d}_'
    choices = []
    if root.exists():
        for folder in sorted(root.glob(prefix + '*'), key=lambda p: p.name):
            if (folder.is_symlink() or not folder.is_dir()
                    or re.fullmatch(re.escape(prefix) + r'[0-9a-f]{32}', folder.name) is None):
                raise SceneIntegrityError('임시 장면 묶음이 변경됐습니다.')
            suffix = folder.name[-32:]
            for path in sorted(folder.iterdir(), key=lambda p: p.name):
                if path.is_symlink() or not path.is_file():
                    raise SceneIntegrityError('임시 장면 경로를 신뢰할 수 없습니다.')
                match = _STAGE.fullmatch(path.name)
                if match is None or int(match.group(1)) == 0:
                    continue
                raw = _read_file(path)
                stage = int(match.group(1))
                if not _record_valid(raw, expected_project=checkpoint_project_identity(
                        database_path, project_id), episode=episode,
                        stage=stage, suffix=suffix):
                    continue
                text = json.loads(raw.decode('utf-8'))['text']
                choices.append(SceneStageChoice(
                    episode, folder.name, stage, sha256(raw).hexdigest(), len(text)))
    require_current_scene_checkpoint_audit(audit, store, database_path, project_id)
    return tuple(choices)


def read_author_scene_stage_choice(
        audit: SceneIntegrityAudit, store: EpisodeStore,
        database_path: str | Path, project_id: str,
        choice: SceneStageChoice) -> str:
    """별도 클릭에서 전체 원고·파일 지문을 재확인한 후 로컬 미승인 장면만 읽는다."""
    if type(choice) is not SceneStageChoice:
        raise SceneIntegrityError('읽을 임시 장면을 다시 선택하세요.')
    current = list_author_scene_stage_choices(
        audit, store, database_path, project_id, episode=choice.episode)
    if choice not in current:
        raise SceneIntegrityError('임시 장면 또는 원고가 변경됐습니다. 다시 조회하세요.')
    path = Path(audit.checkpoint_root) / choice.folder_name / f'{choice.stage:02d}.json'
    raw = _read_file(path)
    if sha256(raw).hexdigest() != choice.file_sha256:
        raise SceneIntegrityError('임시 장면 내용이 변경됐습니다.')
    record = json.loads(raw.decode('utf-8'))
    if not _record_valid(raw, expected_project=checkpoint_project_identity(
            database_path, project_id), episode=choice.episode,
            stage=choice.stage, suffix=choice.folder_name[-32:]):
        raise SceneIntegrityError('임시 장면 형식을 신뢰할 수 없습니다.')
    return record['text']
