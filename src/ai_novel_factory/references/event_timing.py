"""Stage 23: offline, lexical *candidates* for event timing in an episode.

This is a positional histogram of stage-22's fixed lexical cues, NOT a semantic
recognizer for important plot events. No passages, matched words, titles, local
file paths, or reference originals are returned, logged, or persisted.
"""
from __future__ import annotations

from dataclasses import dataclass

from .episode_splitter import SplitEpisodes, split_episodes
from .episode_structure import (
    CueCounts, _PATTERNS, _body_paragraphs, _paragraphs,
    analyze_reference_structure,
)
from .plaintext_parser import ParsedReference, ReferenceParseError

MAX_EVENT_MARKERS = 20000
_CATEGORIES = ("conflict", "progression", "payoff", "reversal")


@dataclass(frozen=True)
class EventCuePosition:
    """Location of a fixed-vocabulary hit (not a confirmed story event)."""

    category: str
    paragraph_number: int  # 1-based, excludes headings and preface
    character_offset: int  # 0-based count of preceding non-whitespace chars
    position_percent: float  # percent through that episode's body, 0 <= p < 100
    quintile: int  # one of 1, 2, 3, 4, 5


@dataclass(frozen=True)
class EpisodeEventTiming:
    episode_number: int
    characters_no_whitespace: int
    paragraph_count: int
    candidate_count: int
    cue_totals: CueCounts
    quintile_counts: tuple[int, int, int, int, int]
    peak_quintile: int | None  # None if zero hits or the maximum is tied
    candidates: tuple[EventCuePosition, ...]


@dataclass(frozen=True)
class ReferenceEventTiming:
    format: str
    episode_count: int
    total_candidates: int
    quintile_counts: tuple[int, int, int, int, int]
    episodes: tuple[EpisodeEventTiming, ...]


def _validate_number(number: int) -> None:
    if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= 10000:
        raise ReferenceParseError("회차 번호가 올바르지 않습니다.")


def _validate_limit(limit: int) -> None:
    if (isinstance(limit, bool) or not isinstance(limit, int)
            or not 1 <= limit <= MAX_EVENT_MARKERS):
        raise ReferenceParseError("사건 후보 개수 제한이 올바르지 않습니다.")


def _analyze(paragraphs: list[str], number: int, budget: int) -> EpisodeEventTiming:
    """The budget may be zero when previous episodes used all allowed hits."""
    _validate_number(number)
    visible_total = sum(sum(not char.isspace() for char in paragraph)
                        for paragraph in paragraphs)
    marker_list: list[EventCuePosition] = []
    counts: dict[str, int] = dict.fromkeys(_CATEGORIES, 0)
    quintile_counts = [0, 0, 0, 0, 0]
    global_visible = 0

    for paragraph_number, paragraph in enumerate(paragraphs, 1):
        # Find all fixed-vocabulary hits and order them by actual text position.
        matches = sorted(
            ((match.start(), category)
             for category in _CATEGORIES
             for match in _PATTERNS[category].finditer(paragraph)),
            key=lambda item: (item[0], item[1]),
        )
        scan_offset = 0
        preceding_visible = 0
        for start, category in matches:
            if len(marker_list) >= budget:
                raise ReferenceParseError("사건 후보가 허용 개수를 초과했습니다.")
            preceding_visible += sum(not char.isspace()
                                     for char in paragraph[scan_offset:start])
            scan_offset = start
            absolute = global_visible + preceding_visible
            # The cue always starts on a visible character when a match exists.
            band = min(4, absolute * 5 // visible_total)
            quintile_counts[band] += 1
            counts[category] += 1
            marker_list.append(EventCuePosition(
                category=category,
                paragraph_number=paragraph_number,
                character_offset=absolute,
                position_percent=round(absolute * 100 / visible_total, 2),
                quintile=band + 1,
            ))
        global_visible += sum(not char.isspace() for char in paragraph)

    highest = max(quintile_counts)
    peaks = [i + 1 for i, count in enumerate(quintile_counts) if count == highest]
    return EpisodeEventTiming(
        episode_number=number,
        characters_no_whitespace=visible_total,
        paragraph_count=len(paragraphs),
        candidate_count=len(marker_list),
        cue_totals=CueCounts(**counts),
        quintile_counts=tuple(quintile_counts),
        peak_quintile=peaks[0] if highest > 0 and len(peaks) == 1 else None,
        candidates=tuple(marker_list),
    )


def analyze_event_timing_text(
    text: str, *, number: int = 1, max_markers: int = MAX_EVENT_MARKERS,
) -> EpisodeEventTiming:
    """Calculate lexical-cue offsets without touching disk, network or models."""
    if not isinstance(text, str):
        raise ReferenceParseError("사건 시점 분석에는 문자열이 필요합니다.")
    _validate_number(number)
    _validate_limit(max_markers)
    return _analyze(_paragraphs(text), number, max_markers)


def analyze_reference_event_timing(
    document: ParsedReference, *, split: SplitEpisodes | None = None,
    max_markers: int = MAX_EVENT_MARKERS,
) -> ReferenceEventTiming:
    """Episode-level candidate timings, excluding preface, headings and code.

    Validates the split against the document and cross-checks all stage-22
    lexical cue totals. Limits apply *across the whole reference*, not per episode.
    """
    if not isinstance(document, ParsedReference):
        raise ReferenceParseError("사건 시점을 분석할 문서 형식이 아닙니다.")
    _validate_limit(max_markers)
    if split is None:
        split = split_episodes(document)
    baseline = analyze_reference_structure(document, split=split)
    accumulated = [0, 0, 0, 0, 0]
    episodes: list[EpisodeEventTiming] = []
    budget_left = max_markers
    for episode, structure in zip(split.episodes, baseline.episodes):
        start = episode.start_block + int(split.detected_markers)
        paragraphs = _body_paragraphs(document.blocks[start:episode.end_block + 1])
        record = _analyze(paragraphs, episode.number, budget_left)
        if (record.characters_no_whitespace != structure.characters_no_whitespace
                or record.paragraph_count != structure.paragraphs):
            raise ReferenceParseError("사건 시점 분포와 본문 통계가 일치하지 않습니다.")
        expected = CueCounts(**{
            key: sum(getattr(getattr(getattr(structure, region), "cues"), key)
                     for region in ("opening", "middle", "ending"))
            for key in _CATEGORIES
        })
        if record.cue_totals != expected:
            raise ReferenceParseError("사건 후보와 구조 키워드 통계가 일치하지 않습니다.")
        budget_left -= record.candidate_count
        episodes.append(record)
        for i, count in enumerate(record.quintile_counts):
            accumulated[i] += count
    return ReferenceEventTiming(
        format=document.format,
        episode_count=len(episodes),
        total_candidates=max_markers - budget_left,
        quintile_counts=tuple(accumulated),
        episodes=tuple(episodes),
    )
