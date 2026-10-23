"""Read-only author action queue for existing AI-NOVEL longform projects.

Uses existing saved episodes, current human review receipts and recorded
reference-check coverage. It never evaluates prose quality, grants a PASS,
modifies an episode, runs a local model or authorizes publication.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256

from .database.episodes import EpisodeStore
from .manual_review_gate import review_state
from .reference_coverage_report import summarize_reference_coverage


class AuthorWorkflowDependenciesError(ValueError):
    """Sanitized operational error without private text or paths."""


@dataclass(frozen=True)
class AuthorWorkflowChapter:
    episode: int
    revision: int | None
    manuscript_sha256: str = field(default='', repr=False)
    draft_present: bool = False
    final_present: bool = False
    review_status: str = 'NOT_RUN'
    reference_status: str = 'NOT_RUN'
    next_action: str = 'CREATE_EPISODE'
    remaining_actions: tuple[str, ...] = ()
    human_review_required: bool = True
    publication_approved: bool = False


@dataclass(frozen=True)
class AuthorWorkflowDependencies:
    project_id: str = field(repr=False)
    through_episode: int = 0
    chapters: tuple[AuthorWorkflowChapter, ...] = ()
    pending_count: int = 0
    missing_episodes: int = 0
    missing_final_manuscripts: int = 0
    review_action_count: int = 0
    reference_action_count: int = 0
    status: str = 'AUTHOR_ACTIONS_REMAIN'
    publication_approved: bool = False


_ACTIONS = (
    'CREATE_EPISODE', 'PREPARE_DRAFT', 'WRITE_OR_REVIEW_FINAL',
    'COMPLETE_OR_REFRESH_QC', 'REVIEW_REFERENCES',
    'CONFIRM_HUMAN_REVIEW', 'SEPARATE_PUBLICATION_APPROVAL',
)


def build_author_workflow_dependencies(
    store: EpisodeStore, project_id: str, *, through_episode: int,
) -> AuthorWorkflowDependencies:
    """Read the same *current* project for every 1..N chapter, no skipping.

    Even when all available records appear complete, this queue never emits
    a release authorization. QC states represent recorded evidence only.
    """
    if (not isinstance(store, EpisodeStore) or type(project_id) is not str
            or not project_id or type(through_episode) is not int
            or not 1 <= through_episode <= 1000):
        raise AuthorWorkflowDependenciesError('기존 작품과 1~1000화 범위를 확인하세요.')
    store.get_project(project_id)
    episodes = {e.episode: e for e in store.list_episodes(project_id)}
    coverage = {r.episode: r for r in summarize_reference_coverage(
        store, project_id, through_episode=through_episode).chapters}
    rows: list[AuthorWorkflowChapter] = []
    for number in range(1, through_episode + 1):
        ep = episodes.get(number)
        if ep is None:
            rows.append(AuthorWorkflowChapter(
                number, None, remaining_actions=('CREATE_EPISODE',
                'PREPARE_DRAFT', 'WRITE_OR_REVIEW_FINAL',
                'COMPLETE_OR_REFRESH_QC', 'REVIEW_REFERENCES',
                'CONFIRM_HUMAN_REVIEW', 'SEPARATE_PUBLICATION_APPROVAL')))
            continue
        tasks: list[str] = []
        if not ep.draft.strip():
            tasks.append('PREPARE_DRAFT')
        if not ep.final_text.strip():
            tasks.append('WRITE_OR_REVIEW_FINAL')
        # Do not consult a past review receipt when no final manuscript exists.
        review = review_state(store, project_id, number)
        if review.incomplete_checks:
            tasks.append('COMPLETE_OR_REFRESH_QC')
        reference = coverage[number]
        # CHECKED_SCOPE_ONLY is deliberately not a copyright or QC PASS.
        if reference.status != 'CHECKED_SCOPE_ONLY':
            tasks.append('REVIEW_REFERENCES')
        if review.status != 'REVIEWED_QC_RECORDED_NOT_PUBLISHED':
            tasks.append('CONFIRM_HUMAN_REVIEW')
        tasks.append('SEPARATE_PUBLICATION_APPROVAL')
        ordered = tuple(action for action in _ACTIONS if action in tasks)
        rows.append(AuthorWorkflowChapter(
            number, ep.revision,
            sha256(ep.final_text.encode('utf-8')).hexdigest(),
            bool(ep.draft.strip()), bool(ep.final_text.strip()),
            review.status, reference.status, ordered[0], ordered))
    chapters = tuple(rows)
    return AuthorWorkflowDependencies(
        project_id, through_episode, chapters,
        sum(bool(c.remaining_actions) for c in chapters),
        sum(c.revision is None for c in chapters),
        sum(not c.final_present for c in chapters),
        sum('CONFIRM_HUMAN_REVIEW' in c.remaining_actions for c in chapters),
        sum('REVIEW_REFERENCES' in c.remaining_actions for c in chapters),
    )


def require_current_workflow_chapter(
    store: EpisodeStore, project_id: str, chapter: AuthorWorkflowChapter,
) -> None:
    """Invalidate stale UI navigation targets before loading an author's editor."""
    if (not isinstance(store, EpisodeStore) or type(chapter) is not AuthorWorkflowChapter
            or type(project_id) is not str or not project_id):
        raise AuthorWorkflowDependenciesError('회차 편집 이동을 다시 선택하세요.')
    if chapter.revision is None:
        raise AuthorWorkflowDependenciesError('저장되지 않은 회차는 열 수 없습니다.')
    ep = store.get_episode(project_id, chapter.episode)
    if (ep.revision != chapter.revision or
            sha256(ep.final_text.encode('utf-8')).hexdigest() != chapter.manuscript_sha256):
        raise AuthorWorkflowDependenciesError('원고가 변경됐습니다. 현재 작업 목록을 새로 확인하세요.')
