"""저장 최종본/작가 검수/참고작 범위/EPUB3 분할의 읽기 전용 인계 계약.

모든 상태는 기존 SQLite의 현재 기록과 EPUB3 분할 계획에서만 조회한다.
EPUB 생성·검수 합격·저작권 승인·출판·원고 변경은 수행하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256

from .author_workflow_dependencies import build_author_workflow_dependencies
from .epub_volume_workflow import plan_epub_volumes


class ExportHandoffError(ValueError):
    """원고/참고작 경로 및 본문을 표시하지 않는 인계 오류."""


@dataclass(frozen=True)
class AuthorExportHandoff:
    project_id: str = field(repr=False)
    through_episode: int = 0
    stored_episodes: int = 0
    missing_final: int = 0
    oversized_final: int = 0
    review_action_count: int = 0
    reference_action_count: int = 0
    volume_ranges: tuple[tuple[int, int, int], ...] = ()
    fingerprint: str = field(default='', repr=False)
    status: str = 'AUTHOR_EXPORT_PREVIEW_ONLY_NOT_APPROVED'
    publication_approved: bool = False


def preview_author_export_handoff(store, project_id: str, *,
                                  through_episode: int) -> AuthorExportHandoff:
    """EPUB 원본 범위와 현재 회차별 작가 작업 지문을 한 번에 묶는다."""
    if (type(project_id) is not str or not project_id or
            type(through_episode) is not int or not 1 <= through_episode <= 1000):
        raise ExportHandoffError('현재 작품과 1~1000화 범위를 다시 선택하세요.')
    try:
        workflow = build_author_workflow_dependencies(
            store, project_id, through_episode=through_episode)
        epub = plan_epub_volumes(
            store, project_id, through_episode=through_episode)
    except (OSError, ValueError, LookupError):
        raise ExportHandoffError('저장 원고·검수·EPUB 분할 기록을 읽지 못했습니다.') from None
    rows = tuple((row.episode, row.revision, row.manuscript_sha256,
                  row.review_status, row.reference_status, row.remaining_actions)
                 for row in workflow.chapters)
    volumes = tuple((v.index, v.first_episode, v.last_episode) for v in epub.volumes)
    digest = sha256(repr((project_id, through_episode, epub.source_sha256,
                          epub.missing_final, epub.oversized_final,
                          volumes, rows)).encode('utf-8')).hexdigest()
    return AuthorExportHandoff(
        project_id=project_id, through_episode=through_episode,
        stored_episodes=through_episode - workflow.missing_episodes,
        missing_final=len(epub.missing_final),
        oversized_final=len(epub.oversized_final),
        review_action_count=workflow.review_action_count,
        reference_action_count=workflow.reference_action_count,
        volume_ranges=volumes, fingerprint=digest)


def require_current_author_export_handoff(snapshot: AuthorExportHandoff,
                                          store, project_id: str) -> None:
    """화면 인계 직전에 원고·검수·EPUB 범위가 바뀌지 않았는지 재확인."""
    if type(snapshot) is not AuthorExportHandoff or snapshot.project_id != project_id:
        raise ExportHandoffError('작품이 변경됐습니다. 다시 조회하세요.')
    latest = preview_author_export_handoff(
        store, project_id, through_episode=snapshot.through_episode)
    if latest.fingerprint != snapshot.fingerprint:
        raise ExportHandoffError('원고·검수·참고작 범위 또는 EPUB 계획이 변경됐습니다.')
