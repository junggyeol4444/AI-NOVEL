"""작가가 직접 선택한 EPUB3 여러 권의 순차 열람 위치와 이동 계약.

기존 비공개 Reader의 파일/회차 검증을 재사용한다. 회차 번호는 표시용
순서일 뿐 원작의 공식 번호로 인증하지 않는다. 검색·원고·DB·출판
파일을 쓰지 않고 메모리에서만 현재 열람 위치를 보관한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256

from .private_volume_reader import (
    PrivateVolumeCatalog, PrivateVolumeReaderError,
    read_selected_volume_chapter,
)


class PrivateVolumeNavigationError(ValueError):
    """본문, 파일 경로를 포함하지 않는 로컬 열람 안내."""


@dataclass(frozen=True)
class PrivateReadingPosition:
    volume_index: int
    chapter_index: int
    display_episode: int
    total_chapters: int
    catalog_sha256: str = field(repr=False)
    file_sha256: str = field(repr=False)
    chapter_sha256: str = field(repr=False)
    persisted: bool = False
    publication_approved: bool = False


def _catalog_fingerprint(catalog: PrivateVolumeCatalog) -> str:
    if (type(catalog) is not PrivateVolumeCatalog
            or not 1 <= len(catalog.volumes) <= 16
            or type(catalog.total_chapters) is not int
            or not 1 <= catalog.total_chapters <= 1000):
        raise PrivateVolumeNavigationError('먼저 비공개 EPUB3 권을 직접 선택하세요.')
    offset = 0
    rows = []
    for index, entry in enumerate(catalog.volumes, 1):
        if (entry.index != index or type(entry.chapters) is not int
                or not 1 <= entry.chapters <= 250
                or entry.first_display_episode != offset + 1
                or entry.last_display_episode != offset + entry.chapters
                or type(entry.file_sha256) is not str
                or len(entry.file_sha256) != 64
                or any(c not in '0123456789abcdef' for c in entry.file_sha256)):
            raise PrivateVolumeNavigationError('현재 EPUB3 권별 목록이 변경되었습니다.')
        rows.append(f'{index}:{entry.chapters}:{entry.file_sha256}')
        offset += entry.chapters
    if offset != catalog.total_chapters:
        raise PrivateVolumeNavigationError('EPUB3 전체 회차 수가 변경되었습니다.')
    return sha256(('\n'.join(rows)).encode('ascii')).hexdigest()


def open_private_reading_position(
    catalog: PrivateVolumeCatalog, *, volume_index: int, chapter_index: int,
) -> tuple[PrivateReadingPosition, str, str]:
    """기존 EPUB3 원본 SHA를 확인해 정확한 권/회차의 텍스트를 열람한다."""
    fingerprint = _catalog_fingerprint(catalog)
    if (type(volume_index) is not int or type(chapter_index) is not int
            or not 1 <= volume_index <= len(catalog.volumes)):
        raise PrivateVolumeNavigationError('열람할 권과 회차를 다시 선택하세요.')
    entry = catalog.volumes[volume_index - 1]
    if not 1 <= chapter_index <= entry.chapters:
        raise PrivateVolumeNavigationError('해당 권에 선택한 회차가 없습니다.')
    try:
        title, prose = read_selected_volume_chapter(
            catalog, volume_index=volume_index, chapter_index=chapter_index,
            expected_file_sha256=entry.file_sha256)
    except (PrivateVolumeReaderError, OSError, ValueError, TypeError):
        raise PrivateVolumeNavigationError(
            'EPUB3 파일 또는 회차가 변경되어 다시 선택해야 합니다.') from None
    if not title.strip() or not prose.strip():
        raise PrivateVolumeNavigationError('EPUB3 본문이 비어 있습니다.')
    if _catalog_fingerprint(catalog) != fingerprint:
        raise PrivateVolumeNavigationError('열람 도중 EPUB3 권 목록이 변경되었습니다.')
    position = PrivateReadingPosition(
        volume_index, chapter_index,
        entry.first_display_episode + chapter_index - 1,
        catalog.total_chapters, fingerprint, entry.file_sha256,
        sha256(prose.encode('utf-8')).hexdigest())
    return position, title, prose


def require_current_reading_position(
    catalog: PrivateVolumeCatalog, position: PrivateReadingPosition,
) -> tuple[str, str]:
    """다음/이전 이동 전에 기존 선택·권·본문이 여전히 같은지 확인."""
    if type(position) is not PrivateReadingPosition:
        raise PrivateVolumeNavigationError('현재 EPUB3 열람 위치가 없습니다.')
    if (position.catalog_sha256 != _catalog_fingerprint(catalog)
            or position.total_chapters != catalog.total_chapters
            or not 1 <= position.volume_index <= len(catalog.volumes)):
        raise PrivateVolumeNavigationError('EPUB3 권 목록이 변경되어 다시 열어야 합니다.')
    entry = catalog.volumes[position.volume_index - 1]
    if (entry.file_sha256 != position.file_sha256
            or not 1 <= position.chapter_index <= entry.chapters
            or position.display_episode
               != entry.first_display_episode + position.chapter_index - 1):
        raise PrivateVolumeNavigationError('현재 EPUB3 열람 위치가 변경되었습니다.')
    current, title, prose = open_private_reading_position(
        catalog, volume_index=position.volume_index,
        chapter_index=position.chapter_index)
    if current.chapter_sha256 != position.chapter_sha256:
        raise PrivateVolumeNavigationError('현재 EPUB3 회차 원문이 변경되었습니다.')
    return title, prose


def jump_private_reading_position(
    catalog: PrivateVolumeCatalog, display_episode: int,
) -> tuple[PrivateReadingPosition, str, str]:
    """작가가 직접 입력한 전체 표시 회차로 이동; 권 순서 추측 없음."""
    _catalog_fingerprint(catalog)
    if (type(display_episode) is not int
            or not 1 <= display_episode <= catalog.total_chapters):
        raise PrivateVolumeNavigationError('1~전체 표시 회차 중 하나를 선택하세요.')
    for entry in catalog.volumes:
        if entry.first_display_episode <= display_episode <= entry.last_display_episode:
            return open_private_reading_position(
                catalog, volume_index=entry.index,
                chapter_index=display_episode - entry.first_display_episode + 1)
    raise PrivateVolumeNavigationError('선택한 표시 회차를 찾지 못했습니다.')


def move_private_reading_position(
    catalog: PrivateVolumeCatalog, position: PrivateReadingPosition, *,
    step: int,
) -> tuple[PrivateReadingPosition, str, str]:
    """정확히 한 회차씩 이동하며 권 경계에서는 다음/이전 권으로 이어 읽는다."""
    if type(step) is not int or step not in (-1, 1):
        raise PrivateVolumeNavigationError('이전 또는 다음 회차만 이동할 수 있습니다.')
    require_current_reading_position(catalog, position)
    target = position.display_episode + step
    if not 1 <= target <= catalog.total_chapters:
        raise PrivateVolumeNavigationError('첫 회차 또는 마지막 회차입니다.')
    return jump_private_reading_position(catalog, target)
