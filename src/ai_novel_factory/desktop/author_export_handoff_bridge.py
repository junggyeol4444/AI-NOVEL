"""기존 Windows 집필 GUI에서 검수→비공개 EPUB3 화면으로 직접 인계.

미리보기와 화면 열기는 별도 클릭이다. 저장/생성/승인/출판을 호출하지 않는다.
"""
from __future__ import annotations

from ai_novel_factory.author_export_handoff_contract import (
    ExportHandoffError, preview_author_export_handoff,
    require_current_author_export_handoff,
)
from .author_batch_scope_bridge import _current_author_state


class ExportHandoffBridgeError(ValueError):
    """사용자 원고와 로컬 파일 경로를 포함하지 않는 안내 오류."""


_EXPORT_STAGE_TARGETS = frozenset((
    'review_worklist', 'final_reference_audit_panel',
    'publication_approval_panel', 'epub_volume_panel',
    'epub_source_alignment_panel', 'private_volume_reader_panel',
    'epub_private_bookmarks_panel', 'project_backup_panel',
    'scene_checkpoint_panel',
))


def preview_author_export_scope(authoring, *, through_episode: int):
    """작가 클릭으로 현재 SQLite 기록만 읽어 인계 지문 생성."""
    session, identity = _current_author_state(authoring)
    snapshot = preview_author_export_handoff(
        session.store, identity[1], through_episode=through_episode)
    return identity, snapshot


def open_author_export_stage(authoring, *, project_identity, snapshot, target: str):
    """지문 재확인 후 기존 허용 화면만 표시, 실제 동작은 별도 클릭."""
    if target not in _EXPORT_STAGE_TARGETS:
        raise ExportHandoffBridgeError('등록된 기존 검수·EPUB 도구를 선택하세요.')
    session, identity = _current_author_state(authoring)
    if identity != tuple(project_identity):
        raise ExportHandoffBridgeError('작품이 변경됐습니다. 미리보기를 다시 실행하세요.')
    try:
        require_current_author_export_handoff(snapshot, session.store, identity[1])
    except ExportHandoffError as exc:
        raise ExportHandoffBridgeError(str(exc)) from exc
    if target == 'epub_volume_panel' and (snapshot.missing_final or snapshot.oversized_final):
        raise ExportHandoffBridgeError(
            '누락·크기 초과 최종본이 있어 권별 생성 화면 인계를 보류합니다.')
    hub = getattr(authoring, 'feature_workspace_hub', None)
    if hub is None or not hub.open_feature(
            target, episode_number=snapshot.through_episode,
            project_identity=identity):
        raise ExportHandoffBridgeError('기존 기능 화면을 열지 못했습니다. 설치 상태를 확인하세요.')
    return (f'{snapshot.through_episode}화 범위의 기존 화면을 열었습니다. '
            'EPUB 생성·검수 기록·출판 승인은 실행하지 않았습니다.')
