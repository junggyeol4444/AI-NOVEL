"""작가 직접 선택 참고작과 저장 최종본의 재검사 대기열(읽기 전용).

과거 QC의 selected 개수는 현재 선택한 파일의 동일성을 증명하지 못한다.
현재 선택 지문을 이전 검사에 결합하거나 PASS·출판 승인을 생성하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256

from .author_reference_selection_lease import (
    ReferenceLeaseError, preview_reference_selection,
)
from .author_workflow_dependencies import build_author_workflow_dependencies
from .database.episodes import EpisodeStore
from .reference_coverage_report import summarize_reference_coverage


class ReferenceRecheckQueueError(ValueError):
    """참고작 원문·파일 경로·원고 내용을 노출하지 않는 오류."""


@dataclass(frozen=True)
class ReferenceRecheckChapter:
    episode: int
    revision: int | None
    final_present: bool
    saved_scope_status: str
    selected_in_record: int
    compared_in_record: int
    unexamined_in_record: int
    human_review_status: str
    next_action: str
    publication_approved: bool = False


@dataclass(frozen=True)
class ReferenceRecheckQueue:
    project_id: str = field(repr=False)
    through_episode: int = 0
    selected_count: int = 0
    selected_formats: tuple[tuple[str, int], ...] = ()
    chapters: tuple[ReferenceRecheckChapter, ...] = ()
    missing_final: int = 0
    needs_fresh_scan: int = 0
    prior_scope_only: int = 0
    fingerprint: str = field(default='', repr=False)
    status: str = 'AUTHOR_SELECTED_REFERENCE_RECHECK_NOT_RUN'
    publication_approved: bool = False


def build_reference_recheck_queue(
    store: EpisodeStore, project_id: str, *, through_episode: int,
    selected_paths: tuple[str, ...],
) -> ReferenceRecheckQueue:
    """선택 파일 바이트·저장 회차·QC 근거를 읽어 1~N화 전수 대기열 작성."""
    if (not isinstance(store, EpisodeStore) or type(project_id) is not str
            or not project_id or type(through_episode) is not int
            or not 1 <= through_episode <= 1000
            or type(selected_paths) is not tuple):
        raise ReferenceRecheckQueueError('기존 작품·1~1000화·직접 선택 참고작을 확인하세요.')
    try:
        lease = preview_reference_selection(selected_paths)
    except ReferenceLeaseError as exc:
        raise ReferenceRecheckQueueError(str(exc)) from exc
    if not 1 <= lease.count <= 100:
        raise ReferenceRecheckQueueError('참고작 1~100개를 직접 선택해야 합니다.')
    try:
        workflow = build_author_workflow_dependencies(
            store, project_id, through_episode=through_episode)
        coverage = summarize_reference_coverage(
            store, project_id, through_episode=through_episode)
        saved = {item.episode: item for item in store.list_episodes(project_id)}
        rows = []
        evidence = []
        for chapter, checked in zip(workflow.chapters, coverage.chapters):
            if chapter.episode != checked.episode:
                raise ReferenceRecheckQueueError('저장 회차와 검사 범위가 일치하지 않습니다.')
            if not chapter.final_present:
                action = 'FINAL_MANUSCRIPT_REQUIRED'
            elif checked.status == 'BLOCKED_OR_FAILED':
                action = 'REVIEW_FLAGGED_THEN_RESCAN'
            elif checked.status == 'CHECKED_SCOPE_ONLY' and checked.selected == lease.count:
                # 기존 기록은 선택 파일의 SHA와 연결되어 있지 않다.
                action = 'RECORDED_SCOPE_UNBOUND_RESCAN'
            else:
                action = 'SCAN_CURRENT_SELECTION'
            rows.append(ReferenceRecheckChapter(
                chapter.episode, chapter.revision, chapter.final_present,
                checked.status, checked.selected, checked.compared,
                checked.unexamined, chapter.review_status, action))
            ep = saved.get(chapter.episode)
            checks = tuple((item.content_revision, item.category, item.outcome,
                            item.note) for item in store.list_checks(project_id, chapter.episode))
            evidence.append((chapter.episode, chapter.revision,
                             chapter.manuscript_sha256,
                             sha256((ep.plot if ep else '').encode('utf-8')).hexdigest(),
                             sha256((ep.draft if ep else '').encode('utf-8')).hexdigest(),
                             chapter.review_status, checked.status,
                             checked.selected, checked.compared, checked.groups,
                             checked.unexamined, checked.direct_overlap_flagged,
                             sha256(repr(checks).encode('utf-8')).hexdigest()))
    except ReferenceRecheckQueueError:
        raise
    except (ValueError, OSError, LookupError, TypeError, AttributeError):
        raise ReferenceRecheckQueueError('현재 저장 원고·검수·참고작 범위를 읽지 못했습니다.') from None
    if len(rows) != through_episode:
        raise ReferenceRecheckQueueError('회차 전수 대기열이 누락됐습니다.')
    fingerprint = sha256(repr((project_id, through_episode, lease.fingerprint,
                               tuple(evidence))).encode('utf-8')).hexdigest()
    return ReferenceRecheckQueue(
        project_id, through_episode, lease.count, lease.file_types, tuple(rows),
        sum(not row.final_present for row in rows),
        sum(row.final_present for row in rows),
        sum(row.saved_scope_status == 'CHECKED_SCOPE_ONLY' for row in rows),
        fingerprint)


def require_current_reference_recheck_queue(
    snapshot: ReferenceRecheckQueue, store: EpisodeStore, project_id: str, *,
    through_episode: int, selected_paths: tuple[str, ...],
) -> None:
    """별도 GUI 이동 직전에 전체 원고·검수·선택 파일 지문을 다시 확인."""
    if type(snapshot) is not ReferenceRecheckQueue or snapshot.project_id != project_id:
        raise ReferenceRecheckQueueError('작품이 변경됐습니다. 재검사 대기열을 다시 조회하세요.')
    current = build_reference_recheck_queue(
        store, project_id, through_episode=through_episode,
        selected_paths=selected_paths)
    if current.fingerprint != snapshot.fingerprint:
        raise ReferenceRecheckQueueError('원고·QC·참고작 선택이 변경됐습니다. 다시 조회하세요.')
