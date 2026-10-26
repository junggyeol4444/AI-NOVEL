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
# An immutable final-scene snapshot is separate from ordinary 1..20
# scene checkpoints. It captures real local-GGUF chapter-tail continuations
# before the complete unapproved chapter is atomically saved in SQLite.
FINAL_EPISODE_TAIL_STAGE = MAX_SCENES + 1
# Six immutable snapshots of ACTUALLY ACCEPTED GGUF continuation prose.
# Stage 21 remains the 133회차 final marker for backward compatibility.
# Stage 22..27 are append-only intermediate checkpoints, not final approval.
MAX_EPISODE_TAIL_PASSES = 6
FIRST_EPISODE_TAIL_PASS_STAGE = FINAL_EPISODE_TAIL_STAGE + 1
LAST_EPISODE_TAIL_PASS_STAGE = (
    FINAL_EPISODE_TAIL_STAGE + MAX_EPISODE_TAIL_PASSES)
# Each scene owns one accepted base and four immutable GGUF continuation
# snapshots. These are *not* final chapter or author-approved manuscript data.
# Keep all previous 0..27 stage IDs unchanged for legacy checkpoints.
MAX_SCENE_CONTINUATION_PASSES = 4
FIRST_SCENE_PROGRESS_STAGE = LAST_EPISODE_TAIL_PASS_STAGE + 1
SCENE_PROGRESS_STRIDE = MAX_SCENE_CONTINUATION_PASSES + 1
LAST_SCENE_PROGRESS_STAGE = (
    FIRST_SCENE_PROGRESS_STAGE + MAX_SCENES * SCENE_PROGRESS_STRIDE - 1)


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
        if type(stage) is not int or not 0 <= stage <= LAST_SCENE_PROGRESS_STAGE:
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

    @staticmethod
    def scene_progress_stage(scene: int, pass_index: int = 0) -> int:
        """Get the new per-scene stage without changing old 0..27 IDs.

        Pass zero is the selected local-model base draft after one revision;
        passes 1..4 are accepted consecutive local GGUF continuations.
        """
        if (type(scene) is not int or not 1 <= scene <= MAX_SCENES
                or type(pass_index) is not int
                or not 0 <= pass_index <= MAX_SCENE_CONTINUATION_PASSES):
            raise SceneCheckpointError('장면 이어쓰기 단계 범위가 올바르지 않습니다.')
        return (FIRST_SCENE_PROGRESS_STAGE
                + (scene - 1) * SCENE_PROGRESS_STRIDE + pass_index)

    def recover_scene_progress(self, scene: int) -> tuple[str | None, int, bool]:
        """Return exact accepted draft, completed tail count, final-stage flag.

        An ordinary completed stage 1..20 from older checkpoints remains
        valid. For new work, every 28..127 snapshot must retain the exact
        previous Korean prose as its prefix. Missing middle passes, orphaned
        passes, or a disagreeing final stage require explicit author review;
        do not replay/replace already generated prose or promote to approval.
        """
        start = self.scene_progress_stage(scene, 0)
        base = self.load_stage(start)
        final = self.load_stage(scene)
        if base is None:
            for pass_index in range(1, MAX_SCENE_CONTINUATION_PASSES + 1):
                if self.load_stage(self.scene_progress_stage(scene, pass_index)):
                    raise SceneCheckpointError(
                        '장면 시작 기록 없이 이어쓰기 중간 기록만 있습니다.')
            return final, 0, final is not None
        latest = base
        completed = 0
        missing_seen = False
        for pass_index in range(1, MAX_SCENE_CONTINUATION_PASSES + 1):
            recovered = self.load_stage(self.scene_progress_stage(scene, pass_index))
            if recovered is None:
                missing_seen = True
                continue
            if missing_seen:
                raise SceneCheckpointError(
                    '장면 이어쓰기 중간 기록이 누락되어 재개하지 않습니다.')
            if not recovered.startswith(latest.rstrip() + '\n\n'):
                raise SceneCheckpointError(
                    '장면 이어쓰기의 저장 원문이 이전 문장과 불일치합니다.')
            latest = recovered
            completed += 1
        if final is not None:
            if final != latest:
                raise SceneCheckpointError(
                    '장면 최종 기록과 이어쓰기 중간 원문이 일치하지 않습니다.')
            return final, completed, True
        return latest, completed, False

    def recover_episode_tail(self, original_scene: str) -> tuple[str, int, bool]:
        """Recover every accepted REAL GGUF tail without replaying its calls.

        Returns (exact recovered scene, accepted_passes, finalized). Stage 21
        is the existing completed marker; 22..27 are accepted continuation
        snapshots. Every step must extend the previous exact prose. A missing
        middle snapshot, changed text, or final/partial disagreement blocks
        automatic resume. Old stage-21-only checkpoints remain supported.
        This is only UNAPPROVED_AI_DRAFT recovery, not an author sign-off.
        """
        if type(original_scene) is not str or not original_scene.strip():
            raise SceneCheckpointError(
                '기존 장면 원문이 없어 최종 이어쓰기를 자동 복원하지 않습니다.')
        latest = original_scene
        count = 0
        missing_seen = False
        for stage in range(
                FIRST_EPISODE_TAIL_PASS_STAGE,
                LAST_EPISODE_TAIL_PASS_STAGE + 1):
            recovered = self.load_stage(stage)
            if recovered is None:
                missing_seen = True
                continue
            if missing_seen:
                raise SceneCheckpointError(
                    '회차 이어쓰기 중간 기록이 누락되어 자동 재개하지 않습니다.')
            if not recovered.startswith(latest.rstrip() + '\n\n'):
                raise SceneCheckpointError(
                    '회차 이어쓰기 기록의 원문 접두가 달라 자동 재개하지 않습니다.')
            latest = recovered
            count += 1
        final = self.load_stage(FINAL_EPISODE_TAIL_STAGE)
        if final is not None:
            if count:
                if final != latest:
                    raise SceneCheckpointError(
                        '회차 최종 기록과 중간 이어쓰기 기록이 다릅니다.')
            elif not (final == latest
                      or final.startswith(latest.rstrip() + '\n\n')):
                # Backward compatible with pre-134 stage-21-only snapshots.
                raise SceneCheckpointError(
                    '회차 최종 장면 기록이 기존 장면과 일치하지 않습니다.')
            latest = final
        return latest, count, final is not None

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
            rows[1] += sum(
                1 for file in folder.glob('*.json')
                if (file.is_file() and not file.is_symlink()
                    and file.stem.isdecimal()
                    and 0 <= int(file.stem) <= LAST_SCENE_PROGRESS_STAGE)
            )
        return tuple(SceneCheckpointOverview(n, *counts[n]) for n in sorted(counts))
    except OSError:
        raise SceneCheckpointError('임시 장면 목록을 확인하지 못했습니다.') from None
