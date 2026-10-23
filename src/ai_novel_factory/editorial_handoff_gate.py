"""Read-only, fail-closed editorial handoff matrix for existing saved episodes.

No QC pass, release authorization, reference clearance or model execution is
inferred from this report. All stages are informational until the user's
separate publication approval and final acceptance.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .database.episodes import EpisodeStore
from .editorial_issue_ledger import list_editorial_issues, EditorialIssueError
from .manual_review_gate import review_state
from .reference_coverage_report import summarize_reference_coverage
from .review_worklist import get_review_worklist


@dataclass(frozen=True)
class EditorialHandoffChapter:
    episode: int
    revision: int | None
    blockers: tuple[str, ...]
    open_issues: int
    stale_issues: int
    status: str = 'RELEASE_BLOCKED'
    publication_approved: bool = False


@dataclass(frozen=True)
class EditorialHandoffReport:
    project_id: str
    through_episode: int
    chapters: tuple[EditorialHandoffChapter, ...]
    attention_count: int
    status: str = 'RELEASE_BLOCKED'
    publication_approved: bool = False


def build_editorial_handoff(store: EpisodeStore, project_id: str, *,
                            through_episode: int, issue_folder: str | Path | None,
                            ) -> EditorialHandoffReport:
    if not isinstance(store, EpisodeStore) or type(project_id) is not str or not project_id:
        raise ValueError('기존 작품 SQLite를 먼저 선택해야 합니다.')
    if type(through_episode) is not int or not 1 <= through_episode <= 1000:
        raise ValueError('조회 범위는 1~1000화입니다.')
    store.get_project(project_id)
    saved = {item.episode: item for item in store.list_episodes(project_id)}
    work = {item.episode: item for item in get_review_worklist(store, project_id).chapters}
    reference = {row.episode: row.status for row in summarize_reference_coverage(
        store, project_id, through_episode=through_episode).chapters}
    chapters = []
    for number in range(1, through_episode + 1):
        ep = saved.get(number)
        if ep is None or not ep.final_text.strip():
            chapters.append(EditorialHandoffChapter(number, ep.revision if ep else None,
                                                    ('MISSING_FINAL',), 0, 0))
            continue
        blockers = []
        item = work[number]
        if item.failed_checks:
            blockers.append('QC_FAILED')
        if item.missing_checks or item.stale_checks or item.pending_checks:
            blockers.append('QC_NOT_COMPLETE_OR_STALE')
        reference_state = reference.get(number, 'NOT_RUN')
        if reference_state != 'CHECKED_SCOPE_ONLY':
            blockers.append('REFERENCE_NOT_FULLY_RECORDED')
        else:
            blockers.append('REFERENCE_SCOPE_ONLY_REQUIRES_AUTHOR_JUDGMENT')
        human = review_state(store, project_id, number)
        if not human.status.startswith('REVIEWED_'):
            blockers.append('HUMAN_REVIEW_NOT_CURRENT')
        elif human.incomplete_checks:
            blockers.append('HUMAN_REVIEW_QC_INCOMPLETE')
        if issue_folder is None:
            blockers.append('EDITORIAL_LEDGER_NOT_SELECTED')
            issues = ()
        else:
            issues = list_editorial_issues(store, project_id, number, folder=issue_folder)
        opened = sum(i.status.startswith('OPEN_') for i in issues)
        stale = sum(i.status.endswith('_STALE') for i in issues)
        if opened:
            blockers.append('EDITORIAL_OPEN_ISSUES')
        if stale:
            blockers.append('EDITORIAL_STALE_ISSUES')
        # This dashboard is not the separate release approval ledger.
        blockers.append('SEPARATE_PUBLICATION_APPROVAL_REQUIRED')
        chapters.append(EditorialHandoffChapter(
            number, ep.revision, tuple(dict.fromkeys(blockers)), opened, stale))
    return EditorialHandoffReport(project_id, through_episode, tuple(chapters),
                                  sum(bool(ch.blockers) for ch in chapters))
