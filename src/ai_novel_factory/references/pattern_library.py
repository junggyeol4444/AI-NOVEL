"""Stage 33: text-free, offline browse/search/compare over saved genre recipes.

No new persistence, network, model or source-file access. Stage 32 owns
cohort freshness and re-aggregation. This library never interprets a pattern
as a writing target or imitates a reference author's language.
"""
from __future__ import annotations

from dataclasses import dataclass

from ai_novel_factory.database.genre_patterns import GenrePatternStore, GenreStorageError
from .genre_patterns import GENRE_NAMES, GenrePattern, _FEATURES
from .profile_collection import WEIGHTING_MODES

MAX_COMPARE = 12
MAX_PAGE_SIZE = 100
MAX_SEARCH_LENGTH = 80


class PatternLibraryError(ValueError):
    """Error message does not expose source content, local paths or DB text."""


@dataclass(frozen=True)
class LibraryEntry:
    genre: str
    weighting: str
    reference_count: int
    current: bool


@dataclass(frozen=True)
class LibraryPage:
    total: int
    offset: int
    limit: int
    entries: tuple[LibraryEntry, ...]


@dataclass(frozen=True)
class ComparedFeature:
    key: str
    means: tuple[float, ...]  # values aligned with the genres in the comparison
    minimum_mean: float
    maximum_mean: float
    difference: float


@dataclass(frozen=True)
class LibraryComparison:
    weighting: str
    genres: tuple[str, ...]
    reference_counts: tuple[int, ...]
    features: tuple[ComparedFeature, ...]


def _check_weighting(weighting: str | None) -> None:
    if weighting is not None and (type(weighting) is not str or weighting not in WEIGHTING_MODES):
        raise PatternLibraryError("지원하지 않는 가중치입니다.")


def _check_genre(genre: str | None) -> None:
    if genre is not None and (type(genre) is not str or genre not in GENRE_NAMES):
        raise PatternLibraryError("지원하지 않는 장르입니다.")


class ReferencePatternLibrary:
    """Read-only views backed exclusively by the local stage-32 SQLite store."""

    def __init__(self, store: GenrePatternStore) -> None:
        if not isinstance(store, GenrePatternStore):
            raise PatternLibraryError("로컬 장르 패턴 저장소가 필요합니다.")
        self._store = store

    def search(
        self, *, query: str = "", genre: str | None = None,
        weighting: str | None = None, current: bool | None = None,
        limit: int = 50, offset: int = 0,
    ) -> LibraryPage:
        """Filter only the fixed taxonomy and metadata; never the source novel."""
        if (type(query) is not str or len(query) > MAX_SEARCH_LENGTH
                or any(ord(ch) < 32 for ch in query)):
            raise PatternLibraryError("검색어가 올바르지 않습니다.")
        _check_genre(genre)
        _check_weighting(weighting)
        if current is not None and type(current) is not bool:
            raise PatternLibraryError("최신 상태 검색 조건이 올바르지 않습니다.")
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
            raise PatternLibraryError("페이지 크기는 1~100이어야 합니다.")
        if type(offset) is not int or not 0 <= offset <= 10000:
            raise PatternLibraryError("검색 시작 위치가 올바르지 않습니다.")
        tokens = query.casefold().strip().split()
        try:
            saved = self._store.list_patterns()
        except GenreStorageError:
            raise PatternLibraryError("패턴 라이브러리를 읽을 수 없습니다.") from None
        filtered = []
        for row in saved:
            if genre is not None and row.genre != genre:
                continue
            if weighting is not None and row.weighting != weighting:
                continue
            if current is not None and row.current != current:
                continue
            searchable = f"{row.genre} {GENRE_NAMES[row.genre]} {row.weighting}".casefold()
            if any(token not in searchable for token in tokens):
                continue
            filtered.append(LibraryEntry(row.genre, row.weighting, row.reference_count, row.current))
        return LibraryPage(len(filtered), offset, limit, tuple(filtered[offset:offset + limit]))

    def get(self, genre: str, *, weighting: str = "equal") -> GenrePattern:
        """Recompute from anonymous profiles, rejecting stale selections."""
        _check_genre(genre)
        _check_weighting(weighting)
        try:
            return self._store.get(genre, weighting=weighting)
        except GenreStorageError:
            raise PatternLibraryError("저장된 패턴이 없거나 최신 상태가 아닙니다. 다시 구축하세요.") from None

    def compare(self, genres: list[str] | tuple[str, ...], *, weighting: str = "equal") -> LibraryComparison:
        """Compare 2..12 distinct current genres using the *same* weighting.

        Numbers are descriptive; we do not rank across different metric units
        or different weighting policies. Failed comparisons never update DB.
        """
        _check_weighting(weighting)
        if (type(genres) not in (list, tuple) or not 2 <= len(genres) <= MAX_COMPARE
                or any(type(item) is not str or item not in GENRE_NAMES for item in genres)
                or len(set(genres)) != len(genres)):
            raise PatternLibraryError("비교할 서로 다른 장르 패턴을 2~12개 선택하세요.")
        items = tuple(self.get(genre, weighting=weighting) for genre in genres)
        if any(item.weighting != weighting for item in items):
            raise PatternLibraryError("동일 가중치의 패턴만 비교할 수 있습니다.")
        features = []
        for index, (key, _label, _low, _high) in enumerate(_FEATURES):
            values = tuple(item.features[index].weighted_mean for item in items)
            if any(item.features[index].key != key for item in items):
                raise PatternLibraryError("패턴 지표 구성이 일치하지 않습니다.")
            minimum, maximum = min(values), max(values)
            features.append(ComparedFeature(key, values, minimum, maximum,
                                            round(maximum - minimum, 6)))
        return LibraryComparison(weighting, tuple(genres),
                                 tuple(item.reference_count for item in items), tuple(features))


