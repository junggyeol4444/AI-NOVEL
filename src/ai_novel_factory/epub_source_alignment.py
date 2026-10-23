"""Offline comparison of author-selected private EPUB3 volumes to saved finals.

This is an exact-content *scope* comparison, not EPUB Reader acceptance,
quality certification, human review, copyright clearance or publication.
No manuscript, reference, EPUB or SQLite bytes are modified or uploaded.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from .database.episodes import EpisodeStore
from .epub_reader import read_private_epub
from .epub_toc_authoring import load_current_epub_toc_manifest
from .epub_volume_workflow import plan_epub_volumes


class EpubSourceAlignmentError(ValueError):
    """Sanitized: no manuscript content, source path or author secrets."""


@dataclass(frozen=True)
class AlignedVolume:
    volume_index: int
    first_episode: int
    last_episode: int
    compared: int
    mismatched_text: tuple[int, ...]
    mismatched_title: tuple[int, ...]
    status: str


@dataclass(frozen=True)
class EpubSourceAlignment:
    project_id: str = field(repr=False)
    through_episode: int
    source_sha256: str = field(repr=False)
    volumes: tuple[AlignedVolume, ...]
    missing_final: tuple[int, ...]
    status: str = 'NOT_RUN'
    human_review_required: bool = True
    publication_approved: bool = False


def _fingerprint(path: Path) -> str:
    h = sha256()
    with path.open('rb') as handle:
        while True:
            part = handle.read(1024 * 1024)
            if not part:
                return h.hexdigest()
            h.update(part)


def compare_private_epub_to_saved_finals(
    store: EpisodeStore, project_id: str, *, through_episode: int,
    selected_volume_files: tuple[str, ...],
    toc_manifest_file: str | Path | None = None,
) -> EpubSourceAlignment:
    """Require every planned volume in order; never silently skip any chapter.

    Chapter text is compared strictly after the existing EPUB reader's parsing,
    so whitespace or formatting drift is reported rather than auto-accepted.
    """
    if not isinstance(store, EpisodeStore) or not project_id:
        raise EpubSourceAlignmentError('기존 작품을 먼저 열어야 합니다.')
    before = plan_epub_volumes(store, project_id, through_episode=through_episode)
    if before.missing_final or before.oversized_final:
        return EpubSourceAlignment(project_id, through_episode,
                                   before.source_sha256, (), before.missing_final,
                                   'BLOCKED_MISSING_OR_OVERSIZED_FINAL')
    if (type(selected_volume_files) is not tuple or
            len(selected_volume_files) != len(before.volumes)):
        raise EpubSourceAlignmentError('계획한 모든 EPUB 권을 순서대로 선택해야 합니다.')
    files = tuple(Path(p) for p in selected_volume_files)
    if (len(set(files)) != len(files) or
            any(not p.is_absolute() or p.is_symlink() or not p.is_file()
                or p.suffix.lower() != '.epub' for p in files)):
        raise EpubSourceAlignmentError('중복·링크 없는 기존 로컬 EPUB3 파일만 선택하세요.')
    if toc_manifest_file is None:
        titles = tuple(f'{n}화' for n in range(1, through_episode + 1))
    else:
        toc = load_current_epub_toc_manifest(
            toc_manifest_file, store, project_id, through_episode=through_episode)
        titles = toc.titles
    saved = {row.episode: row for row in store.list_episodes(project_id)}
    output = []
    for path, volume in zip(files, before.volumes):
        initial_file_sha = _fingerprint(path)
        try:
            chapters = read_private_epub(path)
        except (ValueError, OSError, KeyError):
            raise EpubSourceAlignmentError('선택한 EPUB3 권을 읽지 못했습니다.') from None
        if len(chapters) != volume.chapter_count:
            raise EpubSourceAlignmentError('권별 EPUB3 회차 개수가 현재 분할 계획과 다릅니다.')
        changed_text, changed_title = [], []
        for offset, chapter in enumerate(chapters):
            number = volume.first_episode + offset
            original = saved.get(number)
            if original is None or not original.final_text.strip():
                raise EpubSourceAlignmentError('검사 도중 저장 최종본이 누락됐습니다.')
            if chapter.text != original.final_text:
                changed_text.append(number)
            if chapter.title != titles[number - 1]:
                changed_title.append(number)
        if _fingerprint(path) != initial_file_sha:
            raise EpubSourceAlignmentError('비교 도중 EPUB3 원본이 변경됐습니다.')
        status = ('MISMATCH_REQUIRES_AUTHOR_REVIEW'
                  if changed_text or changed_title else 'EXACT_SAVED_TEXT_SCOPE_ONLY')
        output.append(AlignedVolume(volume.index, volume.first_episode,
                                    volume.last_episode, len(chapters),
                                    tuple(changed_text), tuple(changed_title), status))
    after = plan_epub_volumes(store, project_id, through_episode=through_episode)
    if after.source_sha256 != before.source_sha256:
        raise EpubSourceAlignmentError('비교 도중 저장 원고가 변경됐습니다.')
    status = ('MISMATCH_REQUIRES_AUTHOR_REVIEW'
              if any(row.mismatched_text or row.mismatched_title for row in output)
              else 'EXACT_SAVED_TEXT_SCOPE_ONLY_NOT_READER_VERIFIED')
    return EpubSourceAlignment(project_id, through_episode,
                               before.source_sha256, tuple(output), (), status)
