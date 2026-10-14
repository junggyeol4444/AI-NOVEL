"""Stage 32: offline genre-pattern statistics from anonymized reference profiles.

Genre is a *user-assigned classification*. Nothing here guesses a genre from
source text, claims narrative comprehension, or generates imitative prose.
Results contain only fixed labels and aggregate numeric values.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from .plaintext_parser import ReferenceParseError
from .profile_collection import (
    MAX_COLLECTION_REFERENCES, WEIGHTING_MODES, MetricSpread,
    ProfileCollection, combine_reference_profiles, render_profile_collection,
)
from .reference_profile import ReferenceProfile

GENRE_NAMES: dict[str, str] = {
    "fantasy": "판타지",
    "romance": "로맨스",
    "mystery": "미스터리",
    "thriller": "스릴러",
    "science_fiction": "SF",
    "historical": "역사",
    "martial_arts": "무협",
    "horror": "공포",
    "contemporary": "현대물",
    "drama": "드라마",
    "comedy": "코미디",
    "other": "기타",
}
GENRE_PATTERN_VERSION = 1
_FEATURES = (
    ("dialogue_ratio", "대사 비율", 0.0, 1.0),
    ("sentence_characters", "평균 문장 길이", 0.0, 1_000_000_000.0),
    ("lexical_diversity", "어휘 다양도", 0.0, 1.0),
    ("emotion_balance", "감정 어휘 균형", -1.0, 1.0),
    ("cliffhanger_episode_rate", "회차 말미 단서 비율", 0.0, 1.0),
    ("event_cue_density_per_1000", "1,000자당 사건 어휘", 0.0, 1_000_000.0),
)


@dataclass(frozen=True)
class GenreFeature:
    """Observed spread and optional descriptive one-SD interval (not targets)."""

    key: str
    observed_min: float
    observed_max: float
    weighted_mean: float
    standard_deviation: float
    typical_low: float
    typical_high: float


@dataclass(frozen=True)
class GenrePattern:
    schema_version: int
    genre: str
    weighting: str
    reference_count: int
    collection: ProfileCollection
    features: tuple[GenreFeature, ...]


def validate_genre(genre: str) -> str:
    if type(genre) is not str or genre not in GENRE_NAMES:
        raise ReferenceParseError("지원하는 장르 코드 중 하나를 선택하세요.")
    return genre


def _event_spread(profiles: tuple[ReferenceProfile, ...], weighting: str) -> MetricSpread:
    values = tuple(1000 * p.event_cue_candidates / p.total_characters
                   if p.total_characters else 0.0 for p in profiles)
    weights = tuple(float(p.total_characters) for p in profiles) if weighting == "characters" else (1.0,) * len(profiles)
    if not any(weights):
        weights = (1.0,) * len(profiles)
    total = sum(weights)
    mean = sum(x * w for x, w in zip(values, weights)) / total
    std = sqrt(sum(w * (x - mean) ** 2 for x, w in zip(values, weights)) / total)
    return MetricSpread(round(min(values), 6), round(max(values), 6),
                        round(mean, 6), round(std, 6))


def _feature(key: str, spread: MetricSpread, low: float, high: float) -> GenreFeature:
    return GenreFeature(key=key, observed_min=spread.minimum,
                        observed_max=spread.maximum, weighted_mean=spread.weighted_mean,
                        standard_deviation=spread.standard_deviation,
                        typical_low=round(max(low, spread.weighted_mean - spread.standard_deviation), 6),
                        typical_high=round(min(high, spread.weighted_mean + spread.standard_deviation), 6))


def build_genre_pattern(
    genre: str,
    profiles: list[ReferenceProfile] | tuple[ReferenceProfile, ...],
    *, weighting: str = "equal",
) -> GenrePattern:
    """Aggregate 2..50 reference profiles that humans assigned to a genre.

    A single work is insufficient for a multi-work genre pattern. No text,
    network access, copying, author imitation, or genre prediction occurs.
    """
    validate_genre(genre)
    # Stage 31 owns strict content/count/weighting validation and bin aggregation.
    collection = combine_reference_profiles(profiles, weighting=weighting)
    data = tuple(profiles)
    spreads = {
        "dialogue_ratio": collection.dialogue_ratio,
        "sentence_characters": collection.sentence_characters,
        "lexical_diversity": collection.lexical_diversity,
        "emotion_balance": collection.emotion_balance,
        "cliffhanger_episode_rate": collection.cliffhanger_episode_rate,
        "event_cue_density_per_1000": _event_spread(data, weighting),
    }
    return GenrePattern(
        schema_version=GENRE_PATTERN_VERSION,
        genre=genre, weighting=weighting, reference_count=collection.reference_count,
        collection=collection,
        features=tuple(_feature(key, spreads[key], lo, hi)
                       for key, _label, lo, hi in _FEATURES),
    )


def render_genre_pattern(pattern: GenrePattern) -> str:
    """Only fixed vocabulary and numbers; never serialize filenames or quotations."""
    if (type(pattern) is not GenrePattern or pattern.schema_version != GENRE_PATTERN_VERSION
            or type(pattern.reference_count) is not int
            or pattern.reference_count < 2 or pattern.reference_count > MAX_COLLECTION_REFERENCES
            or type(pattern.collection) is not ProfileCollection
            or pattern.reference_count != pattern.collection.reference_count
            or pattern.weighting not in WEIGHTING_MODES
            or pattern.weighting != pattern.collection.weighting
            or type(pattern.features) is not tuple
            or tuple(f.key for f in pattern.features if type(f) is GenreFeature)
            != tuple(f[0] for f in _FEATURES) or len(pattern.features) != len(_FEATURES)):
        raise ReferenceParseError("장르 패턴 자료형이 올바르지 않습니다.")
    validate_genre(pattern.genre)
    lines = [f"장르 패턴: {GENRE_NAMES[pattern.genre]} ({pattern.genre})",
             "분류: 사용자 직접 지정 · 통계 기반 관찰값 · 작품/작가 문체 복제용 아님",
             "특징 | 관찰 최솟값 | 관찰 최댓값 | 평균 | 표준편차 | 평균±표준편차"]
    for item, (_, label, _, _) in zip(pattern.features, _FEATURES):
        lines.append(f"{label} | {item.observed_min:.4f} | {item.observed_max:.4f} | "
                     f"{item.weighted_mean:.4f} | {item.standard_deviation:.4f} | "
                     f"{item.typical_low:.4f}~{item.typical_high:.4f}")
    lines.extend(("", render_profile_collection(pattern.collection),
                  "주의: 단서 빈도는 실제 서사 사건/복선의 의미나 장르 특성의 인과관계를 입증하지 않습니다.",
                  "주의: 참고작 수와 선정 편향을 확인하세요. 위 범위는 창작 목표치가 아닙니다."))
    return "\n".join(lines)
