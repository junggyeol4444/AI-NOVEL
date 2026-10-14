"""Stage 58: apply *selected, approved aggregate statistics* as episode-plan annotations.

Reference patterns supply bounded numerical observations and fixed editorial review
questions only. They cannot replace Novel Bible facts, source text, or existing plot.
This function has no network, persistence, model, or publishing side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .episode_planner import EpisodePlan
from .episode_context import EpisodeContext, ContextFact
from .planning import PlanningError
from .references.element_selection import (
    ElementSelection, SelectedElement, FEATURE_KEYS, FEATURE_LABELS,
)
from .references.genre_patterns import GENRE_NAMES, _FEATURES
from .database.pattern_usage import PatternUsageRecord

# Fixed vocabulary only. Neither a numeric value nor a reference source is a
# directive to imitate any particular work's episode/story/voice.
_REVIEW_QUESTIONS = {
    "dialogue_ratio": ("scene_dialogue", "장면별 대사·서술 균형을 검토"),
    "sentence_characters": ("style", "문장 길이를 작품 고유 Style Bible과 대조"),
    "lexical_diversity": ("style", "반복 표현을 점검하되 고유 문체를 우선"),
    "emotion_balance": ("emotional_flow", "이번 회차 감정 흐름과 대비"),
    "cliffhanger_episode_rate": ("ending_hook", "회차 마지막 Hook의 필요성과 적합성 검토"),
    "event_cue_density_per_1000": ("required_events", "필수 사건의 배치·간격을 검토"),
}


@dataclass(frozen=True)
class PatternPlotNote:
    feature_key: str
    label: str
    observed_mean: float
    plan_field: str
    review_question: str


@dataclass(frozen=True)
class PatternAppliedEpisode:
    project_id: str
    episode: EpisodePlan
    canon_facts: tuple[ContextFact, ...]
    usage_id: str
    source_genre: str
    weighting: str
    notes: tuple[PatternPlotNote, ...]
    status: str = "DRAFT_REQUIRES_USER_APPROVAL"
    origin: str = "SELECTED_AGGREGATE_STATISTICS_NOT_AI"


def apply_reference_patterns(
    episode: EpisodePlan,
    context: EpisodeContext,
    selection: ElementSelection,
    usage: PatternUsageRecord,
) -> PatternAppliedEpisode:
    """Attach opt-in aggregate observations to a concrete episode for human editing.

    ``usage`` must be re-fetched from PatternUsageStore to check its ``current``
    status. Snapshot validity cannot be inferred from a saved ID alone. Cross-
    genre usage is not supported in this conservative first integration.
    """
    if (type(episode) is not EpisodePlan or type(episode.episode_number) is not int
            or episode.episode_number < 1 or type(episode.arc_number) is not int
            or episode.arc_number < 1 or episode.status != "DRAFT_REQUIRES_USER_APPROVAL"):
        raise PlanningError("사용자 검토 단계의 회차 계획이 필요합니다.")
    if (type(context) is not EpisodeContext or type(context.project_id) is not str
            or not context.project_id.strip() or context.episode_number != episode.episode_number
            or context.status != "DRAFT_REQUIRES_USER_APPROVAL"
            or type(context.facts) is not tuple):
        raise PlanningError("작품과 회차가 일치하는 설정 컨텍스트가 필요합니다.")
    for fact in context.facts:
        if (type(fact) is not ContextFact or fact.project_id != context.project_id
                or fact.source not in {"novel_bible", "character", "world", "relationship",
                                        "timeline", "foreshadowing", "style_bible", "episode_summary"}):
            raise PlanningError("설정 자료에 다른 작품이나 허용되지 않는 출처가 포함되었습니다.")
    if type(usage) is not PatternUsageRecord or usage.current is not True:
        raise PlanningError("승인된 최신 참고 패턴 사용 기록이 필요합니다.")
    if (type(usage.usage_id) is not str or len(usage.usage_id) != 32
            or any(c not in "0123456789abcdef" for c in usage.usage_id)
            or usage.source_genre not in GENRE_NAMES or usage.pattern_genre != usage.source_genre
            or usage.weighting not in {"equal", "characters"}):
        raise PlanningError("지원하지 않는 참고 패턴 사용 기록입니다.")
    if (type(selection) is not ElementSelection or selection.genre != usage.source_genre
            or selection.weighting != usage.weighting
            or type(selection.selected_keys) is not tuple
            or not 1 <= len(selection.selected_keys) <= len(FEATURE_KEYS)
            or len(set(selection.selected_keys)) != len(selection.selected_keys)
            or selection.selected_keys != tuple(k for k in FEATURE_KEYS if k in selection.selected_keys)
            or selection.selected_keys != usage.selected_keys
            or type(selection.reference_count) is not int
            or not 2 <= selection.reference_count <= 50
            or type(selection.max_share_percent) not in (int, float)
            or not isfinite(selection.max_share_percent)
            or not 0 <= selection.max_share_percent <= 60
            or type(selection.elements) is not tuple
            or len(selection.elements) != len(selection.selected_keys)):
        raise PlanningError("참고 통계 선택과 승인 기록이 일치하지 않습니다.")
    notes = []
    bounds = {key: (low, high) for key, _label, low, high in _FEATURES}
    for key, element in zip(selection.selected_keys, selection.elements):
        if type(element) is not SelectedElement or key not in bounds or element.key != key or element.label != FEATURE_LABELS[key]:
            raise PlanningError("선택된 참고 통계 항목이 유효하지 않습니다.")
        value = element.observed_mean
        if (type(value) not in (int, float) or not isfinite(value)
                or not bounds[key][0] <= value <= bounds[key][1]):
            raise PlanningError("참고 통계 관찰 값이 유효하지 않습니다.")
        field, question = _REVIEW_QUESTIONS[key]
        notes.append(PatternPlotNote(key, FEATURE_LABELS[key], float(value), field, question))
    # Output preserves all existing episode fields verbatim. Canon stays above
    # these notes and the user must decide whether any edit is appropriate.
    return PatternAppliedEpisode(context.project_id, episode, context.facts,
                                 usage.usage_id, usage.source_genre, usage.weighting,
                                 tuple(notes))
