"""Stage 57: bounded, project-isolated offline retrieval of earlier episode summaries/manuscripts.

Explicit opt-in is required to expose manuscript text. No reference novel ingestion,
AI generation, remote service or publication action occurs here.
"""
from dataclasses import dataclass
from ai_novel_factory.database.episodes import EpisodeStore, EpisodeError

@dataclass(frozen=True)
class EpisodeHit:
    episode: int
    field: str
    excerpt: str
    revision: int


def search_episode_history(store: EpisodeStore, project_id: str, current_episode: int,
                           query: str, *, include_manuscript: bool = False,
                           limit: int = 10, excerpt_chars: int = 240) -> tuple[EpisodeHit, ...]:
    """Literal case-insensitive search, strictly before current_episode.

    Summary search is the default; manuscript search is explicitly enabled.
    Results are ordered newest episode first, then summary/draft/final.
    """
    if type(current_episode) is not int or current_episode < 1 or current_episode > 1_000_000:
        raise EpisodeError('검색 회차가 올바르지 않습니다.')
    if type(query) is not str or not query.strip() or len(query) > 200 or any(ord(c) < 32 for c in query):
        raise EpisodeError('검색어가 올바르지 않습니다.')
    if type(include_manuscript) is not bool or type(limit) is not int or not 1 <= limit <= 100:
        raise EpisodeError('검색 옵션이 올바르지 않습니다.')
    if type(excerpt_chars) is not int or not 20 <= excerpt_chars <= 2000:
        raise EpisodeError('검색 길이가 올바르지 않습니다.')
    needle = query.casefold()
    hits = []
    for episode in reversed(store.list_episodes(project_id)):
        if episode.episode >= current_episode:
            continue
        fields = [('summary', episode.summary)]
        if include_manuscript:
            fields.extend([('draft', episode.draft), ('final_text', episode.final_text)])
        for field, content in fields:
            pos = content.casefold().find(needle)
            if pos < 0:
                continue
            start = max(0, pos - excerpt_chars // 3)
            hits.append(EpisodeHit(episode.episode, field, content[start:start + excerpt_chars], episode.revision))
            if len(hits) == limit:
                return tuple(hits)
    return tuple(hits)
