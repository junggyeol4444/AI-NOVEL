"""Stage 31: combine saved, text-free Reference Profiles fully offline.

This is a descriptive analysis of several legally held reference works, never
text generation or copying. All results contain aggregate numbers and fixed
vocabulary labels only; no titles, quotations, names, original words or paths.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import sqrt
import re

from .plaintext_parser import ReferenceParseError
from .reference_profile import (
    ALLOWED_HOOK_TYPES, PROFILE_SCHEMA_VERSION, ReferenceProfile, validate_profile,
)

MAX_COLLECTION_REFERENCES = 50
CURVE_BINS = 5
WEIGHTING_MODES = frozenset({"equal", "characters"})
_ID = re.compile(r"[0-9a-f]{32}\Z")


@dataclass(frozen=True)
class MetricSpread:
    minimum: float
    maximum: float
    weighted_mean: float
    standard_deviation: float  # population standard deviation of work-level metrics


@dataclass(frozen=True)
class CurveSegment:
    segment: int  # 1..5, relative position of the episode in its work
    contributing_works: int
    contributing_episodes: int
    dialogue_ratio: float
    emotion_balance: float
    event_cue_density_per_1000: float


@dataclass(frozen=True)
class ProfileCollection:
    schema_version: int
    reference_count: int
    weighting: str
    empty_character_fallback: bool
    episode_count: int
    total_characters: int
    total_words: int
    total_event_cue_candidates: int
    total_hook_candidate_episodes: int
    event_cue_density_per_1000: float  # pooled cues / pooled characters
    dialogue_ratio: MetricSpread
    sentence_characters: MetricSpread
    lexical_diversity: MetricSpread
    emotion_balance: MetricSpread
    cliffhanger_episode_rate: MetricSpread
    hook_type_counts: tuple[tuple[str, int], ...]
    episode_curve: tuple[CurveSegment, ...]


def _check_inputs(profiles: list[ReferenceProfile] | tuple[ReferenceProfile, ...],
                  weighting: str) -> tuple[ReferenceProfile, ...]:
    if type(profiles) not in (list, tuple) or not 2 <= len(profiles) <= MAX_COLLECTION_REFERENCES:
        raise ReferenceParseError("통합 분석에는 2~50개의 참고작 프로필이 필요합니다.")
    if type(weighting) is not str or weighting not in WEIGHTING_MODES:
        raise ReferenceParseError("허용되지 않은 참고작 통합 가중치입니다.")
    for item in profiles:
        validate_profile(item)  # fail closed on corrupt or untrusted metrics
        if item.schema_version != PROFILE_SCHEMA_VERSION:
            raise ReferenceParseError("지원하지 않는 참고작 프로필 버전입니다.")
    return tuple(profiles)


def _weights(profiles: tuple[ReferenceProfile, ...], mode: str) -> tuple[tuple[float, ...], bool]:
    if mode == "equal":
        return (1.0,) * len(profiles), False
    result = tuple(float(profile.total_characters) for profile in profiles)
    if not any(result):
        return (1.0,) * len(profiles), True
    return result, False


def _weighted_mean(values: tuple[float, ...], weights: tuple[float, ...]) -> float:
    denominator = sum(weights)
    return sum(a * b for a, b in zip(values, weights)) / denominator if denominator else 0.0


def _spread(values: tuple[float, ...], weights: tuple[float, ...]) -> MetricSpread:
    mean = _weighted_mean(values, weights)
    variance = _weighted_mean(tuple((v - mean) ** 2 for v in values), weights)
    return MetricSpread(
        minimum=round(min(values), 6),
        maximum=round(max(values), 6),
        weighted_mean=round(mean, 6),
        standard_deviation=round(sqrt(variance), 6),
    )


def _curve(profiles: tuple[ReferenceProfile, ...], weights: tuple[float, ...]) -> tuple[CurveSegment, ...]:
    # First calculate each work's per-bin episode averages, then average across
    # works. A 100-episode book therefore does not cast 100 votes against a
    # 10-episode book when equal-work weighting is requested.
    per_bin: list[list[tuple[float, float, float, float, int]]] = [[] for _ in range(CURVE_BINS)]
    for work, work_weight in zip(profiles, weights):
        buckets: list[list] = [[] for _ in range(CURVE_BINS)]
        for idx, episode in enumerate(work.episodes):
            position = min(CURVE_BINS - 1, ((2 * idx + 1) * CURVE_BINS) // (2 * len(work.episodes)))
            buckets[position].append(episode)
        for idx, bucket in enumerate(buckets):
            if not bucket:
                continue
            local_weights = tuple(float(e.characters) for e in bucket)
            if not any(local_weights):
                local_weights = (1.0,) * len(bucket)
            per_bin[idx].append((
                work_weight,
                _weighted_mean(tuple(float(e.dialogue_ratio) for e in bucket), local_weights),
                _weighted_mean(tuple(float(e.emotion_balance) for e in bucket), local_weights),
                # Pooled candidate density within this relative-position bin.
                1000.0 * sum(e.event_cue_candidates for e in bucket) / sum(e.characters for e in bucket)
                if sum(e.characters for e in bucket) else 0.0,
                len(bucket),
            ))
    result: list[CurveSegment] = []
    for idx, values in enumerate(per_bin):
        # For a zero-character work with nonempty episodes, equal-work mode
        # still contributes; characters mode gives it zero weight.
        w = tuple(item[0] for item in values)
        result.append(CurveSegment(
            segment=idx + 1,
            contributing_works=len(values),
            contributing_episodes=sum(item[4] for item in values),
            dialogue_ratio=round(_weighted_mean(tuple(item[1] for item in values), w), 6),
            emotion_balance=round(_weighted_mean(tuple(item[2] for item in values), w), 6),
            event_cue_density_per_1000=round(_weighted_mean(tuple(item[3] for item in values), w), 6),
        ))
    return tuple(result)


def combine_reference_profiles(
    profiles: list[ReferenceProfile] | tuple[ReferenceProfile, ...],
    *, weighting: str = "equal",
) -> ProfileCollection:
    """Summarize 2..50 existing profiles without reading source novels.

    ``equal`` gives every *work* the same vote; ``characters`` weights work-level
    averages by non-whitespace character counts. Pooled density uses total
    counts / total characters in both modes. Type diversity is a mean of each
    book's value, NOT lexical diversity of a merged corpus. No AI inference.
    """
    data = _check_inputs(profiles, weighting)
    weights, fallback = _weights(data, weighting)
    total_chars = sum(p.total_characters for p in data)
    total_candidates = sum(p.event_cue_candidates for p in data)
    hook_counts = Counter(e.cliffhanger_type for p in data for e in p.episodes)
    result = ProfileCollection(
        schema_version=1,
        reference_count=len(data),
        weighting=weighting,
        empty_character_fallback=fallback,
        episode_count=sum(p.episode_count for p in data),
        total_characters=total_chars,
        total_words=sum(p.total_words for p in data),
        total_event_cue_candidates=total_candidates,
        total_hook_candidate_episodes=sum(p.cliffhanger_candidate_episodes for p in data),
        event_cue_density_per_1000=round(1000 * total_candidates / total_chars, 6)
        if total_chars else 0.0,
        dialogue_ratio=_spread(tuple(float(p.dialogue_ratio) for p in data), weights),
        sentence_characters=_spread(tuple(float(p.average_sentence_characters) for p in data), weights),
        lexical_diversity=_spread(tuple(float(p.lexical_diversity) for p in data), weights),
        emotion_balance=_spread(tuple(float(p.emotion_balance) for p in data), weights),
        cliffhanger_episode_rate=_spread(tuple(p.cliffhanger_candidate_episodes / p.episode_count
                                                for p in data), weights),
        hook_type_counts=tuple((kind, hook_counts[kind]) for kind in sorted(ALLOWED_HOOK_TYPES)),
        episode_curve=_curve(data, weights),
    )
    return result


def combine_saved_profiles(store: object, reference_ids: list[str] | tuple[str, ...],
                           *, weighting: str = "equal") -> ProfileCollection:
    """Fetch explicit IDs from a local SQLite profile store, then aggregate.

    No network and no persistence of the combined result. IDs must be unique;
    profile text/title/path is never included in the returned aggregate.
    """
    from ai_novel_factory.database.reference_profiles import ReferenceProfileStore

    if not isinstance(store, ReferenceProfileStore):
        raise ReferenceParseError("로컬 참고작 프로필 저장소가 필요합니다.")
    if (type(reference_ids) not in (list, tuple)
            or not 2 <= len(reference_ids) <= MAX_COLLECTION_REFERENCES
            or any(type(item) is not str or _ID.fullmatch(item) is None for item in reference_ids)
            or len(set(reference_ids)) != len(reference_ids)):
        raise ReferenceParseError("서로 다른 참고작 프로필 ID를 2~50개 선택하세요.")
    if type(weighting) is not str or weighting not in WEIGHTING_MODES:
        raise ReferenceParseError("허용되지 않은 참고작 통합 가중치입니다.")
    # Load before processing; missing/corrupt profiles cause an error, never
    # silently change the population and bias the resulting statistics.
    return combine_reference_profiles(tuple(store.get(item) for item in reference_ids), weighting=weighting)


def render_profile_collection(collection: ProfileCollection) -> str:
    """Printable Korean report using strictly fixed labels + numeric metrics."""
    if type(collection) is not ProfileCollection:
        raise ReferenceParseError("통합 참고작 프로필이 올바르지 않습니다.")
    mode = "작품별 동일 가중치" if collection.weighting == "equal" else "작품 글자 수 가중치"
    if collection.empty_character_fallback:
        mode += " (전체 본문 0자이므로 동일 가중치 적용)"
    lines = [
        "여러 참고작 통합 Reference Profile (통계 참고 지표, 원문 비저장)",
        f"참고작: {collection.reference_count}개 | 회차 합계: {collection.episode_count}개 | {mode}",
        f"본문 글자 합계: {collection.total_characters:,} | 공백 단어 합계: {collection.total_words:,}",
        f"사건 단서: {collection.total_event_cue_candidates:,}개 | 1,000자당 {collection.event_cue_density_per_1000:.2f}",
        f"말미 후보 회차 합계: {collection.total_hook_candidate_episodes:,}",
        "구분 | 가중 평균 | 최소 | 최대 | 작품 간 표준편차",
    ]
    for label, spread in (
        ("대사 비율", collection.dialogue_ratio),
        ("문장 평균 길이", collection.sentence_characters),
        ("작품별 어휘 다양도", collection.lexical_diversity),
        ("감정 어휘 균형", collection.emotion_balance),
        ("말미 후보 회차 비율", collection.cliffhanger_episode_rate),
    ):
        lines.append(f"{label} | {spread.weighted_mean:.4f} | {spread.minimum:.4f} | "
                     f"{spread.maximum:.4f} | {spread.standard_deviation:.4f}")
    lines.append("--- 전체 말미 후보 유형 (회차별 분류) ---")
    lines.append(" | ".join(f"{name}: {count}" for name, count in collection.hook_type_counts))
    lines.append("--- 회차 상대 위치별 5구간 곡선 ---")
    for segment in collection.episode_curve:
        lines.append(f"{segment.segment}/5구간 | 기여 작품 {segment.contributing_works}개"
                     f" | 회차 {segment.contributing_episodes}개"
                     f" | 대사 {segment.dialogue_ratio:.1%}"
                     f" | 감정 균형 {segment.emotion_balance:+.3f}"
                     f" | 단서 밀도 {segment.event_cue_density_per_1000:.2f}")
    lines.append("주의: 원문을 결합한 결과가 아니며, 동일 문체 생성이나 서사 사건의 의미 분석 결과가 아닙니다.")
    lines.append("주의: 어휘 다양도는 개별 작품 수치의 평균이며 여러 작품을 합친 실제 어휘 다양도가 아닙니다.")
    return "\n".join(lines)