def render_library_page(page: LibraryPage) -> str:
    """Fixed vocabulary/IDs and counts only, suitable for CLI or UI."""
    if type(page) is not LibraryPage or type(page.entries) is not tuple:
        raise PatternLibraryError("목록 형식이 올바르지 않습니다.")
    lines = [f"Reference Pattern Library · 총 {page.total}개 · {page.offset + 1}번째부터 최대 {page.limit}개", 
             "장르 | 가중치 | 참고작 수 | 상태"]
    for entry in page.entries:
        if (type(entry) is not LibraryEntry or entry.genre not in GENRE_NAMES
                or entry.weighting not in WEIGHTING_MODES or type(entry.reference_count) is not int
                or not 2 <= entry.reference_count <= 50 or type(entry.current) is not bool):
            raise PatternLibraryError("목록 항목이 올바르지 않습니다.")
        lines.append(f"{GENRE_NAMES[entry.genre]} ({entry.genre}) | {entry.weighting} | "
                     f"{entry.reference_count} | {'최신' if entry.current else '재구축 필요'}")
    if not page.entries:
        lines.append("검색 결과 없음")
    return "\n".join(lines)


def render_library_comparison(comparison: LibraryComparison) -> str:
    """Show feature means in their own units; no ranking or source data."""
    if (type(comparison) is not LibraryComparison or comparison.weighting not in WEIGHTING_MODES
            or not 2 <= len(comparison.genres) <= MAX_COMPARE
            or len(set(comparison.genres)) != len(comparison.genres)
            or any(genre not in GENRE_NAMES for genre in comparison.genres)
            or len(comparison.reference_counts) != len(comparison.genres)
            or len(comparison.features) != len(_FEATURES)):
        raise PatternLibraryError("비교 보고서가 올바르지 않습니다.")
    lines = ["Reference Pattern Library · 장르별 통계 비교", "자료: 사용자 지정 장르 · 참고작의 원문 없는 관찰 통계",
             f"가중치: {comparison.weighting}",
             "대상: " + ", ".join(f"{GENRE_NAMES[g]}({n}작품)" for g,n in
                                  zip(comparison.genres, comparison.reference_counts)),
             "지표 | " + " | ".join(GENRE_NAMES[g] for g in comparison.genres) + " | 평균값 차이"]
    for feature, (key, label, _lo, _hi) in zip(comparison.features, _FEATURES):
        if (type(feature) is not ComparedFeature or feature.key != key
                or len(feature.means) != len(comparison.genres)):
            raise PatternLibraryError("비교 지표 구성이 올바르지 않습니다.")
        lines.append(label + " | " + " | ".join(f"{v:.4f}" for v in feature.means)
                     + f" | {feature.difference:.4f}")
    lines.append("주의: 표본 크기와 선정 편향이 있으며, 값 차이는 창작 목표나 장르의 법칙이 아닙니다.")
    return "\n".join(lines)
