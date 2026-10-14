"""Stage 60: offline, read-only integration of stages 51-58 planning components.

This constructs a *preview*, never a manuscript or an approved Novel Bible.
Stage 59's explicit manual SQLite editor remains the only path for plot writes.
"""
from __future__ import annotations

from dataclasses import dataclass

from .planning import PlanningInput, PremiseDraft, PlanningError, draft_premise
from .story_arcs import StoryArcPlan, plan_story_arcs, validate_arc_coverage
from .episode_planner import EpisodePlan, plan_episodes, validate_episode_plans
from .scene_planner import ScenePlan, plan_scenes, validate_scene_plans
from .episode_context import ContextFact, EpisodeContext, select_episode_context
from .pattern_application import PatternAppliedEpisode, apply_reference_patterns
from .references.element_selection import ElementSelection
from .database.pattern_usage import PatternUsageStore
from .database.episodes import EpisodeStore
from .episode_retrieval import EpisodeHit, search_episode_history
from .scene_vectors import SceneVector, SceneHit, search_scenes


@dataclass(frozen=True)
class PlanningPipelinePreview:
    project_id: str
    premise: PremiseDraft
    arcs: StoryArcPlan
    episode: EpisodePlan
    scenes: tuple[ScenePlan, ...]
    context: EpisodeContext
    pattern: PatternAppliedEpisode | None
    history: tuple[EpisodeHit, ...]
    similar_scenes: tuple[SceneHit, ...]
    status: str = 'DRAFT_REQUIRES_USER_APPROVAL'
    origin: str = 'OFFLINE_RULE_BASED_PREVIEW_NOT_AI'


def build_planning_preview(
    spec: PlanningInput,
    project_id: str,
    episode_number: int,
    facts: tuple[ContextFact, ...],
    *,
    arc_count: int | None = None,
    scene_count: int = 3,
    maximum_facts: int = 100,
    selection: ElementSelection | None = None,
    usage_store: PatternUsageStore | None = None,
    usage_id: str | None = None,
    pattern_project_authorized: bool = False,
    history_store: EpisodeStore | None = None,
    history_query: str | None = None,
    vectors: tuple[SceneVector, ...] | None = None,
    query_vector: tuple[float, ...] | None = None,
) -> PlanningPipelinePreview:
    """Assemble a bounded episode preview with explicit, opt-in history and patterns.

    Caller must authorize which project may use a reference pattern. Freshness is
    re-evaluated through the *real* PatternUsageStore.get() on each invocation.
    No source prose, manuscript text, or write operation enters this pipeline.
    A later human edit is explicitly saved through PlotEditorSession, not here.
    """
    if type(project_id) is not str or not project_id.strip() or len(project_id) > 128:
        raise PlanningError('작품 식별 정보가 올바르지 않습니다.')
    if type(episode_number) is not int or episode_number < 1:
        raise PlanningError('회차 번호가 올바르지 않습니다.')
    if (selection is None) != (usage_store is None) or (selection is None) != (usage_id is None):
        raise PlanningError('참고 통계 선택과 사용 기록을 함께 제공해야 합니다.')
    if selection is not None and pattern_project_authorized is not True:
        raise PlanningError('이 작품에 대한 참고 패턴 사용 권한 확인이 필요합니다.')
    if (history_store is None) != (history_query is None):
        raise PlanningError('과거 요약 검색 저장소와 검색어를 함께 제공해야 합니다.')
    if (vectors is None) != (query_vector is None):
        raise PlanningError('과거 장면 자료와 쿼리 벡터를 함께 제공해야 합니다.')
    if history_store is not None and not isinstance(history_store, EpisodeStore):
        raise PlanningError('지원하는 로컬 회차 저장소가 필요합니다.')

    premise = draft_premise(spec)
    if episode_number > premise.episode_count:
        raise PlanningError('계획된 전체 회차를 초과했습니다.')
    arcs = plan_story_arcs(premise, arc_count=arc_count)
    if not validate_arc_coverage(arcs):
        raise PlanningError('Story Arc 범위 검사에 실패했습니다.')
    episodes = plan_episodes(arcs)
    if not validate_episode_plans(arcs, episodes):
        raise PlanningError('회차 계획의 누락 또는 중복을 발견했습니다.')
    episode = episodes[episode_number - 1]
    scenes = plan_scenes(episode, scene_count)
    if not validate_scene_plans(episode, scenes):
        raise PlanningError('장면 구성 검사에 실패했습니다.')
    context = select_episode_context(project_id, episode, facts, maximum=maximum_facts)

    applied = None
    if selection is not None:
        if not isinstance(usage_store, PatternUsageStore) or type(usage_id) is not str:
            raise PlanningError('최신 참고 패턴 사용 기록 저장소가 필요합니다.')
        current_usage = usage_store.get(usage_id)
        applied = apply_reference_patterns(episode, context, selection, current_usage)

    history = (() if history_store is None else
               search_episode_history(history_store, project_id, episode_number,
                                      history_query, include_manuscript=False))
    similar = (() if vectors is None else
               search_scenes(project_id, episode_number, query_vector, vectors))
    return PlanningPipelinePreview(project_id, premise, arcs, episode, scenes,
                                   context, applied, history, similar)
