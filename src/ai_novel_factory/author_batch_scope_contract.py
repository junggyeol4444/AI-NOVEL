"""기존 집필 작업 목록과 로컬 AI 배치 범위를 연결하는 읽기 전용 계약.

사용자가 직접 요청할 때 기존 SQLite의 저장 상태만 읽는다. 참고작 본문,
원고 본문, 모델 파일은 읽거나 수정하지 않으며 검사 PASS를 생성하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import PurePath

from .author_workflow_dependencies import build_author_workflow_dependencies


_ALLOWED_REFERENCE_TYPES = ('.txt', '.md', '.epub', '.docx', '.pdf')


class BatchScopeContractError(ValueError):
    """원고나 로컬 경로를 포함하지 않는 범위 오류."""


@dataclass(frozen=True)
class BatchScopeSnapshot:
    project_id: str = field(repr=False)
    through_episode: int = 0
    target_chars: int = 0
    scenes_per_episode: int = 0
    stored_episodes: int = 0
    missing_episodes: int = 0
    missing_final_manuscripts: int = 0
    human_review_needed: int = 0
    reference_review_needed: int = 0
    reference_type_counts: tuple[tuple[str, int], ...] = ()
    unknown_reference_count: int = 0
    fingerprint: str = field(default='', repr=False)
    status: str = 'SCOPE_PREVIEW_ONLY'


def _reference_types(selected_paths) -> tuple[tuple[tuple[str, int], ...], int]:
    if not isinstance(selected_paths, (tuple, list)):
        raise BatchScopeContractError('참고작 선택을 다시 확인하세요.')
    if len(selected_paths) > 100:
        raise BatchScopeContractError('참고작은 직접 선택한 최대 100개 범위로 제한합니다.')
    counts = {suffix: 0 for suffix in _ALLOWED_REFERENCE_TYPES}
    unknown = 0
    for raw in selected_paths:
        if not isinstance(raw, (str, PurePath)) or not str(raw).strip():
            raise BatchScopeContractError('참고작 선택 항목이 올바르지 않습니다.')
        suffix = PurePath(str(raw)).suffix.casefold()
        if suffix in counts:
            counts[suffix] += 1
        else:
            unknown += 1
    return tuple((suffix, counts[suffix]) for suffix in _ALLOWED_REFERENCE_TYPES), unknown


def preview_existing_batch_scope(store, project_id: str, *, through_episode: int,
                                 target_chars: int, scenes_per_episode: int,
                                 reference_paths=()) -> BatchScopeSnapshot:
    """현재 저장 회차/검수/참고작 선택 확장자만 집계. 집필을 시작하지 않는다."""
    if (type(project_id) is not str or not project_id
            or type(through_episode) is not int or not 1 <= through_episode <= 1000
            or type(target_chars) is not int or not 1 <= target_chars <= 50000
            or type(scenes_per_episode) is not int or not 1 <= scenes_per_episode <= 20):
        raise BatchScopeContractError('기존 작품·회차·분량·장면 범위를 다시 선택하세요.')
    types, unknown = _reference_types(reference_paths)
    report = build_author_workflow_dependencies(
        store, project_id, through_episode=through_episode)
    rows = tuple((c.episode, c.revision, c.manuscript_sha256,
                  c.review_status, c.reference_status, c.remaining_actions)
                 for c in report.chapters)
    # 경로와 본문은 저장/표시하지 않는다. 선택한 참고작의 순서/파일명은
    # 지문 계산에만 사용해 변경된 선택을 과거 승인 범위로 오인하지 않는다.
    selection = tuple(str(p) for p in reference_paths)
    fingerprint = sha256(repr((project_id, through_episode, target_chars,
                               scenes_per_episode, selection, rows)).encode('utf-8')).hexdigest()
    return BatchScopeSnapshot(
        project_id=project_id, through_episode=through_episode,
        target_chars=target_chars, scenes_per_episode=scenes_per_episode,
        stored_episodes=through_episode - report.missing_episodes,
        missing_episodes=report.missing_episodes,
        missing_final_manuscripts=report.missing_final_manuscripts,
        human_review_needed=report.review_action_count,
        reference_review_needed=report.reference_action_count,
        reference_type_counts=types, unknown_reference_count=unknown,
        fingerprint=fingerprint)


def require_current_batch_scope(snapshot: BatchScopeSnapshot, store, project_id: str,
                                *, through_episode: int, target_chars: int,
                                scenes_per_episode: int, reference_paths=()) -> None:
    """배치 설정으로 이동하기 직전에 현재 SQLite/선택 범위를 다시 확인한다."""
    if type(snapshot) is not BatchScopeSnapshot or snapshot.project_id != project_id:
        raise BatchScopeContractError('작품이 바뀌었습니다. 범위를 다시 확인하세요.')
    current = preview_existing_batch_scope(
        store, project_id, through_episode=through_episode,
        target_chars=target_chars, scenes_per_episode=scenes_per_episode,
        reference_paths=reference_paths)
    if current.fingerprint != snapshot.fingerprint:
        raise BatchScopeContractError('원고·검수 기록 또는 참고작 선택이 변경됐습니다. 다시 확인하세요.')
