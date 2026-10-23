"""Read-only restart preview for the existing sequential chapter writer.

No model is launched, no chapter is replaced, and no user consent is reused.
"""
from __future__ import annotations
from dataclasses import dataclass
from .database.episodes import EpisodeStore


@dataclass(frozen=True)
class ResumePlan:
    project_id: str
    through_episode: int
    existing_episodes: tuple[int, ...]
    missing_episodes: tuple[int, ...]
    existing_without_draft: tuple[int, ...]
    existing_draft_only: tuple[int, ...]
    existing_final: tuple[int, ...]
    requires_new_model_approval: bool = True

    @property
    def next_missing(self) -> int | None:
        return self.missing_episodes[0] if self.missing_episodes else None


def preview_resume(store: EpisodeStore, project_id: str, *, through_episode: int) -> ResumePlan:
    if not isinstance(store, EpisodeStore):
        raise ValueError('기존 작품 저장소를 먼저 열어야 합니다.')
    if type(through_episode) is not int or not 1 <= through_episode <= 1000:
        raise ValueError('기존 자동 집필 지원 회차 범위는 1~1000화입니다.')
    records = {ep.episode: ep for ep in store.list_episodes(project_id)
               if ep.episode <= through_episode}
    existing = tuple(sorted(records))
    missing = tuple(i for i in range(1, through_episode + 1) if i not in records)
    no_draft = tuple(i for i, ep in sorted(records.items())
                     if not ep.draft.strip() and not ep.final_text.strip())
    draft_only = tuple(i for i, ep in sorted(records.items())
                       if ep.draft.strip() and not ep.final_text.strip())
    final = tuple(i for i, ep in sorted(records.items()) if ep.final_text.strip())
    return ResumePlan(project_id, through_episode, existing, missing,
                      no_draft, draft_only, final)
