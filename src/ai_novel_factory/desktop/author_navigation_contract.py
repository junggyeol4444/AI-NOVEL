"""기존 작가 편집기/회차 작업 GUI의 읽기 전용 이동 계약.

작가의 미저장 입력, 실행 중인 모델, 다른 작품/회차의 기록을 자동으로
버리거나 덮어쓰지 않는다. 저장·검수·출판 작업은 이 모듈에 없다.
"""
from __future__ import annotations

from dataclasses import dataclass

from ai_novel_factory.author_workflow_dependencies import (
    AuthorWorkflowDependenciesError, require_current_workflow_chapter,
)


@dataclass(frozen=True)
class NavigationDecision:
    allowed: bool
    message: str


def _busy(authoring) -> bool:
    """모델/배치 실행 중에는 회차 전환을 금지한다."""
    return bool(authoring.is_generating() or authoring.auto_panel.is_running())


def _unsaved(authoring) -> bool:
    session = authoring.session
    if session.pending_draft is not None:
        return True
    if session.episode_number is None:
        return False
    saved = session.episode()
    for key, value in (('plot', saved.plot), ('draft', saved.draft),
                       ('final_text', saved.final_text)):
        if authoring._text(key) != value:
            return True
    if session.scene_id is not None:
        if authoring._text('scene') != session.scene().text:
            return True
    return False


def check_author_navigation(authoring, *, project_identity,
                            episode: int, snapshot=None) -> NavigationDecision:
    """SQLite 최신 회차를 읽고 원고/승인 지문이 유효한 경우에만 허용."""
    session = authoring.session
    if (session.store is None or session.project_id is None or session.path is None
            or (str(session.path), str(session.project_id)) != tuple(project_identity)):
        return NavigationDecision(False, '작품이 변경됐습니다. 작업 목록을 다시 조회하세요.')
    if type(episode) is not int or not 1 <= episode <= 1000:
        return NavigationDecision(False, '저장된 1~1000화 중 한 회차를 선택하세요.')
    if _busy(authoring):
        return NavigationDecision(False, '실행 중인 집필·배치가 끝난 뒤 이동하세요.')
    try:
        if _unsaved(authoring):
            return NavigationDecision(False, '미저장 초고·플롯·장면·최종본을 먼저 직접 정리하세요.')
        current = session.store.get_episode(str(session.project_id), episode)
        if snapshot is not None:
            if snapshot.episode != episode:
                return NavigationDecision(False, '회차 선택이 변경됐습니다. 다시 조회하세요.')
            require_current_workflow_chapter(
                session.store, str(session.project_id), snapshot)
            if snapshot.revision != current.revision:
                return NavigationDecision(False, '원고 revision이 변경됐습니다. 다시 조회하세요.')
    except (AuthorWorkflowDependenciesError, ValueError, OSError, LookupError):
        return NavigationDecision(False, '원고·검수 기록이 변경됐습니다. 다시 조회하세요.')
    return NavigationDecision(True, '현재 저장 회차 확인 완료. 검수·출판 승인은 별도입니다.')


def select_saved_episode(authoring, *, project_identity, episode: int,
                         snapshot=None) -> NavigationDecision:
    """확인된 회차로만 이동. 새 회차/장면/승인/모델 실행은 하지 않는다."""
    decision = check_author_navigation(
        authoring, project_identity=project_identity,
        episode=episode, snapshot=snapshot)
    if not decision.allowed:
        return decision
    try:
        authoring.session.select_episode(episode)
        authoring._sync()
    except (ValueError, OSError, LookupError):
        return NavigationDecision(False, '회차 이동을 완료하지 못했습니다. 다시 조회하세요.')
    return NavigationDecision(True, f'{episode}화 기존 편집기로 이동했습니다. 자동 승인 없음.')


# 이미 존재하는 읽기 전용 화면의 회차/범위 입력만 채운다.
# 여기에서 refresh, QC, 저장, 참고작 전수 비교, 모델 실행을 호출하지 않는다.
_EPISODE_FIELDS = {
    'author_arc_context_panel': 'episode',
    'author_scene_context_panel': 'episode',
    'author_language_review_panel': 'episode',
    'author_context_composer_panel': 'episode',
    'author_fact_review_panel': 'through',
    'longform_revision_impact_panel': 'source',
    'final_reference_audit_panel': 'through',
    'epub_volume_panel': 'through',
    'author_workflow_dependencies_panel': 'through',
    'author_workflow_milestones_panel': 'through',
    'author_volume_review_matrix_panel': 'through',
    'author_editorial_readiness_panel': 'through',
    'author_recovery_matrix_panel': 'through',
    'author_continuity_coverage_panel': 'through',
    'author_manuscript_language_queue_panel': 'through',
    'author_scene_final_alignment_panel': 'through',
    'author_cross_chapter_repetition_panel': 'through',
}


def prefill_existing_feature(widget, attribute: str, episode: int) -> bool:
    """허용 목록에 있는 기존 QSpinBox의 회차 숫자만 설정한다."""
    field = _EPISODE_FIELDS.get(attribute)
    if field is None or type(episode) is not int or not 1 <= episode <= 1000:
        return False
    control = getattr(widget, field, None)
    if control is None or not callable(getattr(control, 'setValue', None)):
        return False
    if attribute == 'longform_revision_impact_panel':
        through = getattr(widget, 'through', None)
        if through is not None and through.value() < episode:
            through.setValue(episode)
    control.setValue(episode)
    return True
