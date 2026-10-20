"""Evidence-only cross-chapter exact sentence reuse screen.

This is a fast bounded local text comparison. It does not learn from user
data, update source episodes, send raw content, assess semantic originality,
or certify that the rest of a 30/100/250-chapter novel is literary-quality.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

_SPLIT = re.compile(r'(?<=[.!?。])\s+|\r?\n+')
_CLEAN = re.compile(r'[^가-힣0-9]+')
_MAX_CHARS = 100_000


@dataclass(frozen=True, slots=True)
class EpisodeReuseScreen:
    prior_episodes_examined: int
    exact_sentence_reuses: int
    affected_prior_episodes: int
    checked_scope_only: bool = True
    literary_approved: bool = False


def _sentences(text: str) -> set[str]:
    # Same normalized sentence can be present multiple times; inter-chapter
    # counts are DISTINCT repeated sentences, not duplicated word counts.
    return {
        clean
        for sentence in _SPLIT.split(text)
        if (clean := _CLEAN.sub('', sentence)).strip() and len(clean) >= 20
    }


def screen_cross_episode_reuse(
        draft: str, prior_drafts: tuple[str, ...],
) -> EpisodeReuseScreen:
    if (type(draft) is not str or not 1 <= len(draft) <= _MAX_CHARS
            or type(prior_drafts) is not tuple
            or len(prior_drafts) > 3
            or any(type(t) is not str or len(t) > _MAX_CHARS
                   for t in prior_drafts)):
        raise ValueError('invalid bounded cross-episode evidence')
    current = _sentences(draft)
    already: set[str] = set()
    affected = 0
    for previous in prior_drafts:
        old = _sentences(previous)
        overlap = current & old
        if overlap:
            affected += 1
            already.update(overlap)
    return EpisodeReuseScreen(
        prior_episodes_examined=len(prior_drafts),
        exact_sentence_reuses=len(already),
        affected_prior_episodes=affected,
    )
