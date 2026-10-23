"""작가가 선택한 EPUB3 여러 권의 Reader↔검색·책갈피 이동 계약.

선택 권의 실제 파일 SHA256을 이동 직전에 다시 확인한다.
파일 내용·경로는 외부 전송하지 않으며 이 계약은 검수/출판 승인이 아니다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json

from .private_volume_reader import (
    PrivateVolumeCatalog, _digest_file, _selected_file,
)


class ReaderSelectionHandoffError(ValueError):
    """파일명·본문·원본 경로를 사용자 오류 문구에 노출하지 않는다."""


@dataclass(frozen=True)
class ReaderSelectionLease:
    project_identity: tuple[str, str] = field(repr=False)
    volume_index: int = 0
    chapter_index: int = 0
    volume_count: int = 0
    total_chapters: int = 0
    fingerprint: str = field(default='', repr=False)
    status: str = 'EPUB3_READER_SELECTION_ONLY_NOT_VERIFIED'
    publication_approved: bool = False


def _catalog_fingerprint(catalog: PrivateVolumeCatalog) -> str:
    if (type(catalog) is not PrivateVolumeCatalog
            or not 1 <= len(catalog.volumes) <= 16
            or not 1 <= catalog.total_chapters <= 1000):
        raise ReaderSelectionHandoffError('EPUB3 권을 다시 직접 선택하세요.')
    evidence = []
    offset = 0
    paths = set()
    for index, volume in enumerate(catalog.volumes, 1):
        if (volume.index != index or type(volume.chapters) is not int
                or not 1 <= volume.chapters <= 250
                or volume.first_display_episode != offset + 1
                or volume.last_display_episode != offset + volume.chapters
                or type(volume.file_sha256) is not str
                or len(volume.file_sha256) != 64):
            raise ReaderSelectionHandoffError('EPUB3 권 순서·회차 구성이 변경됐습니다.')
        try:
            path = _selected_file(volume.file_path)
            resolved = str(path.resolve(strict=True))
            if resolved in paths or _digest_file(path) != volume.file_sha256:
                raise ReaderSelectionHandoffError('EPUB3 원본이 변경됐습니다.')
        except (OSError, ValueError):
            raise ReaderSelectionHandoffError('EPUB3 원본을 다시 선택하세요.') from None
        paths.add(resolved)
        evidence.append((index, resolved, volume.file_sha256, volume.chapters,
                         volume.first_display_episode, volume.last_display_episode))
        offset += volume.chapters
    if offset != catalog.total_chapters:
        raise ReaderSelectionHandoffError('EPUB3 전체 회차 구성이 변경됐습니다.')
    return sha256(json.dumps(evidence, ensure_ascii=False, separators=(',', ':'))
                  .encode('utf-8')).hexdigest()


def preview_reader_selection(catalog: PrivateVolumeCatalog,
                             project_identity: tuple[str, str], *,
                             volume_index: int, chapter_index: int) -> ReaderSelectionLease:
    if (type(project_identity) is not tuple or len(project_identity) != 2
            or any(type(part) is not str or not part for part in project_identity)):
        raise ReaderSelectionHandoffError('현재 작품을 다시 열어 주세요.')
    if (type(volume_index) is not int or type(chapter_index) is not int
            or type(catalog) is not PrivateVolumeCatalog
            or not 1 <= volume_index <= len(catalog.volumes)
            or not 1 <= chapter_index <= catalog.volumes[volume_index - 1].chapters):
        raise ReaderSelectionHandoffError('인계할 권과 회차를 직접 선택하세요.')
    digest = _catalog_fingerprint(catalog)
    return ReaderSelectionLease(project_identity, volume_index, chapter_index,
                                len(catalog.volumes), catalog.total_chapters, digest)


def require_current_reader_selection(lease: ReaderSelectionLease,
                                     catalog: PrivateVolumeCatalog,
                                     project_identity: tuple[str, str]) -> None:
    if type(lease) is not ReaderSelectionLease or lease.project_identity != project_identity:
        raise ReaderSelectionHandoffError('작품 또는 인계 선택이 변경됐습니다.')
    current = preview_reader_selection(
        catalog, project_identity, volume_index=lease.volume_index,
        chapter_index=lease.chapter_index)
    if current != lease:
        raise ReaderSelectionHandoffError('EPUB3 파일·권 순서·회차가 변경됐습니다.')
