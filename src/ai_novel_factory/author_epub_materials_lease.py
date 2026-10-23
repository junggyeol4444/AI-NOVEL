"""작가가 직접 선택한 EPUB3 자료와 현재 저장 원고의 읽기 전용 인계 계약."""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from .author_volume_review_matrix import build_volume_review_matrix
from .epub_toc_authoring import load_current_epub_toc_manifest
from .epub_volume_workflow import plan_epub_volumes
from .publication_metadata import load_metadata


class EpubMaterialsLeaseError(ValueError):
    """개인 원고·로컬 경로를 노출하지 않는 인계 오류."""


@dataclass(frozen=True)
class EpubMaterialsLease:
    project_id: str = field(repr=False)
    through_episode: int = 0
    metadata_file: str = field(default='', repr=False)
    toc_file: str = field(default='', repr=False)
    cover_file: str = field(default='', repr=False)
    source_sha256: str = field(default='', repr=False)
    fingerprint: str = field(default='', repr=False)
    volume_count: int = 0
    missing_final: int = 0
    oversized_final: int = 0
    qc_actions: int = 0
    human_review_actions: int = 0
    reference_actions: int = 0
    status: str = 'PRIVATE_MATERIALS_PREVIEW_ONLY'
    publication_approved: bool = False


def _digest(value: str, suffixes: tuple[str, ...], limit: int,
            required: bool) -> tuple[str, str]:
    if not value:
        if required:
            raise EpubMaterialsLeaseError('필수 EPUB 자료를 직접 선택하세요.')
        return '', ''
    path = Path(value)
    if (not path.is_absolute() or path.is_symlink() or not path.is_file()
            or path.suffix.lower() not in suffixes):
        raise EpubMaterialsLeaseError('기존 로컬 자료 파일을 다시 선택하세요.')
    try:
        if not 0 < path.stat().st_size <= limit:
            raise EpubMaterialsLeaseError('자료 파일 크기를 확인하세요.')
        data = path.read_bytes()
    except OSError:
        raise EpubMaterialsLeaseError('선택 자료를 읽을 수 없습니다.') from None
    if not 0 < len(data) <= limit:
        raise EpubMaterialsLeaseError('자료 파일 크기를 확인하세요.')
    if suffixes == ('.jpg', '.jpeg') and (
            len(data) < 4 or not data.startswith(b'\xff\xd8')
            or not data.endswith(b'\xff\xd9')):
        raise EpubMaterialsLeaseError('표지는 기존 JPEG 파일을 선택하세요.')
    return str(path), sha256(data).hexdigest()


def preview_epub_materials(store, project_id: str, *, through_episode: int,
                           metadata_file: str, toc_file: str = '',
                           cover_file: str = '') -> EpubMaterialsLease:
    """저장 원고·권별 검수·메타데이터·목차·표지 파일 지문을 함께 확인."""
    if (type(project_id) is not str or not project_id
            or type(through_episode) is not int
            or not 1 <= through_episode <= 1000):
        raise EpubMaterialsLeaseError('현재 작품과 1~1000화 범위를 선택하세요.')
    try:
        volume = plan_epub_volumes(store, project_id,
                                   through_episode=through_episode)
        review = build_volume_review_matrix(store, project_id,
                                             through_episode=through_episode)
        metadata_path, metadata_hash = _digest(
            metadata_file, ('.json',), 16384, True)
        if load_metadata(metadata_path).project_id != project_id:
            raise EpubMaterialsLeaseError('메타데이터 작품이 다릅니다.')
        toc_path, toc_hash = _digest(
            toc_file, ('.json',), 256 * 1024, False)
        if toc_path:
            load_current_epub_toc_manifest(
                toc_path, store, project_id, through_episode=through_episode)
        cover_path, cover_hash = _digest(
            cover_file, ('.jpg', '.jpeg'), 20 * 1024 * 1024, False)
    except (ValueError, OSError, LookupError, TypeError):
        raise EpubMaterialsLeaseError(
            '현재 원고·검수·메타데이터·목차·표지를 확인하지 못했습니다.') from None
    fingerprint = sha256(repr((
        project_id, through_episode, volume.source_sha256,
        volume.missing_final, volume.oversized_final,
        review.fingerprint, metadata_hash, toc_hash, cover_hash,
    )).encode('utf-8')).hexdigest()
    return EpubMaterialsLease(
        project_id, through_episode, metadata_path, toc_path, cover_path,
        volume.source_sha256, fingerprint, len(volume.volumes),
        len(volume.missing_final), len(volume.oversized_final),
        sum(row.qc_action_count for row in review.rows),
        sum(row.human_review_action_count for row in review.rows),
        sum(row.reference_action_count for row in review.rows))


def require_current_epub_materials(snapshot: EpubMaterialsLease,
                                   store, project_id: str) -> None:
    """두 번째 클릭에서 원고·검수·파일 SHA 변경 시 이전 선택 무효화."""
    if type(snapshot) is not EpubMaterialsLease or snapshot.project_id != project_id:
        raise EpubMaterialsLeaseError('현재 작품이 변경됐습니다.')
    current = preview_epub_materials(
        store, project_id, through_episode=snapshot.through_episode,
        metadata_file=snapshot.metadata_file, toc_file=snapshot.toc_file,
        cover_file=snapshot.cover_file)
    if current != snapshot:
        raise EpubMaterialsLeaseError('원고·검수·EPUB 자료가 변경됐습니다.')
