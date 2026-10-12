"""Stage 23: offline lexical cue timing, not confirmed plot-event detection.

Markers store positions and fixed category labels only. Never store, display,
send, or log source paragraphs, matched original words, titles or local paths.
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
    """A fixed-vocabulary cue occurrence, not a confirmed story event."""

    category: str
    paragraph_number: int
    character_offset: int
    position_percent: float
    quintile: int


@dataclass(frozen=True)
class EpisodeEventTiming:
    episode_number: int
    characters_no_whitespace: int
    paragraph_count: int
    candidate_count: int
    cue_totals: CueCounts
    quintile_counts: tuple[int, int, int, int, int]
    peak_quintile: int | None
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
    """The budget may be zero if previous episodes have used all hit slots."""
    _validate_number(number)
    visible_total = sum(sum(not ch.isspace() for ch in paragraph)
                        for paragraph in paragraphs)
    markers: list[EventCuePosition] = []
    counts: dict[str, int] = dict.fromkeys(_CATEGORIES, 0)
    bands = [0, 0, 0, 0, 0]
    global_visible = 0

    for paragraph_no, paragraph in enumerate(paragraphs, 1):
        matches = sorted(
            ((match.start(), category)
             for category in _CATEGORIES
             for match in _PATTERNS[category].finditer(paragraph)),
            key=lambda item: (item[0], item[1]),
        )
        cursor = 0
        preceding_visible = 0
        for start, category in matches:
            if len(markers) >= budget:
                raise ReferenceParseError("사건 후보가 허용 개수를 초과했습니다.")
            preceding_visible += sum(not ch.isspace()
                                     for ch in paragraph[cursor:start])
            cursor = start
            offset = global_visible + preceding_visible
            band = min(4, offset * 5 // visible_total)
            bands[band] += 1
            counts[category] += 1
            markers.append(EventCuePosition(
                category=category,
                paragraph_number=paragraph_no,
                character_offset=offset,
                position_percent=round(offset * 100 / visible_total, 2),
                quintile=band + 1,
            ))
        global_visible += sum(not ch.isspace() for ch in paragraph)

    maximum = max(bands)
    tied = [idx + 1 for idx, count in enumerate(bands) if count == maximum]
    return EpisodeEventTiming(
        episode_number=number,
        characters_no_whitespace=visible_total,
        paragraph_count=len(paragraphs),
        candidate_count=len(markers),
        cue_totals=CueCounts(**counts),
        quintile_counts=tuple(bands),
        peak_quintile=tied[0] if maximum > 0 and len(tied) == 1 else None,
        candidates=tuple(markers),
    )


def analyze_event_timing_text(
    text: str, *, number: int = 1, max_markers: int = MAX_EVENT_MARKERS,
) -> EpisodeEventTiming:
    """Return only cue counts/offsets, not raw reference source."""
    if not isinstance(text, str):
        raise ReferenceParseError("사건 시점 분석에는 문자열이 필요합니다.")
    _validate_number(number)
    _validate_limit(max_markers)
    return _analyze(_paragraphs(text), number, max_markers)


def analyze_reference_event_timing(
    document: ParsedReference, *, split: SplitEpisodes | None = None,
    max_markers: int = MAX_EVENT_MARKERS,
) -> ReferenceEventTiming:
    """Cross-check stage-22 cue counts, excluding headings, code and preface.

    The marker budget applies to the entire reference, not to each episode.
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
        for idx, count in enumerate(record.quintile_counts):
            accumulated[idx] += count
    return ReferenceEventTiming(
        format=document.format,
        episode_count=len(episodes),
        total_candidates=max_markers - budget_left,
        quintile_counts=tuple(accumulated),
        episodes=tuple(episodes),
    )
