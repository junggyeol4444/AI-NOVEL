"""Read-only 30/100/250-episode author-context coverage planning.

No model call, DB mutation, QC PASS, saving, or manuscript publication.
Each requested episode is classified conservatively; no artificial successes.
"""
from __future__ import annotations

from dataclasses import dataclass
from .database.episodes import EpisodeStore
from .author_context_envelope import (AuthorContextSources,
                                      AuthorContextEnvelopeError,
                                      compose_author_context,
                                      require_unchanged_author_sources)


@dataclass(frozen=True)
class ScopeEpisode:
    episode: int
    status: str  # EXISTING / CONTEXT_READY / CONTEXT_BLOCKED
    saved_revision: int | None
    note: str = ''


@dataclass(frozen=True)
class ContextScopePlan:
    total: int
    existing: int
    ready: int
    blocked: int
    episodes: tuple[ScopeEpisode, ...]
    quality_certified: bool = False
    publication_approved: bool = False


def plan_author_context_scope(store: EpisodeStore, project_id: str, *,
                              through_episode: int, scenes_per_episode: int,
                              sources: AuthorContextSources) -> ContextScopePlan:
    if (not isinstance(store, EpisodeStore) or type(through_episode) is not int
            or not 1 <= through_episode <= 1000 or
            type(scenes_per_episode) is not int or not 1 <= scenes_per_episode <= 20):
        raise AuthorContextEnvelopeError('작가 문맥 계획의 회차·장면 수가 올바르지 않습니다.')
    require_unchanged_author_sources(store, project_id, sources)
    existing = {record.episode: record.revision for record in
                store.list_episodes(project_id)}
    rows: list[ScopeEpisode] = []
    for number in range(1, through_episode + 1):
        # A saved episode cannot be silently overwritten by the current batch.
        if number in existing:
            rows.append(ScopeEpisode(number, 'EXISTING', existing[number],
                                     '저장된 회차 · 자동 덮어쓰기 금지'))
            continue
        try:
            compose_author_context(store, project_id, episode=number,
                                   scene_count=scenes_per_episode, sources=sources)
        except (ValueError, OSError):
            rows.append(ScopeEpisode(number, 'CONTEXT_BLOCKED', None,
                                     '작가 문맥 누락·변경·충돌·한도 확인 필요'))
        else:
            rows.append(ScopeEpisode(number, 'CONTEXT_READY', None,
                                     '문맥 준비만 확인 · 모델 실행/품질 검증 아님'))
    require_unchanged_author_sources(store, project_id, sources)
    return ContextScopePlan(
        through_episode,
        sum(row.status == 'EXISTING' for row in rows),
        sum(row.status == 'CONTEXT_READY' for row in rows),
        sum(row.status == 'CONTEXT_BLOCKED' for row in rows),
        tuple(rows))
