"""Stage 55: conservative offline selection of user-provided canon and event facts.

Only explicit project-scoped records are eligible. Reference source text is never
accepted as context. A selection is a draft, not a truth inference or AI output.
"""
from __future__ import annotations
from dataclasses import dataclass
from .episode_planner import EpisodePlan
from .planning import PlanningError

_ALLOWED = frozenset({'novel_bible', 'character', 'world', 'relationship', 'timeline', 'foreshadowing', 'style_bible', 'episode_summary'})

@dataclass(frozen=True)
class ContextFact:
    project_id: str
    source: str
    fact_id: str
    text: str
    episode_start: int = 1
    episode_end: int | None = None
    character_ids: tuple[str, ...] = ()
    event_ids: tuple[str, ...] = ()

@dataclass(frozen=True)
class EpisodeContext:
    project_id: str
    episode_number: int
    facts: tuple[ContextFact, ...]
    status: str = 'DRAFT_REQUIRES_USER_APPROVAL'

def select_episode_context(project_id: str, episode: EpisodePlan, facts: tuple[ContextFact, ...], *, maximum: int = 100) -> EpisodeContext:
    """Prioritize Novel Bible; select only relevant, active, explicitly supplied facts.

    Shared project facts without tags remain eligible. Tagged facts require an
    exact match with the episode's characters or required events. The output
    does not claim that unselected facts are false or overridden.
    """
    if not isinstance(project_id, str) or not project_id.strip() or not isinstance(episode, EpisodePlan) or type(episode.episode_number) is not int or episode.episode_number < 1:
        raise PlanningError('작품 및 회차 식별 정보가 올바르지 않습니다.')
    if not isinstance(facts, tuple) or type(maximum) is not int or maximum < 1:
        raise PlanningError('설정 자료 형식 또는 최대 개수가 올바르지 않습니다.')
    selected = []
    seen = set()
    for fact in facts:
        if not isinstance(fact, ContextFact) or fact.project_id != project_id or fact.source not in _ALLOWED:
            raise PlanningError('작품 범위 또는 설정 출처가 올바르지 않습니다.')
        if (not isinstance(fact.fact_id, str) or not fact.fact_id.strip() or not isinstance(fact.text, str)
                or not fact.text.strip() or len(fact.text) > 4000 or type(fact.episode_start) is not int
                or fact.episode_start < 1 or (fact.episode_end is not None and (type(fact.episode_end) is not int or fact.episode_end < fact.episode_start))
                or not isinstance(fact.character_ids, tuple) or not isinstance(fact.event_ids, tuple)
                or any(not isinstance(v, str) or not v.strip() for v in fact.character_ids + fact.event_ids)):
            raise PlanningError('설정 기록의 형식이 올바르지 않습니다.')
        key = (fact.source, fact.fact_id)
        if key in seen:
            raise PlanningError('중복 설정 식별자가 있습니다.')
        seen.add(key)
        if not (fact.episode_start <= episode.episode_number and (fact.episode_end is None or episode.episode_number <= fact.episode_end)):
            continue
        if fact.character_ids or fact.event_ids:
            if not (set(fact.character_ids).intersection(episode.characters) or set(fact.event_ids).intersection(episode.required_events)):
                continue
        selected.append(fact)
    selected.sort(key=lambda f: (0 if f.source == 'novel_bible' else 1, f.source, f.fact_id))
    if len(selected) > maximum:
        raise PlanningError('설정 선택 상한을 초과했습니다. 자동 누락 없이 사용자 검토가 필요합니다.')
    return EpisodeContext(project_id, episode.episode_number, tuple(selected))
