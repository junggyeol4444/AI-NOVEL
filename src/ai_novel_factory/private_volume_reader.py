"""User-selected multi-volume offline EPUB reading through the existing reader.

The order is supplied by the author; no filename guessing, crawling, online
lookup, automatic publication, quality certification or manuscript DB writes.
Reading a generated EPUB is not the later Windows10/11 reader acceptance test.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from .epub_reader import read_private_epub


class PrivateVolumeReaderError(ValueError):
    """Sanitized: never leak book text or user-selected paths."""


@dataclass(frozen=True)
class VolumeEntry:
    index: int
    first_display_episode: int
    last_display_episode: int
    chapters: int
    file_sha256: str
    file_path: Path = field(repr=False)


@dataclass(frozen=True)
class PrivateVolumeCatalog:
    volumes: tuple[VolumeEntry, ...]
    total_chapters: int
    status: str = 'PRIVATE_READING_ONLY_NOT_VERIFIED'
    publication_approved: bool = False


def _selected_file(value: str | Path) -> Path:
    path = Path(value)
    if (not path.is_absolute() or path.is_symlink() or not path.is_file()
            or path.suffix.lower() != '.epub'):
        raise PrivateVolumeReaderError('작가가 직접 선택한 로컬 EPUB3 파일이 필요합니다.')
    try:
        if not 1 <= path.stat().st_size <= 64 * 1024 * 1024:
            raise PrivateVolumeReaderError('EPUB3 파일 크기 제한을 초과했습니다.')
    except OSError:
        raise PrivateVolumeReaderError('EPUB3 파일 상태를 확인할 수 없습니다.') from None
    return path


def _digest_file(path: Path) -> str:
    digest = sha256()
    try:
        with path.open('rb') as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError:
        raise PrivateVolumeReaderError('선택한 EPUB3 파일을 읽을 수 없습니다.') from None
    return digest.hexdigest()


def build_private_volume_catalog(paths: tuple[str, ...]) -> PrivateVolumeCatalog:
    """Open each selected volume locally, keeping only chapter counts/hashes.

    The sequential numbers are UI positions, NOT asserted original chapter
    numbers. Author-selected volume order is never inferred or silently sorted.
    """
    if type(paths) is not tuple or not 1 <= len(paths) <= 16:
        raise PrivateVolumeReaderError('EPUB3 파일을 1~16권 직접 선택해야 합니다.')
    volumes = []
    seen = set()
    offset = 0
    for index, raw in enumerate(paths, 1):
        path = _selected_file(raw)
        digest = _digest_file(path)
        if digest in seen:
            raise PrivateVolumeReaderError('동일한 EPUB3 파일이 중복 선택되었습니다.')
        seen.add(digest)
        try:
            chapters = read_private_epub(path)
        except (OSError, ValueError, KeyError, TypeError):
            raise PrivateVolumeReaderError('선택한 EPUB3 권을 로컬 Reader로 읽지 못했습니다.') from None
        if not 1 <= len(chapters) <= 250 or offset + len(chapters) > 1000:
            raise PrivateVolumeReaderError('EPUB3 권별 회차 수 제한을 초과했습니다.')
        volumes.append(VolumeEntry(index, offset + 1, offset + len(chapters),
                                   len(chapters), digest, path))
        offset += len(chapters)
    return PrivateVolumeCatalog(tuple(volumes), offset)


def read_selected_volume_chapter(catalog: PrivateVolumeCatalog, *,
                                 volume_index: int, chapter_index: int,
                                 expected_file_sha256: str) -> tuple[str, str]:
    """Read one chapter in memory, rejecting changed books since selection."""
    if (type(catalog) is not PrivateVolumeCatalog or
            type(volume_index) is not int or
            not 1 <= volume_index <= len(catalog.volumes)):
        raise PrivateVolumeReaderError('열람할 EPUB3 권을 선택해야 합니다.')
    volume = catalog.volumes[volume_index - 1]
    if (type(chapter_index) is not int or
            not 1 <= chapter_index <= volume.chapters or
            expected_file_sha256 != volume.file_sha256 or
            _digest_file(_selected_file(volume.file_path)) != volume.file_sha256):
        raise PrivateVolumeReaderError('EPUB3 선택 또는 원본이 변경되어 다시 열어야 합니다.')
    try:
        chapters = read_private_epub(volume.file_path)
    except (OSError, ValueError, KeyError, TypeError):
        raise PrivateVolumeReaderError('현재 EPUB3 회차를 읽지 못했습니다.') from None
    if len(chapters) != volume.chapters or _digest_file(volume.file_path) != volume.file_sha256:
        raise PrivateVolumeReaderError('EPUB3 파일이 열람 중 변경되었습니다.')
    chapter = chapters[chapter_index - 1]
    return chapter.title, chapter.text
