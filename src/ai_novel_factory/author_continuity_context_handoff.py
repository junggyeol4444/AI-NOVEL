"""기존 장편 5종 기록의 집필 문맥으로의 읽기 전용 인계 계약.

현재 저장 원고·작가 기록·문맥 길이와 선택 회차를 함께 확인한다.
미리보기/인계는 AI 실행, 검수 합격, 원고 저장, 출판 승인이 아니다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .author_continuity_coverage import (
    ContinuityCoverageSnapshot, ContinuityCoverageError,
    require_current_continuity_coverage,
)
from .author_context_envelope import (
    AuthorContextSources, AuthorContextEnvelopeError,
    capture_author_context_sources, compose_author_context,
    require_unchanged_author_sources,
)
from .database.episodes import EpisodeStore


class ContinuityContextHandoffError(ValueError):
    """개인 원고·폴더·본문을 오류 메시지에 포함하지 않는다."""


@dataclass(frozen=True)
class ContinuityContextLease:
    project_id: str
    episode: int
    scene_count: int
    coverage: ContinuityCoverageSnapshot = field(repr=False)
    sources: AuthorContextSources = field(repr=False)
    content_sha256: str
    outline_chars: int
    scene_chars: int
    model_execution_approved: bool = False
    publication_approved: bool = False


def _prepare(store: EpisodeStore, project_id: str,
             coverage: ContinuityCoverageSnapshot, episode: int,
             scene_count: int):
    if (not isinstance(store, EpisodeStore) or not isinstance(coverage, ContinuityCoverageSnapshot)
            or type(project_id) is not str or project_id != coverage.project_id
            or type(episode) is not int or not 1 <= episode <= coverage.through_episode
            or type(scene_count) is not int or not 1 <= scene_count <= 20):
        raise ContinuityContextHandoffError('현재 작품·회차·장면 수를 다시 직접 확인하세요.')
    try:
        require_current_continuity_coverage(coverage, store, project_id)
        row = coverage.rows[episode - 1]
        # A saved chapter may be used as evidence, but a missing/changed
        # selected author record is never silently synthesized or omitted.
        if row.revision is None or row.stale_sources or row.missing_sources:
            raise ContinuityContextHandoffError(
                '선택한 회차의 저장 최종본·5종 기록 또는 근거가 누락·변경됐습니다.')
        folders = coverage.folders
        sources = capture_author_context_sources(
            store, project_id, arc_folder=folders[0], scene_folder=folders[1],
            fact_folder=folders[2], language_folder=folders[3],
            memory_folder=folders[4])
        envelope = compose_author_context(
            store, project_id, episode=episode, scene_count=scene_count,
            sources=sources)
        require_current_continuity_coverage(coverage, store, project_id)
        require_unchanged_author_sources(store, project_id, sources)
        return sources, envelope
    except ContinuityContextHandoffError:
        raise
    except (ContinuityCoverageError, AuthorContextEnvelopeError,
            ValueError, OSError, LookupError):
        raise ContinuityContextHandoffError(
            '저장 원고·5종 작가 기록·집필 문맥을 확인하지 못했습니다. 다시 직접 조회하세요.') from None


def preview_continuity_context(store: EpisodeStore, project_id: str, *,
                               coverage: ContinuityCoverageSnapshot,
                               episode: int, scene_count: int) -> ContinuityContextLease:
    """모든 직접 선택 기록으로 문맥을 조합하지만 원문·승인을 저장하지 않는다."""
    sources, envelope = _prepare(store, project_id, coverage, episode, scene_count)
    return ContinuityContextLease(
        project_id, episode, scene_count, coverage, sources,
        envelope.content_sha256, len(envelope.outline),
        sum(len(scene) for scene in envelope.scenes))


def require_current_continuity_context(lease: ContinuityContextLease,
                                       store: EpisodeStore, project_id: str) -> None:
    """두 번째 클릭과 이후 모델 동의 이전에 원고·기록·문맥 지문 재확인."""
    if not isinstance(lease, ContinuityContextLease) or lease.project_id != project_id:
        raise ContinuityContextHandoffError('작품 또는 선택 범위가 변경됐습니다.')
    sources, envelope = _prepare(
        store, project_id, lease.coverage, lease.episode, lease.scene_count)
    if (sources != lease.sources or envelope.content_sha256 != lease.content_sha256
            or len(envelope.outline) != lease.outline_chars
            or sum(len(scene) for scene in envelope.scenes) != lease.scene_chars):
        raise ContinuityContextHandoffError(
            '선택한 원고·작가 기록·문맥이 변경되어 이전 인계가 무효화됐습니다.')