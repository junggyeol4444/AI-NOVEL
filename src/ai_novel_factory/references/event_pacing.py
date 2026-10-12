"""Stage 24: local lexical cue density and spacing measurements.

These outputs describe observable *word-marker positions* only. They cannot
establish scene beats, causality, plot importance, or reader-perceived pacing.
No text, paths, titles or identified matches are stored in results.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, median, pstdev

from .episode_splitter import SplitEpisodes
from .event_timing import (
    MAX_EVENT_MARKERS, EpisodeEventTiming, ReferenceEventTiming,
    analyze_event_timing_text, analyze_reference_event_timing,
)
from .plaintext_parser import ParsedReference, ReferenceParseError


@dataclass(frozen=True)
class GapMetrics:
    """Start-to-start distances between adjacent cue candidates in one episode.

    No gap value is present with fewer than two candidates. `longest_span` is
    the largest boundary/start-to-start span among 0, candidate starts and the
    episode's final non-whitespace-character boundary. These spans count cue
    *start positions* and do not measure narrative scene lengths.
    """

    sample_count: int
    minimum: int | None
    maximum: int | None
    mean: float | None
    median: float | None
    standard_deviation: float | None
    coefficient_of_variation: float | None
    longest_span: int


@dataclass(frozen=True)
class EpisodePacing:
    episode_number: int
    characters_no_whitespace: int
    candidate_count: int
    candidates_per_1000_characters: float
    quintile_counts: tuple[int, int, int, int, int]
    quintile_rates: tuple[float, float, float, float, float]
    gaps: GapMetrics


@dataclass(frozen=True)
class ReferencePacing:
    format: str
    episode_count: int
    characters_no_whitespace: int  # explicit episodes only, never preface
    candidate_count: int
    candidates_per_1000_characters: float
    gap_sample_count: int  # excludes cross-episode distances
    mean_gap_characters: float | None
    episodes: tuple[EpisodePacing, ...]


def _density(candidate_count: int, character_count: int) -> float:
    return round(candidate_count * 1000 / character_count, 2) if character_count else 0.0


def _quintile_lengths(total: int) -> tuple[int, int, int, int, int]:
    """Bucket lengths corresponding to the Stage 23 floor(offset*5/total).

    Ceil-based boundaries correctly handle very short episodes, including
    episodes with fewer than five characters.
    """
    def ceiling_divide(x: int, y: int) -> int:
        return (x + y - 1) // y

    return tuple(ceiling_divide((i + 1) * total, 5)
                 - ceiling_divide(i * total, 5) for i in range(5))


def _episode(record: EpisodeEventTiming) -> EpisodePacing:
    """Compute derived metrics exclusively from trusted stage-23 records."""
    characters = record.characters_no_whitespace
    starts = [m.character_offset for m in record.candidates]
    # Keep a defensive invariant for callers passing hand-built timing objects.
    if (characters < 0 or len(starts) != record.candidate_count
            or sum(record.quintile_counts) != len(starts)
            or starts != sorted(starts)
            or any(p < 0 or p >= characters for p in starts)):
        raise ReferenceParseError("사건 후보 위치 데이터가 올바르지 않습니다.")
    differences = [right - left for left, right in zip(starts, starts[1:])]
    boundaries = [0, *starts, characters]
    longest = max((right - left for left, right in zip(boundaries, boundaries[1:])),
                  default=0)
    gaps = GapMetrics(
        sample_count=len(differences),
        minimum=min(differences) if differences else None,
        maximum=max(differences) if differences else None,
        mean=round(mean(differences), 2) if differences else None,
        median=round(median(differences), 2) if differences else None,
        standard_deviation=round(pstdev(differences), 2) if differences else None,
        coefficient_of_variation=(
            round(pstdev(differences) / mean(differences), 4)
            if differences and mean(differences) > 0 else None
        ),
        longest_span=longest,
    )
    lengths = _quintile_lengths(characters)
    return EpisodePacing(
        episode_number=record.episode_number,
        characters_no_whitespace=characters,
        candidate_count=record.candidate_count,
        candidates_per_1000_characters=_density(record.candidate_count, characters),
        quintile_counts=record.quintile_counts,
        quintile_rates=tuple(_density(n, length)
                             for n, length in zip(record.quintile_counts, lengths)),
        gaps=gaps,
    )


def analyze_pacing_text(
    text: str, *, number: int = 1, max_markers: int = MAX_EVENT_MARKERS,
) -> EpisodePacing:
    """Analyze visible-character cue density/gaps without network or I/O."""
    return _episode(analyze_event_timing_text(
        text, number=number, max_markers=max_markers,
    ))


def analyze_reference_pacing(
    document: ParsedReference, *, split: SplitEpisodes | None = None,
    timing: ReferenceEventTiming | None = None,
    max_markers: int = MAX_EVENT_MARKERS,
) -> ReferencePacing:
    """Analyze pacing per episode, excluding episode-crossing artificial gaps.

    Re-compute and compare supplied stage-23 timing to reject stale inputs.
    Stage 23 checks stage 22's counts, split identity, and the global cue cap.
    """
    if not isinstance(document, ParsedReference):
        raise ReferenceParseError("전개 속도를 분석할 문서 형식이 아닙니다.")
    baseline = analyze_reference_event_timing(
        document, split=split, max_markers=max_markers,
    )
    if timing is not None and (not isinstance(timing, ReferenceEventTiming)
                               or timing != baseline):
        raise ReferenceParseError("사건 후보 시점 결과와 원문이 일치하지 않습니다.")
    entries = tuple(_episode(item) for item in baseline.episodes)
    visible_total = sum(item.characters_no_whitespace for item in entries)
    count_total = sum(item.candidate_count for item in entries)
    if (len(entries) != baseline.episode_count
            or count_total != baseline.total_candidates):
        raise ReferenceParseError("사건 후보 수와 회차 통계가 일치하지 않습니다.")
    weighted_gap_sum = 0
    gap_samples = 0
    for item in baseline.episodes:
        offsets = [candidate.character_offset for candidate in item.candidates]
        if len(offsets) > 1:
            weighted_gap_sum += offsets[-1] - offsets[0]
            gap_samples += len(offsets) - 1
    return ReferencePacing(
        format=baseline.format,
        episode_count=len(entries),
        characters_no_whitespace=visible_total,
        candidate_count=count_total,
        candidates_per_1000_characters=_density(count_total, visible_total),
        gap_sample_count=gap_samples,
        mean_gap_characters=(round(weighted_gap_sum / gap_samples, 2)
                             if gap_samples else None),
        episodes=entries,
    )
