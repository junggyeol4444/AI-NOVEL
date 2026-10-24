"""작가 승인 전 장면 임시 파일과 저장 최종본의 읽기 전용 연결 대조.

임시 장면 문자열이 저장 최종본에 포함되는지만 확인한다. 일치/불일치는
원고 품질, AI 재개 가능 여부, 작가 검수 또는 출판 승인 판정이 아니다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
import re

from .author_scene_checkpoint_integrity import (
    SceneIntegrityError, _read_file, _record_valid, _STAGE,
    audit_scene_checkpoints, require_current_scene_checkpoint_audit,
)
from .database.episodes import EpisodeStore
from .scene_checkpoint_store import _identity as checkpoint_project_identity


class CheckpointFinalCoverageError(ValueError):
    """개인 파일 경로·원고 본문을 출력하지 않는 조회 실패."""


@dataclass(frozen=True)
class CheckpointFinalChapter:
    episode: int
    revision: int | None
    saved_final_characters: int
    checkpoint_sets: int
    scene_stage_files: int
    exact_in_final: int
    changed_or_missing: int
    invalid_files: int
    requires_author_review: bool = True


@dataclass(frozen=True)
class CheckpointFinalCoverage:
    project_id: str = field(repr=False)
    database_path: str = field(repr=False)
    checkpoint_root: str = field(repr=False)
    through_episode: int = 0
    chapters: tuple[CheckpointFinalChapter, ...] = ()
    source_fingerprint: str = field(default='', repr=False)
    quality_certified: bool = False
    resume_approved: bool = False
    publication_approved: bool = False
    status: str = 'READ_ONLY_AUTHOR_REVIEW_REQUIRED'

    @property
    def changed_or_missing(self) -> int:
        return sum(row.changed_or_missing for row in self.chapters)


def _compact(text: str) -> str:
    return re.sub(r'\s+', '', text)


def build_checkpoint_final_coverage(
    store: EpisodeStore, database_path: str | Path, project_id: str, *,
    through_episode: int, checkpoint_root: str | Path,
) -> CheckpointFinalCoverage:
    """1~선택 회차의 실제 임시 장면 본문과 저장 최종본을 로컬에서 대조."""
    try:
        audit = audit_scene_checkpoints(
            store, database_path, project_id,
            through_episode=through_episode, checkpoint_root=checkpoint_root)
        root = Path(audit.checkpoint_root)
        project_hash = checkpoint_project_identity(database_path, project_id)
        saved = {ep.episode: ep for ep in store.list_episodes(project_id)
                 if 1 <= ep.episode <= through_episode}
        final_compact = {}
        counts = {n: [0, 0] for n in range(1, through_episode + 1)}
        if root.exists():
            prefix = project_hash[:20] + '_'
            for folder in sorted(root.glob(prefix + '*'), key=lambda p: p.name):
                if folder.is_symlink() or not folder.is_dir():
                    raise CheckpointFinalCoverageError('임시 장면 폴더가 변경됐습니다.')
                match = re.fullmatch(re.escape(prefix) + r'(\d{4})_([0-9a-f]{32})',
                                     folder.name)
                if match is None:
                    raise CheckpointFinalCoverageError('임시 장면 폴더 형식이 다릅니다.')
                episode, suffix = int(match.group(1)), match.group(2)
                if episode > through_episode:
                    continue
                for path in sorted(folder.iterdir(), key=lambda p: p.name):
                    stage = _STAGE.fullmatch(path.name)
                    if stage is None or int(stage.group(1)) == 0:
                        continue  # 0단계 플롯은 장면 본문이 아니다.
                    data = _read_file(path)
                    if not _record_valid(data, expected_project=project_hash,
                                         episode=episode, stage=int(stage.group(1)),
                                         suffix=suffix):
                        continue  # 손상 수는 기존 무결성 조회에서 별도로 제공한다.
                    item = json.loads(data.decode('utf-8'))
                    checkpoint_text = _compact(item['text'])
                    if episode not in final_compact:
                        ep = saved.get(episode)
                        final_compact[episode] = _compact(ep.final_text) if ep else ''
                    if final_compact[episode] and checkpoint_text in final_compact[episode]:
                        counts[episode][0] += 1
                    else:
                        counts[episode][1] += 1
        rows = []
        for original in audit.chapters:
            ep = saved.get(original.episode)
            rows.append(CheckpointFinalChapter(
                episode=original.episode,
                revision=original.revision,
                saved_final_characters=len(_compact(ep.final_text)) if ep else 0,
                checkpoint_sets=original.checkpoint_sets,
                scene_stage_files=counts[original.episode][0] + counts[original.episode][1],
                exact_in_final=counts[original.episode][0],
                changed_or_missing=counts[original.episode][1],
                invalid_files=original.invalid_files,
            ))
        # 중간에 원고/임시 파일이 바뀐 경우 결과를 반환하지 않는다.
        require_current_scene_checkpoint_audit(audit, store, database_path, project_id)
        digest = sha256(repr((audit.fingerprint, tuple(rows))).encode('utf-8')).hexdigest()
        return CheckpointFinalCoverage(
            project_id=project_id, database_path=audit.database_path,
            checkpoint_root=audit.checkpoint_root, through_episode=through_episode,
            chapters=tuple(rows), source_fingerprint=digest)
    except (SceneIntegrityError, OSError, ValueError, TypeError, LookupError) as exc:
        if isinstance(exc, CheckpointFinalCoverageError):
            raise
        raise CheckpointFinalCoverageError(
            '저장 원고 또는 임시 장면이 변경됐거나 조회할 수 없습니다.') from None


def require_current_checkpoint_final_coverage(
    snapshot: CheckpointFinalCoverage, store: EpisodeStore,
    database_path: str | Path, project_id: str,
) -> None:
    """별도 두 번째 GUI 클릭에서 파일·저장 원고를 다시 대조한다."""
    if not isinstance(snapshot, CheckpointFinalCoverage) or snapshot.project_id != project_id:
        raise CheckpointFinalCoverageError('작품이 변경됐습니다. 다시 조회하세요.')
    current = build_checkpoint_final_coverage(
        store, database_path, project_id,
        through_episode=snapshot.through_episode,
        checkpoint_root=snapshot.checkpoint_root)
    if (current.source_fingerprint != snapshot.source_fingerprint
            or current.database_path != snapshot.database_path
            or current.chapters != snapshot.chapters):
        raise CheckpointFinalCoverageError('임시 장면·원고 변경으로 이전 조회가 무효화됐습니다.')
