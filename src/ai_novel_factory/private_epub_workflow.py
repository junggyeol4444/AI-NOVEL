"""Author-initiated offline EPUB3 preview from *saved* original final chapters.

No publication, remote upload, model execution, reference text import, or
automatic approval. The original SQLite DB is read only by this workflow.
This is a bridge to the existing EPUB3 generator and private reader, not a
replacement EPUB implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .database.episodes import EpisodeStore
from .epub3 import Chapter, EpubOutput, create_epub
from .epub_reader import read_private_epub
from .publication_metadata import load_metadata
from .manual_review_gate import review_state


class PrivateEpubWorkflowError(ValueError):
    """Never echo author text, private paths or metadata."""


@dataclass(frozen=True)
class PrivateEpubPlan:
    project_id: str
    through_episode: int
    chapters: int
    reviewed_current: int
    unreviewed: tuple[int, ...]
    missing_final: tuple[int, ...]
    source_sha256: str
    status: str = 'PRIVATE_PREVIEW_ONLY_NOT_APPROVED'
    publication_approved: bool = False


def plan_private_epub(store: EpisodeStore, project_id: str, *,
                      through_episode: int) -> PrivateEpubPlan:
    """Inspect real saved final manuscripts, without reading reference works.

    Missing chapters are reported, never skipped or replaced with invented text.
    Source digest ties the preview to the exact current saved finals.
    """
    if not isinstance(store, EpisodeStore) or type(project_id) is not str:
        raise PrivateEpubWorkflowError('현재 작품 저장소가 올바르지 않습니다.')
    if type(through_episode) is not int or not 1 <= through_episode <= 1000:
        raise PrivateEpubWorkflowError('EPUB 회차 범위가 올바르지 않습니다.')
    episodes = {e.episode: e for e in store.list_episodes(project_id)}
    digest = sha256()
    missing, unreviewed = [], []
    reviewed = 0
    for number in range(1, through_episode + 1):
        episode = episodes.get(number)
        if episode is None or not episode.final_text.strip():
            missing.append(number)
            continue
        digest.update(f'{number}:{episode.revision}:'.encode('ascii'))
        digest.update(sha256(episode.final_text.encode('utf-8')).digest())
        state = review_state(store, project_id, number)
        if state.status in ('REVIEWED_QC_RECORDED_NOT_PUBLISHED',
                            'REVIEWED_QC_INCOMPLETE'):
            reviewed += 1
        else:
            unreviewed.append(number)
    return PrivateEpubPlan(project_id, through_episode,
                           through_episode - len(missing), reviewed,
                           tuple(unreviewed), tuple(missing), digest.hexdigest())


def create_private_epub_from_saved_finals(
    store: EpisodeStore, project_id: str, *, through_episode: int,
    metadata_file: str | Path, output_directory: str | Path,
    cover_file: str | Path | None, expected_source_sha256: str,
    explicit_private_preview: bool,
) -> EpubOutput:
    """Create a local *unpublished* EPUB only after a new explicit user click.

    A preview is allowed for an author who has not finished reviewing, but its
    unreviewed chapters are never represented as reviewed or publishable.
    The existing EPUB3 generator creates a new file exclusively, no overwrite.
    """
    if explicit_private_preview is not True:
        raise PrivateEpubWorkflowError('비공개 미승인 미리보기 생성을 직접 선택해야 합니다.')
    before = plan_private_epub(store, project_id, through_episode=through_episode)
    if before.missing_final:
        raise PrivateEpubWorkflowError('최종 원고가 없는 회차가 있어 EPUB를 만들지 않았습니다.')
    if before.source_sha256 != expected_source_sha256:
        raise PrivateEpubWorkflowError('회차 원고가 변경되어 EPUB 생성 승인이 무효화됐습니다.')
    metadata = load_metadata(metadata_file)
    if metadata.project_id != project_id:
        raise PrivateEpubWorkflowError('다른 작품의 EPUB 메타데이터입니다.')
    chapters = tuple(
        Chapter(f'{number}화', store.get_episode(project_id, number).final_text)
        for number in range(1, through_episode + 1))
    # Re-read source revisions/digests after gathering text, before file write.
    after = plan_private_epub(store, project_id, through_episode=through_episode)
    if after.source_sha256 != before.source_sha256:
        raise PrivateEpubWorkflowError('EPUB 생성 중 원고가 변경됐습니다.')
    return create_epub(metadata, chapters, output_directory, cover_path=cover_file)


def read_private_epub_preview(file: str | Path) -> tuple[Chapter, ...]:
    """Delegate to the existing verified local EPUB3 reader, without writes."""
    return read_private_epub(file)
