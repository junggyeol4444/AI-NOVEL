"""Offline, author-initiated multi-volume EPUB3 previews for the existing novel.

The existing EPUB generator limits one book to 250 chapters and 20 MiB of
chapter text. A 1000-episode work therefore needs explicit bounded volumes.
No model call, publication approval, upload, SQLite write or file overwrite.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .database.episodes import EpisodeStore
from .epub3 import (Chapter, EpubOutput, MAX_CHAPTERS,
                    MAX_CHAPTER_BYTES, MAX_TOTAL_CHAPTER_BYTES, create_epub)
from .epub_toc_authoring import load_current_epub_toc_manifest
from .publication_metadata import load_metadata


class EpubVolumeError(ValueError):
    """Sanitized: no manuscript text, private filename or model information."""


@dataclass(frozen=True)
class EpubVolume:
    index: int
    first_episode: int
    last_episode: int
    chapter_count: int
    chapter_bytes: int


@dataclass(frozen=True)
class EpubVolumePlan:
    project_id: str
    through_episode: int
    source_sha256: str
    volumes: tuple[EpubVolume, ...]
    missing_final: tuple[int, ...]
    oversized_final: tuple[int, ...]
    status: str = 'PRIVATE_VOLUMES_NOT_PUBLISHED'
    publication_approved: bool = False


@dataclass(frozen=True)
class EpubVolumeResult:
    output: EpubOutput
    volume: EpubVolume
    source_current_after_export: bool
    status: str = 'PRIVATE_PREVIEW_ONLY'
    publication_approved: bool = False


def plan_epub_volumes(store: EpisodeStore, project_id: str, *,
                      through_episode: int) -> EpubVolumePlan:
    """Inspect existing saved final revisions without skipping missing episodes.

    Both volume count and uncompressed text size are bounded by the existing
    generator's limits. A missing final blocks *all* volume creation, rather
    than silently producing a misleading incomplete longform export.
    """
    if not isinstance(store, EpisodeStore) or type(project_id) is not str or not project_id:
        raise EpubVolumeError('기존 작품을 먼저 선택해야 합니다.')
    if type(through_episode) is not int or not 1 <= through_episode <= 1000:
        raise EpubVolumeError('EPUB 전체 회차 범위는 1~1000화입니다.')
    store.get_project(project_id)
    saved = {row.episode: row for row in store.list_episodes(project_id)}
    digest = sha256()
    missing, oversized, volumes = [], [], []
    start, count, size = 1, 0, 0
    for number in range(1, through_episode + 1):
        row = saved.get(number)
        final = row.final_text if row is not None else ''
        data = final.encode('utf-8') if final.strip() else b''
        digest.update(f'{number}:{row.revision if row else 0}:'.encode('ascii'))
        digest.update(sha256(data).digest())
        if not data:
            missing.append(number)
        if len(data) > MAX_CHAPTER_BYTES:
            oversized.append(number)
        if count and (count >= MAX_CHAPTERS or
                      size + len(data) > MAX_TOTAL_CHAPTER_BYTES):
            volumes.append(EpubVolume(len(volumes) + 1, start, number - 1,
                                      count, size))
            start, count, size = number, 0, 0
        count += 1
        size += len(data)
    if count:
        volumes.append(EpubVolume(len(volumes) + 1, start,
                                  through_episode, count, size))
    return EpubVolumePlan(project_id, through_episode, digest.hexdigest(),
                          tuple(volumes), tuple(missing), tuple(oversized))


def create_private_epub_volume(
    store: EpisodeStore, project_id: str, *, through_episode: int,
    volume_index: int, expected_source_sha256: str,
    metadata_file: str | Path, output_directory: str | Path,
    cover_file: str | Path | None = None,
    toc_manifest_file: str | Path | None = None,
    explicit_private_preview: bool,
) -> EpubVolumeResult:
    """Write one new book.epub in a user-selected EXISTING per-volume folder.

    Each volume requires a separate author click and an empty destination for
    book.epub. The existing generator uses exclusive creation, never overwrite.
    The caller is responsible for choosing a different directory per volume.
    """
    if explicit_private_preview is not True:
        raise EpubVolumeError('이번 비공개 EPUB 권별 생성을 직접 승인해야 합니다.')
    before = plan_epub_volumes(store, project_id, through_episode=through_episode)
    if before.missing_final or before.oversized_final:
        raise EpubVolumeError('누락 또는 EPUB 크기 제한 초과 회차가 있어 생성하지 않았습니다.')
    if (type(expected_source_sha256) is not str or
            before.source_sha256 != expected_source_sha256):
        raise EpubVolumeError('저장 원고가 변경되어 이번 권별 생성 승인이 무효화됐습니다.')
    if type(volume_index) is not int or not 1 <= volume_index <= len(before.volumes):
        raise EpubVolumeError('생성할 EPUB 권 번호가 올바르지 않습니다.')
    volume = before.volumes[volume_index - 1]
    dest = Path(output_directory)
    if (not dest.is_absolute() or dest.is_symlink() or not dest.is_dir() or
            (dest / 'book.epub').exists() or (dest / 'book.epub').is_symlink()):
        raise EpubVolumeError('기존 비어 있는 권별 출력 폴더를 선택해야 합니다.')
    metadata = load_metadata(metadata_file)
    if metadata.project_id != project_id:
        raise EpubVolumeError('선택한 EPUB 메타데이터의 작품이 다릅니다.')
    if toc_manifest_file is not None:
        toc = load_current_epub_toc_manifest(
            toc_manifest_file, store, project_id, through_episode=through_episode)
        titles = toc.titles
    else:
        titles = tuple(f'{n}화' for n in range(1, through_episode + 1))
    chapters = []
    for number in range(volume.first_episode, volume.last_episode + 1):
        row = store.get_episode(project_id, number)
        if row is None or not row.final_text.strip():
            raise EpubVolumeError('생성 직전 최종 원고가 누락되었습니다.')
        chapters.append(Chapter(titles[number - 1], row.final_text))
    # No file is written unless every source revision remains unchanged.
    just_before = plan_epub_volumes(store, project_id,
                                    through_episode=through_episode)
    if just_before.source_sha256 != before.source_sha256:
        raise EpubVolumeError('EPUB 생성 직전 원고 변경이 확인되었습니다.')
    result = create_epub(metadata, tuple(chapters), dest, cover_path=cover_file)
    # Do not delete a newly created author-owned EPUB if the manuscript changed
    # during export; explicitly label that artifact as STALE instead.
    after = plan_epub_volumes(store, project_id, through_episode=through_episode)
    current = after.source_sha256 == before.source_sha256
    return EpubVolumeResult(result, volume, current,
                            'PRIVATE_PREVIEW_ONLY' if current
                            else 'STALE_SOURCE_AFTER_EXPORT_NOT_APPROVED')



@dataclass(frozen=True)
class PrivateEpubSeriesResult:
    """Only local files created with this user's explicit one-time approval."""
    volumes: tuple[EpubVolumeResult, ...]
    root: Path
    source_sha256: str
    source_current: bool
    status: str = 'PRIVATE_SERIES_PREVIEW_NOT_PUBLISHED'
    publication_approved: bool = False


