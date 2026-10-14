"""Stage 36: offline retrieval of *statistically* related genre patterns.

Only six explicitly selected aggregate metrics are compared. No novel text,
keywords, semantic embeddings, prompt construction, network, or remote service.
Similarity is a bounded descriptive distance, NOT creative suitability.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from ai_novel_factory.database.reference_catalog import ReferenceCatalog
from ai_novel_factory.database.genre_patterns import GenrePatternStore, GenreStorageError
from ai_novel_factory.database.pattern_strengths import PatternStrengthStore
from ai_novel_factory.database.element_selections import (
    ElementSelectionStore, ElementSelectionStorageError,
)
from .element_selection import FEATURE_KEYS, FEATURE_LABELS, ElementSelection
from .genre_patterns import GENRE_NAMES
from .pattern_strength import PatternStrengthError, preview_strengths, PatternStrengthPreview

MAX_RESULTS = 11  # 12 fixed genres, excluding the selected source genre.
# Per-metric scales are declared explicitly; never normalize using 1e9 database
# schema bounds (that would make sentence length differences meaningless).
_FIXED_SCALES = {
    "dialogue_ratio": 1.0,
    "sentence_characters": 20.0,
    "lexical_diversity": 1.0,
    "emotion_balance": 2.0,
    "cliffhanger_episode_rate": 1.0,
    "event_cue_density_per_1000": 10.0,
}


class RelatedPatternError(ValueError):
    """Fixed, privacy-preserving error strings only."""


@dataclass(frozen=True)
class MetricDifference:
    key: str
    distance: float  # Unit-free distance 0..1 (1 means very different).


@dataclass(frozen=True)
class RelatedPattern:
    genre: str
    reference_count: int
    similarity_percent: float
    differences: tuple[MetricDifference, ...]


@dataclass(frozen=True)
class RelatedPatternResults:
    source_genre: str
    weighting: str
    selected_keys: tuple[str, ...]
    inspected_count: int
    excluded_stale: int
    excluded_unsafe: int
    filtered_by_threshold: int
    matches: tuple[RelatedPattern, ...]


def _distance(key: str, left: float, right: float) -> float:
    if (key not in _FIXED_SCALES or type(left) not in (int, float)
            or type(right) not in (int, float)
            or not isfinite(left) or not isfinite(right)):
        raise RelatedPatternError("비교 통계 값이 유효하지 않습니다.")
    # Ratio metrics have a fixed natural range; other metrics use a stable
    # positive floor, while scaling very large observations proportionally.
    scale = max(_FIXED_SCALES[key], abs(left), abs(right))
    return round(min(1.0, abs(left - right) / scale), 6)


def _feature_values(preview: PatternStrengthPreview) -> dict[str, float]:
    if (type(preview) is not PatternStrengthPreview
            or tuple(f.key for f in preview.features) != FEATURE_KEYS
            or preview.usable_for_selection is not True or preview.status != "ready"
            or preview.active_count < 2 or not 0 <= preview.max_share_percent <= 60.00000001):
        raise RelatedPatternError("참고작 강도가 유효하지 않습니다.")
    values = {}
    for item in preview.features:
        if type(item.weighted_mean) not in (int, float) or not isfinite(item.weighted_mean):
            raise RelatedPatternError("비교 통계 값이 유효하지 않습니다.")
        values[item.key] = float(item.weighted_mean)
    return values


class RelatedPatternSearch:
    """Queries existing local SQLite recipes without persisting search history."""

    def __init__(self, catalog: ReferenceCatalog) -> None:
        if not isinstance(catalog, ReferenceCatalog):
            raise RelatedPatternError("로컬 SQLite 저장소가 필요합니다.")
        self._genres = GenrePatternStore(catalog)
        self._strengths = PatternStrengthStore(catalog)
        self._selections = ElementSelectionStore(catalog)

    def search(self, genre: str, *, weighting: str = "equal", limit: int = 10,
               min_similarity: float = 0.0) -> RelatedPatternResults:
        if type(genre) is not str or genre not in GENRE_NAMES:
            raise RelatedPatternError("장르 코드가 올바르지 않습니다.")
        if type(weighting) is not str or weighting not in ("equal", "characters"):
            raise RelatedPatternError("가중치 형식이 올바르지 않습니다.")
        if type(limit) is not int or not 1 <= limit <= MAX_RESULTS:
            raise RelatedPatternError("검색 결과는 1~11개까지 요청할 수 있습니다.")
        if (type(min_similarity) not in (int, float) or not isfinite(min_similarity)
                or not 0 <= min_similarity <= 100):
            raise RelatedPatternError("유사도 하한은 0~100 사이 숫자여야 합니다.")
        try:
            selection = self._selections.get(genre, weighting=weighting)
        except ElementSelectionStorageError:
            raise RelatedPatternError("해당 장르의 유효한 참고 요소 선택이 필요합니다.") from None
        if (type(selection) is not ElementSelection or selection.genre != genre
                or selection.weighting != weighting
                or not 1 <= len(selection.selected_keys) <= len(FEATURE_KEYS)
                or len(selection.selected_keys) != len(selection.elements)
                or len(set(selection.selected_keys)) != len(selection.selected_keys)
                or any(k not in FEATURE_KEYS for k in selection.selected_keys)):
            raise RelatedPatternError("참고 요소 선택이 올바르지 않습니다.")
        observed = {item.key: float(item.observed_mean) for item in selection.elements
                    if type(item.observed_mean) in (int, float) and isfinite(item.observed_mean)}
        if tuple(observed) != selection.selected_keys:
            raise RelatedPatternError("참고 요소 선택 통계가 손상되었습니다.")
        try:
            available = self._genres.list_patterns()
        except GenreStorageError:
            raise RelatedPatternError("패턴 목록을 읽지 못했습니다.") from None

        matches = []
        stale = unsafe = filtered = inspected = 0
        for row in available:
            if row.genre == genre or row.weighting != weighting:
                continue
            inspected += 1
            if not row.current:
                stale += 1
                continue
            try:
                preview = preview_strengths(self._genres, self._strengths, row.genre,
                                            weighting=weighting)
                candidate = _feature_values(preview)
            except PatternStrengthError:
                stale += 1
                continue
            except RelatedPatternError:
                unsafe += 1
                continue
            differences = tuple(MetricDifference(key, _distance(key, observed[key], candidate[key]))
                                for key in selection.selected_keys)
            similarity = round(100.0 * (1.0 - sum(x.distance for x in differences)
                                          / len(differences)), 2)
            if similarity < min_similarity:
                filtered += 1
                continue
            matches.append(RelatedPattern(row.genre, preview.reference_count,
                                          similarity, differences))
        matches.sort(key=lambda record: (-record.similarity_percent, record.genre))
        return RelatedPatternResults(genre, weighting, selection.selected_keys, inspected,
                                     stale, unsafe, filtered, tuple(matches[:limit]))


def render_related_patterns(results: RelatedPatternResults) -> str:
    """Render fixed genre names and anonymous numeric metric differences only."""
    if (type(results) is not RelatedPatternResults or results.source_genre not in GENRE_NAMES
            or results.weighting not in ("equal", "characters")
            or not 1 <= len(results.selected_keys) <= len(FEATURE_KEYS)
            or len(set(results.selected_keys)) != len(results.selected_keys)
            or any(k not in FEATURE_KEYS for k in results.selected_keys)
            or any(type(n) is not int or n < 0 for n in (
                results.inspected_count, results.excluded_stale,
                results.excluded_unsafe, results.filtered_by_threshold))
            or type(results.matches) is not tuple or len(results.matches) > MAX_RESULTS):
        raise RelatedPatternError("검색 결과 형식이 올바르지 않습니다.")
    lines = [f"관련 패턴 검색 · {GENRE_NAMES[results.source_genre]} ({results.weighting})",
             "비교 요소: " + ", ".join(FEATURE_LABELS[k] for k in results.selected_keys),
             f"검토 {results.inspected_count}개 · 오래됨 {results.excluded_stale}개 · "
             f"강도/데이터 부적합 {results.excluded_unsafe}개 · 하한 미달 {results.filtered_by_threshold}개",
             "통계적으로 가까운 장르 패턴 (문체 모방·작품 추천 점수 아님):"]
    for entry in results.matches:
        if (type(entry) is not RelatedPattern or entry.genre not in GENRE_NAMES
                or entry.genre == results.source_genre or type(entry.reference_count) is not int
                or not 2 <= entry.reference_count <= 50
                or type(entry.similarity_percent) not in (int, float)
                or not isfinite(entry.similarity_percent)
                or not 0 <= entry.similarity_percent <= 100
                or tuple(item.key for item in entry.differences) != results.selected_keys
                or any(type(item) is not MetricDifference or type(item.distance) not in (int, float)
                       or not isfinite(item.distance) or not 0 <= item.distance <= 1
                       for item in entry.differences)):
            raise RelatedPatternError("검색 결과 항목이 손상되었습니다.")
        lines.append(f"- {GENRE_NAMES[entry.genre]} ({entry.genre}) · {entry.reference_count}작품 · "
                     f"통계 근접도 {entry.similarity_percent:.2f}%")
    if not results.matches:
        lines.append("조건에 맞는 패턴이 없습니다.")
    lines.append("주의: 통계 근접도는 서사 의미나 창작 적합성/품질을 보증하지 않습니다.")
    lines.append("소설 원문·파일명·문구는 검색 및 결과에 포함되지 않습니다.")
    return "\n".join(lines)
