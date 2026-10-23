"""기존 Windows 집필 GUI의 명시적 배치 범위 미리보기/인계 연결.

여기서는 QSpinBox 범위만 전달한다. AI 시작, 승인 체크, 참고작 본문
읽기, 원고 저장, 출판 승인, EPUB 생성은 호출하지 않는다.
"""
from __future__ import annotations

from ai_novel_factory.author_batch_scope_contract import (
    BatchScopeContractError, preview_existing_batch_scope,
    require_current_batch_scope,
)
from .author_navigation_contract import _busy, _unsaved
from ai_novel_factory.author_reference_selection_lease import (
    ReferenceLeaseError, preview_reference_selection,
    require_current_reference_selection,
)


class BatchScopeBridgeError(ValueError):
    """실제 파일 경로/원고 내용을 노출하지 않는 GUI 안내 오류."""


def _current_author_state(authoring):
    session = authoring.session
    if session.store is None or session.project_id is None or session.path is None:
        raise BatchScopeBridgeError('기존 작품을 먼저 열어 주세요.')
    if _busy(authoring):
        raise BatchScopeBridgeError('현재 모델·배치 집필이 끝난 뒤 범위를 선택하세요.')
    try:
        if _unsaved(authoring):
            raise BatchScopeBridgeError('미저장 초고·플롯·장면·최종본을 먼저 직접 정리하세요.')
    except (ValueError, OSError, LookupError):
        raise BatchScopeBridgeError('현재 편집 원고를 확인할 수 없습니다. 저장 상태를 다시 확인하세요.')
    return session, (str(session.path), str(session.project_id))


def preview_author_batch_scope(authoring, *, through_episode: int):
    """직접 클릭으로 기존 저장 회차와 선택 참고작의 형식별 개수만 조회."""
    session, identity = _current_author_state(authoring)
    batch = authoring.auto_panel
    try:
        reference_lease = preview_reference_selection(tuple(batch.reference_paths))
    except ReferenceLeaseError as exc:
        raise BatchScopeBridgeError(str(exc)) from exc
    snapshot = preview_existing_batch_scope(
        session.store, identity[1], through_episode=through_episode,
        target_chars=batch.target_chars.value(),
        scenes_per_episode=batch.scenes.value(),
        reference_paths=tuple(batch.reference_paths))
    return identity, snapshot, reference_lease


def handoff_author_batch_scope(authoring, *, project_identity, snapshot, reference_lease):
    """동일 작품·원고 지문이면 기존 배치 GUI 범위만 변경, 승인은 철회."""
    session, identity = _current_author_state(authoring)
    if identity != project_identity:
        raise BatchScopeBridgeError('작품이 변경됐습니다. 미리보기를 다시 실행하세요.')
    batch = authoring.auto_panel
    try:
        require_current_reference_selection(
            reference_lease, tuple(batch.reference_paths))
        require_current_batch_scope(
            snapshot, session.store, identity[1],
            through_episode=snapshot.through_episode,
            target_chars=batch.target_chars.value(),
            scenes_per_episode=batch.scenes.value(),
            reference_paths=tuple(batch.reference_paths))
    except (BatchScopeContractError, ReferenceLeaseError) as exc:
        raise BatchScopeBridgeError(str(exc)) from exc
    if snapshot.target_chars < 5000:
        raise BatchScopeBridgeError('회차당 5000자 미만 설정은 인계하지 않습니다. 기존 배치에서 직접 변경하세요.')
    if snapshot.unknown_reference_count:
        raise BatchScopeBridgeError('지원하지 않는 참고작 확장자가 포함되어 있습니다. 다시 선택하세요.')
    # 기존 실행 승인/lease는 절대로 인계하지 않는다.
    batch.consent.setChecked(False)
    batch.through.setValue(snapshot.through_episode)
    return (f'기존 배치 GUI의 마지막 회차를 {snapshot.through_episode}화로 입력했습니다. '
            '모델·참고작·품질·출판 승인은 이전되지 않았으며 실행도 시작하지 않았습니다.')