def create_private_epub_series(
    store: EpisodeStore, project_id: str, *, through_episode: int,
    expected_source_sha256: str, metadata_file: str | Path,
    output_root: str | Path, cover_file: str | Path | None = None,
    toc_manifest_file: str | Path | None = None,
    explicit_private_series: bool,
) -> PrivateEpubSeriesResult:
    """Create every volume of one saved 1..N manuscript into NEW local dirs.

    One explicit user consent covers the entire planned series. The function
    never publishes, uploads, overwrites a file, creates an account or modifies
    SQLite. Preflight blocks incomplete/stale manuscripts and occupied child
    paths *before* writing volume 1. A mid-series failure stops immediately;
    previously created private EPUBs are preserved, never deleted.
    """
    if explicit_private_series is not True:
        raise EpubVolumeError('전체 권 비공개 EPUB 생성은 이번 실행에 별도 승인이 필요합니다.')
    plan = plan_epub_volumes(store, project_id,
                             through_episode=through_episode)
    if plan.missing_final or plan.oversized_final:
        raise EpubVolumeError('원고 최종본 누락 또는 권별 용량 초과가 있어 전체 권 생성을 중단합니다.')
    if (type(expected_source_sha256) is not str
            or expected_source_sha256 != plan.source_sha256):
        raise EpubVolumeError('원고 내용이 변경되어 전체 권 생성 승인이 무효입니다.')
    root = Path(output_root)
    if (not root.is_absolute() or root.is_symlink() or not root.is_dir()
            or str(root).startswith(('\\\\', '//'))):
        raise EpubVolumeError('기존의 로컬 전체 EPUB 출력 폴더가 필요합니다.')
    root = root.resolve(strict=True)
    volume_dirs = [
        root / f'anf-private-volume-{volume.index:03d}'
        for volume in plan.volumes]
    if any(path.exists() or path.is_symlink() for path in volume_dirs):
        raise EpubVolumeError('기존 권별 폴더와 이름이 충돌합니다. 다른 출력 폴더를 선택하세요.')
    # Validate shared inputs BEFORE volume 1, so later volumes do not
    # unexpectedly depend on a missing metadata/TOC file.
    metadata = load_metadata(metadata_file)
    if metadata.project_id != project_id:
        raise EpubVolumeError('EPUB 메타데이터가 다른 작품에 속합니다.')
    if toc_manifest_file is not None:
        load_current_epub_toc_manifest(
            toc_manifest_file, store, project_id, through_episode=through_episode)
    if cover_file is not None:
        cover = Path(cover_file)
        if not cover.is_file() or cover.is_symlink():
            raise EpubVolumeError('선택한 EPUB 표지 파일을 확인할 수 없습니다.')
    results: list[EpubVolumeResult] = []
    for planned, destination in zip(plan.volumes, volume_dirs):
        now = plan_epub_volumes(
            store, project_id, through_episode=through_episode)
        if now.source_sha256 != plan.source_sha256:
            raise EpubVolumeError(
                f'전체 EPUB 작업 중 저장 원고가 변경되었습니다. '
                f'이미 생성된 {len(results)}권은 비공개 파일로 보존합니다.')
        try:
            destination.mkdir(mode=0o700, parents=False, exist_ok=False)
        except OSError:
            raise EpubVolumeError(
                f'권별 새 폴더를 만들 수 없습니다. '
                f'이미 생성된 {len(results)}권은 비공개 파일로 보존합니다.') from None
        try:
            generated = create_private_epub_volume(
                store, project_id, through_episode=through_episode,
                volume_index=planned.index,
                expected_source_sha256=plan.source_sha256,
                metadata_file=metadata_file, output_directory=destination,
                cover_file=cover_file, toc_manifest_file=toc_manifest_file,
                explicit_private_preview=True)
        except (OSError, ValueError):
            # Never delete a generated author's EPUB, even when this specific
            # operation may have written a partial/complete file before error.
            raise EpubVolumeError(
                f'{planned.index}권 생성에 실패했습니다. '
                f'이전에 생성된 {len(results)}권과 기존 파일은 삭제하지 않았습니다.') from None
        results.append(generated)
        if not generated.source_current_after_export:
            raise EpubVolumeError(
                f'원고 변경으로 {planned.index}권 이후 생성을 중단했습니다. '
                '생성된 파일은 비공개이며 현재 원고 버전 인증이 아닙니다.')
    current = (plan_epub_volumes(
        store, project_id, through_episode=through_episode
    ).source_sha256 == plan.source_sha256)
    return PrivateEpubSeriesResult(
        tuple(results), root, plan.source_sha256, current,
        'PRIVATE_SERIES_PREVIEW_NOT_PUBLISHED' if current
        else 'STALE_SOURCE_AFTER_EXPORT_NOT_APPROVED')
