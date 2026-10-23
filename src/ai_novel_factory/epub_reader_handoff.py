"""기존 EPUB3 다권 원고 대조 → 로컬 Reader/회차 편집기의 수동 인계.

작가가 직접 선택한 파일과 현재 SQLite 최종본을 읽기 전용으로 비교한다.
미리보기는 출판 승인, 저작권 판정, 실제 Windows Reader 검증이 아니다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from .database.episodes import EpisodeStore
from .epub_source_alignment import (
    EpubSourceAlignment, EpubSourceAlignmentError,
    compare_private_epub_to_saved_finals,
)
from .private_volume_reader import (
    PrivateVolumeReaderError, build_private_volume_catalog,
)


class EpubReaderHandoffError(ValueError):
    """원고·책 제목·파일 경로를 노출하지 않는 인계 오류."""


@dataclass(frozen=True)
class EpubReaderHandoffLease:
    project_id: str = field(repr=False)
    through_episode: int
    source_sha256: str = field(repr=False)
    selected_files: tuple[str, ...] = field(repr=False)
    file_sha256: tuple[str, ...] = field(repr=False)
    toc_file: str = field(default='', repr=False)
    toc_sha256: str = field(default='', repr=False)
    mismatched_episodes: tuple[int, ...] = ()
    status: str = 'PRIVATE_READER_HANDOFF_NOT_VERIFIED'
    publication_approved: bool = False


def _toc_digest(value: str) -> str:
    if not value:
        return ''
    path = Path(value)
    if (not path.is_absolute() or path.is_symlink() or not path.is_file()
            or path.suffix.lower() != '.json' or path.stat().st_size > 2_000_000):
        raise EpubReaderHandoffError('기존 로컬 목차 JSON을 다시 선택하세요.')
    digest = sha256()
    with path.open('rb') as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                return digest.hexdigest()
            digest.update(block)


def preview_epub_reader_handoff(
    store: EpisodeStore, project_id: str, *, through_episode: int,
    selected_files: tuple[str, ...], toc_manifest_file: str = '',
) -> tuple[EpubSourceAlignment, EpubReaderHandoffLease]:
    """현재 원고와 모든 선택 권을 실제 읽어 대조하고 인계 지문만 보관."""
    if (not isinstance(store, EpisodeStore) or type(project_id) is not str
            or not project_id or type(selected_files) is not tuple
            or not selected_files or type(toc_manifest_file) is not str):
        raise EpubReaderHandoffError('현재 작품과 기존 EPUB3 전체 권을 선택하세요.')
    try:
        report = compare_private_epub_to_saved_finals(
            store, project_id, through_episode=through_episode,
            selected_volume_files=selected_files,
            toc_manifest_file=toc_manifest_file or None)
        if report.missing_final or not report.volumes:
            raise EpubReaderHandoffError('저장 최종본 누락으로 Reader 인계를 보류합니다.')
        catalog = build_private_volume_catalog(selected_files)
        if (catalog.total_chapters != through_episode
                or len(catalog.volumes) != len(report.volumes)
                or any(a.chapters != b.compared
                       for a, b in zip(catalog.volumes, report.volumes))):
            raise EpubReaderHandoffError('Reader 권별 회차와 현재 최종본 범위가 다릅니다.')
        toc_sha = _toc_digest(toc_manifest_file)
    except EpubReaderHandoffError:
        raise
    except (EpubSourceAlignmentError, PrivateVolumeReaderError,
            OSError, ValueError, TypeError):
        raise EpubReaderHandoffError('EPUB3·최종본·목차 전체를 대조하지 못했습니다.') from None
    mismatched = tuple(sorted({n for volume in report.volumes
                               for n in (*volume.mismatched_text,
                                         *volume.mismatched_title)}))
    lease = EpubReaderHandoffLease(
        project_id, through_episode, report.source_sha256, selected_files,
        tuple(volume.file_sha256 for volume in catalog.volumes),
        toc_manifest_file, toc_sha, mismatched,
        'MISMATCH_REQUIRES_AUTHOR_REVIEW' if mismatched
        else 'EXACT_TEXT_SCOPE_ONLY_READER_NOT_VERIFIED')
    return report, lease


def require_current_epub_reader_handoff(
    lease: EpubReaderHandoffLease, store: EpisodeStore, project_id: str,
) -> EpubSourceAlignment:
    """두 번째 클릭 시 SQLite·EPUB 전체·목차를 재검사해 변경된 인계를 거부."""
    if type(lease) is not EpubReaderHandoffLease or lease.project_id != project_id:
        raise EpubReaderHandoffError('작품이 변경됐습니다. 원고 대조를 다시 실행하세요.')
    report, latest = preview_epub_reader_handoff(
        store, project_id, through_episode=lease.through_episode,
        selected_files=lease.selected_files, toc_manifest_file=lease.toc_file)
    if (latest.source_sha256 != lease.source_sha256
            or latest.file_sha256 != lease.file_sha256
            or latest.toc_sha256 != lease.toc_sha256
            or latest.mismatched_episodes != lease.mismatched_episodes
            or latest.status != lease.status):
        raise EpubReaderHandoffError('원고·EPUB3·목차가 변경됐습니다. 다시 대조하세요.')
    return report
