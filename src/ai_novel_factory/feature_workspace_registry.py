"""Static, allowlisted GUI feature catalogue for existing authoring project.

Every entry points to a module in the existing AI-NOVEL Python package.
Importing this catalogue never imports/executes optional feature modules.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureEntry:
    group: str
    caption: str
    module: str
    class_name: str
    instance_attribute: str


FEATURE_ENTRIES: tuple[FeatureEntry, ...] = (
    FeatureEntry('작가 검수', '회차별 검수 대기', 'review_worklist_widget', 'ReviewWorklistWidget', 'review_worklist'),
    FeatureEntry('작가 검수', '전체 QC 검수 현황', 'review_dashboard_panel', 'ReviewDashboardPanel', 'review_dashboard_panel'),
    FeatureEntry('작가 검수', '편집 문제 직접 기록', 'editorial_issue_panel', 'EditorialIssuePanel', 'editorial_issue_panel'),
    FeatureEntry('작가 검수', '원고 인계 보류 목록', 'editorial_handoff_panel', 'EditorialHandoffPanel', 'editorial_handoff_panel'),
    FeatureEntry('작가 검수', '직접 수정·초고 재작성', 'manual_rewrite_panel', 'ManualRewritePanel', 'manual_rewrite_panel'),
    FeatureEntry('작가 검수', '수동 출판 승인·철회', 'publication_approval_panel', 'PublicationApprovalPanel', 'publication_approval_panel'),
    FeatureEntry('장편 연속성', '회차별 근거 JSON', 'evidence_review_panel', 'EvidenceReviewPanel', 'evidence_review_panel'),
    FeatureEntry('장편 연속성', '인물·복선·시간선 기록', 'author_fact_panel', 'AuthorFactPanel', 'author_fact_panel'),
    FeatureEntry('장편 연속성', '작가 저장 사실 문맥', 'author_fact_context_panel', 'AuthorFactContextPanel', 'author_fact_context_panel'),
    FeatureEntry('장편 연속성', '회차별 사실·QC 검토표', 'author_fact_review_panel', 'AuthorFactReviewPanel', 'author_fact_review_panel'),
    FeatureEntry('장편 연속성', '수정 후속 회차 영향', 'longform_revision_impact_panel', 'LongformRevisionImpactPanel', 'longform_revision_impact_panel'),
    FeatureEntry('참고작', '참고작 전수 등록·통계', 'reference_intake_panel', 'ReferenceIntakePanel', 'reference_intake_panel'),
    FeatureEntry('참고작', '회차별 참고작 비교 범위', 'reference_coverage_panel', 'ReferenceCoveragePanel', 'reference_coverage_panel'),
    FeatureEntry('참고작', '최종본 참고작 전수 검사', 'final_reference_audit_panel', 'FinalReferenceAuditPanel', 'final_reference_audit_panel'),
    FeatureEntry('장편 집필', '실행 전 범위 확인', 'batch_preflight_panel', 'BatchPreflightPanel', 'batch_preflight_panel'),
    FeatureEntry('장편 집필', 'GGUF/실행 파일 별도 승인', 'local_model_integrity_panel', 'LocalModelIntegrityPanel', 'local_model_integrity_panel'),
    FeatureEntry('장편 집필', '중단 후 회차 재개', 'resume_preview_widget', 'ResumePreviewWidget', 'resume_preview'),
    FeatureEntry('장편 집필', '실행 기록 및 재개 현황', 'batch_recovery_panel', 'BatchRecoveryPanel', 'batch_recovery_panel'),
    FeatureEntry('장편 집필', '장면별 임시 초고', 'scene_checkpoint_panel', 'SceneCheckpointPanel', 'scene_checkpoint_panel'),
    FeatureEntry('작품·SQLite', '기존 SQLite 재열기', 'sqlite_reopen_panel', 'SqliteReopenPanel', 'sqlite_reopen_panel'),
    FeatureEntry('작품·SQLite', 'SQLite 로컬 백업', 'project_backup_panel', 'ProjectBackupPanel', 'project_backup_panel'),
    FeatureEntry('작품·SQLite', 'SQLite 새 복원 사본', 'project_restore_panel', 'ProjectRestorePanel', 'project_restore_panel'),
    FeatureEntry('비공개 출력', 'EPUB3 1권 생성', 'private_epub_panel', 'PrivateEpubPanel', 'private_epub_panel'),
    FeatureEntry('비공개 출력', 'EPUB3 다권 분할 생성', 'epub_volume_panel', 'EpubVolumePanel', 'epub_volume_panel'),
    FeatureEntry('비공개 출력', 'EPUB3 회차별 목차 편집', 'epub_toc_panel', 'EpubTocPanel', 'epub_toc_panel'),
    FeatureEntry('비공개 출력', 'EPUB3 단권 읽기', 'private_epub_reader_panel', 'PrivateEpubReaderPanel', 'private_epub_reader_panel'),
    FeatureEntry('비공개 출력', 'EPUB3 여러 권 이어읽기', 'private_volume_reader_panel', 'PrivateVolumeReaderPanel', 'private_volume_reader_panel'),
    FeatureEntry('비공개 출력', 'EPUB3 원고 대조', 'epub_source_alignment_panel', 'EpubSourceAlignmentPanel', 'epub_source_alignment_panel'),
    FeatureEntry('비공개 출력', 'TXT·MD 비공개 교정본', 'local_manuscript_proof_panel', 'LocalManuscriptProofPanel', 'local_manuscript_proof_panel'),
    FeatureEntry('비공개 출력', '출판 상태 스냅샷', 'release_snapshot_panel', 'ReleaseSnapshotPanel', 'release_snapshot_panel'),
)


def get_feature_entry(instance_attribute: str) -> FeatureEntry:
    """Only allow a registered, non-user-controlled module/class name."""
    for entry in FEATURE_ENTRIES:
        if entry.instance_attribute == instance_attribute:
            return entry
    raise KeyError('unregistered feature')
