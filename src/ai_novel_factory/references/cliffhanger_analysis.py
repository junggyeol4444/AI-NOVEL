"""Stage 25: deterministic end-of-episode cliffhanger *signals*.

All analysis is local, lexical/punctuation-based and intentionally conservative
about what it claims. These are possible hook patterns, not confirmed plot
revelations, threats, decisions, or reader engagement. No reference excerpts,
matched words, or file paths are retained in returned records.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .episode_splitter import SplitEpisodes, split_episodes
from .episode_structure import (
    _body_paragraphs, _ending_hook, _paragraphs, analyze_reference_structure,
)
from .plaintext_parser import ParsedReference, ReferenceParseError

# Stable vocabulary used for reports and tests; never user-derived labels.
LEXICAL_TYPES = ("revelation", "danger", "interruption", "decision")
PUNCTUATION_TYPES = ("question", "ellipsis", "exclamation")
TYPE_PRIORITY = (*LEXICAL_TYPES, *PUNCTUATION_TYPES)

# Fixed lexical indicators can have false positives (quotations, negation,
# metaphor, etc). They are *candidate signals*, not real scene classifications.
_CUE_TERMS = {
    "revelation": ("사실은", "알고 보니", "정체가", "진실은", "비밀은", "밝혀졌다"),
    "danger": ("죽을", "죽음", "위협", "폭발", "위기", "공격", "총구", "칼날"),
    "interruption": ("그 순간", "바로 그때", "그때였다", "문이 열렸다", "불이 꺼졌다"),
    "decision": ("선택해야", "결정해야", "어떻게 해야", "둘 중 하나", "골라야"),
}
_PATTERNS = {
    kind: re.compile("|".join(re.escape(word) for word in _CUE_TERMS[kind]))
    for kind in LEXICAL_TYPES
}


@dataclass(frozen=True)
class LexicalSignals:
    revelation: int = 0
    danger: int = 0
    interruption: int = 0
    decision: int = 0


@dataclass(frozen=True)
class EpisodeCliffhanger:
    number: int
    body_characters: int
    paragraph_count: int
    analyzed_tail_paragraphs: int
    analyzed_tail_characters: int
    ending_punctuation: str  # question, ellipsis, exclamation, none
    lexical_signals: LexicalSignals
    candidate_types: tuple[str, ...]
    primary_type: str  # fixed heuristic priority, or none
    possible_cliffhanger: bool


@dataclass(frozen=True)
class ReferenceCliffhangers:
    format: str
    episode_count: int
    possible_cliffhanger_count: int
    # Fixed category names only; counts include the 'none' category.
    primary_type_counts: tuple[tuple[str, int], ...]
    episodes: tuple[EpisodeCliffhanger, ...]


def _validate_number(number: int) -> None:
    if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= 10000:
        raise ReferenceParseError("회차 번호가 올바르지 않습니다.")


def _analyze_episode(paragraphs: list[str], number: int) -> EpisodeCliffhanger:
    _validate_number(number)
    paragraph_count = len(paragraphs)
    # Last quarter of paragraphs, with a ceiling of three whole paragraphs.
    # For a single long paragraph, the entire paragraph is considered; this
    # limitation is documented rather than silently claiming scene detection.
    tail_count = min(3, (paragraph_count + 3) // 4) if paragraph_count else 0
    tail = paragraphs[-tail_count:] if tail_count else []
    tail_text = "\n\n".join(tail)
    signal_counts = LexicalSignals(**{
        name: len(pattern.findall(tail_text)) for name, pattern in _PATTERNS.items()
    })
    punctuation = _ending_hook(paragraphs)
    candidate_types = tuple(
        name for name in TYPE_PRIORITY
        if (getattr(signal_counts, name) > 0 if name in LEXICAL_TYPES
            else name == punctuation)
    )
    total_chars = sum(sum(not ch.isspace() for ch in p) for p in paragraphs)
    tail_chars = sum(sum(not ch.isspace() for ch in p) for p in tail)
    return EpisodeCliffhanger(
        number=number,
        body_characters=total_chars,
        paragraph_count=paragraph_count,
        analyzed_tail_paragraphs=tail_count,
        analyzed_tail_characters=tail_chars,
        ending_punctuation=punctuation,
        lexical_signals=signal_counts,
        candidate_types=candidate_types,
        primary_type=candidate_types[0] if candidate_types else "none",
        possible_cliffhanger=bool(candidate_types),
    )


def analyze_cliffhanger_text(text: str, *, number: int = 1) -> EpisodeCliffhanger:
    """Analyze transient prose; no network, DB, model, or source persistence."""
    if not isinstance(text, str):
        raise ReferenceParseError("클리프행어 분석에는 문자열이 필요합니다.")
    return _analyze_episode(_paragraphs(text), number)


def analyze_reference_cliffhangers(
    document: ParsedReference, *, split: SplitEpisodes | None = None,
) -> ReferenceCliffhangers:
    """Analyze only episode bodies, excluding headings, code, and preface.

    Stage-22 structure analysis validates split boundaries and provides an
    independent consistency check on body size and terminal punctuation.
    """
    if not isinstance(document, ParsedReference):
        raise ReferenceParseError("클리프행어 분석 대상 문서 형식이 아닙니다.")
    if split is None:
        split = split_episodes(document)
    structure = analyze_reference_structure(document, split=split)
    results: list[EpisodeCliffhanger] = []
    for episode, baseline in zip(split.episodes, structure.episodes):
        start = episode.start_block + int(split.detected_markers)
        paragraphs = _body_paragraphs(document.blocks[start:episode.end_block + 1])
        current = _analyze_episode(paragraphs, episode.number)
        if (current.body_characters != baseline.characters_no_whitespace
                or current.paragraph_count != baseline.paragraphs
                or current.ending_punctuation != baseline.ending_hook):
            raise ReferenceParseError("회차 말미 분석과 본문 구조 통계가 일치하지 않습니다.")
        results.append(current)
    possible_count = sum(item.possible_cliffhanger for item in results)
    counts = tuple(
        (name, sum(item.primary_type == name for item in results))
        for name in (*TYPE_PRIORITY, "none")
    )
    return ReferenceCliffhangers(
        format=document.format,
        episode_count=len(results),
        possible_cliffhanger_count=possible_count,
        primary_type_counts=counts,
        episodes=tuple(results),
    )
