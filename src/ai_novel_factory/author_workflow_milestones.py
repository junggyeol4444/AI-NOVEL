"""Read-only 30 / 100 / 250 / 1000 episode action-pulse for authors."""
from __future__ import annotations

from dataclasses import dataclass

from .database.episodes import EpisodeStore
from .author_workflow_dependencies import (
    AuthorWorkflowDependencies, build_author_workflow_dependencies,
)


@dataclass(frozen=True)
class AuthorWorkflowMilestone:
    episodes: int
    saved: int
    draft_present: int
    final_present: int
    human_review_recorded_current: int
    references_checked_scope_only: int
    chapters_requiring_attention: int
    sample_attention_episodes: tuple[int, ...]
    status: str = 'UNVERIFIED_AUTHOR_WORK_PENDING'
    publication_approved: bool = False


@dataclass(frozen=True)
class AuthorWorkflowMilestones:
    milestones: tuple[AuthorWorkflowMilestone, ...]
    publication_approved: bool = False


def summarize_author_workflow_milestones(
    store: EpisodeStore, project_id: str,
    *, targets: tuple[int, ...] = (30, 100, 250, 1000),
    full_report: AuthorWorkflowDependencies | None = None,
) -> AuthorWorkflowMilestones:
    """Summarize actual stored records; never infer model or release success."""
    if (type(targets) is not tuple or not targets or len(targets) > 4
            or any(type(x) is not int or x not in {30, 100, 250, 1000} for x in targets)
            or len(set(targets)) != len(targets)):
        raise ValueError('30·100·250·1000화 중 중복 없는 조회 범위를 선택하세요.')
    limit = max(targets)
    report = full_report or build_author_workflow_dependencies(
        store, project_id, through_episode=limit)
    if report.project_id != project_id or report.through_episode < limit:
        raise ValueError('다른 작품 또는 짧은 범위의 현황을 재사용할 수 없습니다.')
    snapshots = []
    for target in sorted(targets):
        rows = report.chapters[:target]
        pending = tuple(ch.episode for ch in rows if ch.remaining_actions)
        snapshots.append(AuthorWorkflowMilestone(
            target,
            sum(ch.revision is not None for ch in rows),
            sum(ch.draft_present for ch in rows),
            sum(ch.final_present for ch in rows),
            sum(ch.review_status == 'REVIEWED_QC_RECORDED_NOT_PUBLISHED'
                for ch in rows),
            sum(ch.reference_status == 'CHECKED_SCOPE_ONLY' for ch in rows),
            len(pending), pending[:20]))
    return AuthorWorkflowMilestones(tuple(snapshots))
