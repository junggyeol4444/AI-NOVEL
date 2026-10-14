"""Stage 53: offline episode goal/event planning scaffolds, never automatic publication."""
from __future__ import annotations
from dataclasses import dataclass
from .story_arcs import StoryArcPlan, validate_arc_coverage
from .planning import PlanningError


@dataclass(frozen=True)
class EpisodePlan:
    episode_number: int
    arc_number: int
    goal: str
    required_events: tuple[str, ...]
    characters: tuple[str, ...]
    emotional_flow: str
    foreshadowing: tuple[str, ...]
    ending_hook: str
    status: str = 'DRAFT_REQUIRES_USER_APPROVAL'
    origin: str = 'DETERMINISTIC_STRUCTURE_NOT_AI'


def plan_episodes(arcs: StoryArcPlan, *, maximum: int = 10000) -> tuple[EpisodePlan, ...]:
    """Generate editable slots tied to the validated Arc coverage, without inventing story facts."""
    if not validate_arc_coverage(arcs):
        raise PlanningError('Story Arc 구간이 올바르지 않습니다.')
    if type(maximum) is not int or maximum < 1 or arcs.episode_count > maximum:
        raise PlanningError('회차 생성 상한을 초과했습니다.')
    result = []
    for arc in arcs.arcs:
        for number in range(arc.start_episode, arc.end_episode + 1):
            result.append(EpisodePlan(
                episode_number=number, arc_number=arc.number,
                goal='Novel Bible 및 해당 Arc 목표를 검토해 회차 목표 입력',
                required_events=(), characters=(), emotional_flow='',
                foreshadowing=(), ending_hook=''))
    return tuple(result)


def validate_episode_plans(arcs: StoryArcPlan, plans: tuple[EpisodePlan, ...]) -> bool:
    """Ensure exactly one correctly assigned plan for every episode."""
    if not validate_arc_coverage(arcs) or not isinstance(plans, tuple):
        return False
    if len(plans) != arcs.episode_count:
        return False
    expected_arc = (a.number for a in arcs.arcs for _ in range(a.start_episode, a.end_episode + 1))
    for number, (plan, arc_number) in enumerate(zip(plans, expected_arc), 1):
        if not isinstance(plan, EpisodePlan) or type(plan.episode_number) is not int or type(plan.arc_number) is not int:
            return False
        if plan.episode_number != number or plan.arc_number != arc_number:
            return False
    return True
