"""Offline, deterministic Story Arc partitioning for stage 52 (no model calls)."""
from __future__ import annotations

from dataclasses import dataclass

from .planning import PlanningInput, PremiseDraft, PlanningError, draft_premise


@dataclass(frozen=True)
class StoryArc:
    number: int
    start_episode: int
    end_episode: int
    label: str
    objective: str


@dataclass(frozen=True)
class StoryArcPlan:
    episode_count: int
    arcs: tuple[StoryArc, ...]
    status: str = "DRAFT_REQUIRES_USER_APPROVAL"
    origin: str = "DETERMINISTIC_STRUCTURE_NOT_AI"


def plan_story_arcs(source: PlanningInput | PremiseDraft, arc_count: int | None = None) -> StoryArcPlan:
    """Partition all episodes into nonempty, contiguous arcs with no gaps.

    No reference text is read, and no story facts are invented or persisted.
    The user must review objectives and plot details in Novel Bible.
    """
    if isinstance(source, PlanningInput):
        episode_count = draft_premise(source).episode_count
    elif isinstance(source, PremiseDraft):
        episode_count = source.episode_count
        if type(episode_count) is not int or not 1 <= episode_count <= 10000:
            raise PlanningError("유효한 전체 회차 수가 필요합니다.")
    else:
        raise PlanningError("기획 입력 형식이 올바르지 않습니다.")
    if arc_count is None:
        arc_count = min(episode_count, max(1, (episode_count + 29) // 30))
    if type(arc_count) is not int or not 1 <= arc_count <= episode_count:
        raise PlanningError("Arc 수는 1 이상 전체 회차 수 이하여야 합니다.")
    base, extra = divmod(episode_count, arc_count)
    arcs = []
    start = 1
    for i in range(arc_count):
        end = start + base + (1 if i < extra else 0) - 1
        arcs.append(StoryArc(i + 1, start, end, f"ARC {i + 1}",
                             "Novel Bible에 근거하여 목표·갈등·전환점을 사용자 검토 후 확정"))
        start = end + 1
    return StoryArcPlan(episode_count, tuple(arcs))


def validate_arc_coverage(plan: StoryArcPlan) -> bool:
    """Reject missing, overlapping, out-of-order or malformed ranges."""
    if not isinstance(plan, StoryArcPlan) or type(plan.episode_count) is not int or plan.episode_count < 1:
        return False
    if not isinstance(plan.arcs, tuple) or not plan.arcs:
        return False
    next_episode = 1
    for number, arc in enumerate(plan.arcs, 1):
        if not isinstance(arc, StoryArc) or type(arc.number) is not int or arc.number != number:
            return False
        if type(arc.start_episode) is not int or type(arc.end_episode) is not int:
            return False
        if arc.start_episode != next_episode or arc.end_episode < arc.start_episode:
            return False
        next_episode = arc.end_episode + 1
    return next_episode == plan.episode_count + 1
