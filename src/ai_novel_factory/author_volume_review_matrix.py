"""작가가 직접 조회하는 장편 권별 원고·QC·참고작·EPUB3 인계 현황.

기존 저장 회차와 권별 분할 계획을 읽기 전용으로 결합한다.
결과는 검사 합격, 저작권 판단, 출판 승인, 실제 EPUB 생성 결과가 아니다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256

from .author_workflow_dependencies import build_author_workflow_dependencies
from .epub_volume_workflow import plan_epub_volumes


class VolumeReviewMatrixError(ValueError):
    """개인 원고와 파일 경로를 노출하지 않는 조회 오류."""


@dataclass(frozen=True)
class VolumeReviewRow:
    volume: int
    first_episode: int
    last_episode: int
    saved_final: int
    missing_final: int
    qc_action_count: int
    human_review_action_count: int
    reference_action_count: int
    oversized_final: int
    next_action: str = 'AUTHOR_REVIEW_REQUIRED'


@dataclass(frozen=True)
class VolumeReviewMatrix:
    project_id: str = field(repr=False)
    through_episode: int = 0
    rows: tuple[VolumeReviewRow, ...] = ()
    fingerprint: str = field(default='', repr=False)
    status: str = 'AUTHOR_PREVIEW_ONLY_NOT_APPROVED'
    publication_approved: bool = False


def build_volume_review_matrix(store, project_id: str, *,
                               through_episode: int) -> VolumeReviewMatrix:
    """기존 1~1000화 전 범위를 누락 없이 권별로 집계한다."""
    if (type(project_id) is not str or not project_id or
            type(through_episode) is not int or not 1 <= through_episode <= 1000):
        raise VolumeReviewMatrixError('기존 작품과 1~1000화 범위를 선택하세요.')
    try:
        workflow = build_author_workflow_dependencies(
            store, project_id, through_episode=through_episode)
        plan = plan_epub_volumes(store, project_id, through_episode=through_episode)
    except (ValueError, OSError, LookupError):
        raise VolumeReviewMatrixError('저장 원고·검수·권별 계획을 조회하지 못했습니다.') from None
    chapters = {item.episode: item for item in workflow.chapters}
    missing = set(plan.missing_final)
    oversized = set(plan.oversized_final)
    rows = []
    for volume in plan.volumes:
        members = tuple(chapters[n] for n in range(
            volume.first_episode, volume.last_episode + 1))
        count_missing = sum(n in missing for n in range(
            volume.first_episode, volume.last_episode + 1))
        count_large = sum(n in oversized for n in range(
            volume.first_episode, volume.last_episode + 1))
        qc = sum('COMPLETE_OR_REFRESH_QC' in c.remaining_actions for c in members)
        human = sum('CONFIRM_HUMAN_REVIEW' in c.remaining_actions for c in members)
        references = sum('REVIEW_REFERENCES' in c.remaining_actions for c in members)
        if count_missing or count_large:
            next_action = 'MANUSCRIPT_OR_SIZE_BLOCKED'
        elif qc or human or references:
            next_action = 'REVIEW_EVIDENCE_REQUIRED'
        else:
            next_action = 'PRIVATE_EPUB_PLAN_ONLY'
        rows.append(VolumeReviewRow(
            volume.index, volume.first_episode, volume.last_episode,
            len(members) - count_missing, count_missing, qc, human,
            references, count_large, next_action))
    evidence = tuple((c.episode, c.revision, c.manuscript_sha256,
                      c.review_status, c.reference_status, c.remaining_actions)
                     for c in workflow.chapters)
    fingerprint = sha256(repr((project_id, through_episode,
        plan.source_sha256, tuple((v.index, v.first_episode, v.last_episode)
        for v in plan.volumes), evidence)).encode('utf-8')).hexdigest()
    return VolumeReviewMatrix(project_id, through_episode, tuple(rows), fingerprint)


def require_current_volume_review_matrix(snapshot: VolumeReviewMatrix,
                                         store, project_id: str) -> None:
    """다른 화면을 열기 전에 현재 저장 원고·검수·권별 계획을 다시 읽는다."""
    if (type(snapshot) is not VolumeReviewMatrix or
            type(project_id) is not str or snapshot.project_id != project_id):
        raise VolumeReviewMatrixError('작품이 변경됐습니다. 다시 조회하세요.')
    latest = build_volume_review_matrix(
        store, project_id, through_episode=snapshot.through_episode)
    if latest.fingerprint != snapshot.fingerprint or latest.rows != snapshot.rows:
        raise VolumeReviewMatrixError('원고·검수·참고작 기록 또는 EPUB3 권별 계획이 변경됐습니다.')
