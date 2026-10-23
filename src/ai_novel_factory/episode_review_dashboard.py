"""Read-only whole-book review dashboard from the existing SQLite project.

Combines the real per-revision QC records, selected reference comparison
coverage, and separate author review ledger. A QC PASS or a checked reference
scope is never promoted to human review, publication consent or literary
quality certification. No model is invoked and no data is changed.
"""
from __future__ import annotations

from dataclasses import dataclass

from .database.episodes import EpisodeStore
from .manual_review_gate import review_state
from .reference_coverage_report import summarize_reference_coverage
from .review_worklist import EXPECTED_CHECKS, get_review_worklist


@dataclass(frozen=True)
class ReviewDashboardChapter:
    episode: int
    revision: int | None
    manuscript: str
    qc_state: str
    qc_missing: int
    qc_stale: int
    qc_pending: int
    qc_failed: int
    reference_scope: str
    human_review: str
    requires_attention: bool = True
    publication_approved: bool = False


@dataclass(frozen=True)
class ReviewDashboard:
    project_id: str
    through_episode: int
    chapters: tuple[ReviewDashboardChapter, ...]
    missing_manuscripts: int
    unreviewed_or_stale: int
    reference_not_examined: int
    qc_incomplete: int
    publication_approved: bool = False


def build_review_dashboard(
    store: EpisodeStore, project_id: str, *, through_episode: int,
) -> ReviewDashboard:
    """Never use older revision PASS or a ledger for another project."""
    if not isinstance(store, EpisodeStore):
        raise ValueError('현재 기존 작품 SQLite를 열어야 합니다.')
    if type(project_id) is not str or not project_id:
        raise ValueError('작품을 선택해야 합니다.')
    if type(through_episode) is not int or not 1 <= through_episode <= 1000:
        raise ValueError('조회 범위는 1~1000화입니다.')
    store.get_project(project_id)
    episodes = {item.episode: item for item in store.list_episodes(project_id)}
    work = {item.episode: item for item in get_review_worklist(store, project_id).chapters}
    coverage = summarize_reference_coverage(
        store, project_id, through_episode=through_episode)
    references = {item.episode: item.status for item in coverage.chapters}
    rows = []
    for number in range(1, through_episode + 1):
        episode = episodes.get(number)
        if episode is None:
            rows.append(ReviewDashboardChapter(
                number, None, 'MISSING', 'NOT_RUN', len(EXPECTED_CHECKS),
                0, 0, 0, references[number], 'UNREVIEWED'))
            continue
        item = work[number]
        state = review_state(store, project_id, number)
        if not episode.final_text.strip():
            manuscript = 'DRAFT_ONLY' if episode.draft.strip() else 'EMPTY'
        else:
            manuscript = 'FINAL_SAVED_NOT_PUBLISHED'
        if item.failed_checks:
            qc_state = 'FAILED'
        elif item.missing_checks or item.stale_checks or item.pending_checks:
            qc_state = 'INCOMPLETE_OR_STALE'
        else:
            qc_state = 'RECORDED_SCOPE_ONLY'
        rows.append(ReviewDashboardChapter(
            number, episode.revision, manuscript, qc_state,
            len(item.missing_checks), len(item.stale_checks),
            len(item.pending_checks), len(item.failed_checks),
            references[number], state.status))
    chapters = tuple(rows)
    return ReviewDashboard(
        project_id, through_episode, chapters,
        sum(c.manuscript in {'MISSING', 'EMPTY'} for c in chapters),
        sum(not c.human_review.startswith('REVIEWED_') for c in chapters),
        sum(c.reference_scope in {'NOT_RUN', 'STALE', 'INCOMPLETE'}
            for c in chapters),
        sum(c.qc_state != 'RECORDED_SCOPE_ONLY' for c in chapters))
