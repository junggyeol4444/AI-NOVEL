"""Stage 54: editable, offline scene plans derived from validated episode plans."""
from __future__ import annotations

from dataclasses import dataclass

from .episode_planner import EpisodePlan
from .planning import PlanningError


@dataclass(frozen=True)
class ScenePlan:
    episode_number: int
    scene_number: int
    location: str
    characters: tuple[str, ...]
    goal: str
    conflict: str
    emotional_direction: str
    status: str = 'DRAFT_REQUIRES_USER_APPROVAL'
    origin: str = 'DETERMINISTIC_STRUCTURE_NOT_AI'


def plan_scenes(episode: EpisodePlan, scene_count: int = 3, *, maximum: int = 100) -> tuple[ScenePlan, ...]:
    """Create empty, reviewable scene slots without inventing facts or copying references."""
    if not isinstance(episode, EpisodePlan) or type(episode.episode_number) is not int or episode.episode_number < 1:
        raise PlanningError('올바른 회차 계획이 필요합니다.')
    if type(maximum) is not int or maximum < 1 or type(scene_count) is not int or not 1 <= scene_count <= maximum:
        raise PlanningError('장면 수는 허용 범위의 양의 정수여야 합니다.')
    return tuple(ScenePlan(episode.episode_number, i, '', (), '', '', '') for i in range(1, scene_count + 1))


def validate_scene_plans(episode: EpisodePlan, scenes: tuple[ScenePlan, ...], *, require_details: bool = False) -> bool:
    """Validate ordering, episode ownership, field types and optionally completed details."""
    if not isinstance(episode, EpisodePlan) or type(episode.episode_number) is not int or episode.episode_number < 1:
        return False
    if not isinstance(scenes, tuple) or not scenes:
        return False
    for i, scene in enumerate(scenes, 1):
        if not isinstance(scene, ScenePlan) or type(scene.episode_number) is not int or type(scene.scene_number) is not int:
            return False
        if scene.episode_number != episode.episode_number or scene.scene_number != i:
            return False
        if not isinstance(scene.characters, tuple) or any(not isinstance(c, str) for c in scene.characters):
            return False
        if any(not isinstance(v, str) for v in (scene.location, scene.goal, scene.conflict, scene.emotional_direction)):
            return False
        if require_details and (not scene.location.strip() or not scene.goal.strip() or not scene.conflict.strip() or not scene.characters):
            return False
    return True
