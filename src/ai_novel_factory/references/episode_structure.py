"""Stage 22: offline, evidence-limited episode structure indicators.

This module detects paragraph distribution, dialogue ratios, explicit lexical
cues, and ending punctuation. It does NOT understand plot, certify an actual
cliffhanger, or reproduce/store any reference source. Outputs are numeric or
from a fixed vocabulary only.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from .basic_statistics import measure_reference
from .dialogue_statistics import measure_dialogue_reference, measure_dialogue_text
from .episode_splitter import SplitEpisodes, split_episodes
from .plaintext_parser import ParsedBlock, ParsedReference, ReferenceParseError

_BODY_TYPES = frozenset({"paragraph", "table"})
_BLANK = re.compile(r"\n[ \t]*\n+")
# These are *observable words*, not validated interpretations of events.
_CUES: dict[str, tuple[str, ...]] = {
    "conflict": ("하지만", "그러나", "위기", "위험", "공격", "싸움", "갈등"),
    "progression": ("그리고", "그래서", "이어", "뒤이어", "그 후"),
    "payoff": ("마침내", "결국", "해결", "성공", "보상", "달성"),
    "reversal": ("그런데", "사실은", "알고 보니", "뜻밖에", "반전", "갑자기"),
}
_PATTERNS = {
    key: re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, words)) + r")(?!\w)")
    for key, words in _CUES.items()
}
_END_QUOTES = '\"\'”’」』)]} \t\r\n'


@dataclass(frozen=True)
class CueCounts:
    """Occurrences of preconfigured cue words, not story-event counts."""

    conflict: int = 0
    progression: int = 0
    payoff: int = 0
    reversal: int = 0


@dataclass(frozen=True)
class SectionMetrics:
    """Position-only section of an episode's body (opening/middle/ending)."""

    paragraphs: int
    characters_no_whitespace: int
    dialogue_ratio: float
    cues: CueCounts


@dataclass(frozen=True)
class EpisodeStructure:
    number: int
    paragraphs: int
    characters_no_whitespace: int
    opening: SectionMetrics
    middle: SectionMetrics
    ending: SectionMetrics
    ending_hook: str  # one of: question, ellipsis, exclamation, none
    possible_hook: bool  # punctuation marker, NOT a confirmed cliffhanger


@dataclass(frozen=True)
class ReferenceStructure:
    format: str
    episode_count: int
    episodes: tuple[EpisodeStructure, ...]
    preface_characters: int
    total_body_characters: int  # includes preface, excludes headings and code


def _paragraphs(text: str) -> list[str]:
    value = text.replace("\r\n", "\n").replace("\r", "\n")
    return [p.strip() for p in _BLANK.split(value) if p.strip()]


def _body_paragraphs(blocks: Iterable[ParsedBlock]) -> list[str]:
    output: list[str] = []
    for block in blocks:
        if block.kind in _BODY_TYPES:
            output.extend(_paragraphs(block.text))
    return output


def _section(paragraphs: list[str]) -> SectionMetrics:
    counts = {key: sum(len(pattern.findall(p)) for p in paragraphs)
              for key, pattern in _PATTERNS.items()}
    # Text remains transient within the current process; result has only metrics.
    dialogue = measure_dialogue_text("\n\n".join(paragraphs))
    return SectionMetrics(
        paragraphs=len(paragraphs),
        characters_no_whitespace=dialogue.total_characters,
        dialogue_ratio=dialogue.dialogue_ratio,
        cues=CueCounts(**counts),
    )


def _ending_hook(paragraphs: list[str]) -> str:
    if not paragraphs:
        return "none"
    ending = paragraphs[-1].strip().rstrip(_END_QUOTES)
    if ending.endswith(("?", "？")):
        return "question"
    if ending.endswith(("…", "...")):
        return "ellipsis"
    if ending.endswith(("!", "！")):
        return "exclamation"
    return "none"


def _analyze_episode(paragraphs: list[str], number: int) -> EpisodeStructure:
    if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= 10000:
        raise ReferenceParseError("회차 번호가 올바르지 않습니다.")
    count = len(paragraphs)
    sections: list[list[str]] = [[], [], []]
    for index, paragraph in enumerate(paragraphs):
        # 1 paragraph: ending only; 2: opening and ending; >=3: thirds.
        position = (2 if count == 1 else index * 2 if count == 2
                    else min(2, index * 3 // count))
        sections[position].append(paragraph)
    opening, middle, ending = (_section(s) for s in sections)
    hook = _ending_hook(paragraphs)
    return EpisodeStructure(
        number=number, paragraphs=count,
        characters_no_whitespace=sum(s.characters_no_whitespace
                                     for s in (opening, middle, ending)),
        opening=opening, middle=middle, ending=ending,
        ending_hook=hook, possible_hook=(hook != "none"),
    )


def analyze_structure_text(text: str, *, number: int = 1) -> EpisodeStructure:
    """Analyze only transient prose; no file, database, API, or model access."""
    if not isinstance(text, str):
        raise ReferenceParseError("회차 구조 분석에는 문자열이 필요합니다.")
    return _analyze_episode(_paragraphs(text), number)


def analyze_reference_structure(
    document: ParsedReference, *, split: SplitEpisodes | None = None,
) -> ReferenceStructure:
    """Analyze each stage-17 episode while excluding episode headings and code.

    Reject splits not matching the document and cross-check stage-18/21 counts.
    No text or detected keyword snippets are retained in the returned records.
    """
    if not isinstance(document, ParsedReference):
        raise ReferenceParseError("회차 구조를 분석할 문서 형식이 아닙니다.")
    if split is None:
        split = split_episodes(document)
    # Reuses stage-18 validation for boundaries and stale splits.
    baseline = measure_reference(document, split=split)
    dialogue = measure_dialogue_reference(document, split=split)
    first_start = split.episodes[0].start_block
    preface = _body_paragraphs(document.blocks[:first_start])
    episodes: list[EpisodeStructure] = []
    for index, episode in enumerate(split.episodes):
        start = episode.start_block + int(split.detected_markers)
        body = _body_paragraphs(document.blocks[start:episode.end_block + 1])
        result = _analyze_episode(body, episode.number)
        stats = baseline.episodes[index].statistics
        if (result.characters_no_whitespace != stats.characters_no_whitespace
                or result.paragraphs != stats.paragraphs
                or result.characters_no_whitespace != dialogue.episodes[index].counts.total_characters):
            raise ReferenceParseError("회차 구조와 원문 통계가 일치하지 않습니다.")
        episodes.append(result)
    preface_visible = sum(sum(not c.isspace() for c in p) for p in preface)
    if preface_visible != baseline.preface.characters_no_whitespace:
        raise ReferenceParseError("서문 통계가 일치하지 않습니다.")
    return ReferenceStructure(
        format=document.format,
        episode_count=len(episodes), episodes=tuple(episodes),
        preface_characters=preface_visible,
        total_body_characters=baseline.total.characters_no_whitespace,
    )
