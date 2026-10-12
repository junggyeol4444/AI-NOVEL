"""Stage 21: conservative quoted-dialogue vs narration statistics.

Offline, deterministic lexical estimate. Quotation marks are not proof that a
passage is spoken; single-quoted thoughts and dash-led lines are excluded.
No original novel text is returned, persisted, or sent to a model.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from .basic_statistics import measure_reference
from .episode_splitter import SplitEpisodes, split_episodes
from .plaintext_parser import ParsedBlock, ParsedReference, ReferenceParseError

_BODY_TYPES = frozenset({"paragraph", "table"})
_BLANK = re.compile(r"\n[ \t]*\n+")
_PAIRS = {'"': '"', '“': '”', '「': '」', '『': '』'}


@dataclass(frozen=True)
class DialogueCounts:
    """Non-whitespace Unicode character counts. The two classes partition total."""

    dialogue_characters: int
    narration_characters: int
    total_characters: int
    dialogue_ratio: float
    narration_ratio: float
    paragraphs: int
    unclosed_quote_paragraphs: int


@dataclass(frozen=True)
class EpisodeDialogue:
    number: int
    counts: DialogueCounts


@dataclass(frozen=True)
class ReferenceDialogue:
    format: str
    total: DialogueCounts
    episodes: tuple[EpisodeDialogue, ...]
    preface: DialogueCounts


def _is_escaped(text: str, index: int) -> bool:
    count = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        count += 1
        index -= 1
    return count % 2 == 1


def _quoted_characters(text: str) -> tuple[int, bool]:
    """Identify *balanced* quoted spans within one paragraph; fail closed.

    Nested quote pairs are allowed, but a mismatched closer invalidates the
    outer span. A dangling opening quote contributes to narration, not dialogue.
    """
    dialogue = 0
    stack: list[tuple[str, int]] = []
    for index, char in enumerate(text):
        if char not in _PAIRS and char not in _PAIRS.values():
            continue
        if _is_escaped(text, index):
            continue
        if stack and char == stack[-1][0]:
            _, start = stack.pop()
            if not stack:  # Only fully closed top-level spans are accepted.
                dialogue += sum(not c.isspace() for c in text[start:index + 1])
            continue
        if char in _PAIRS:
            stack.append((_PAIRS[char], index))
        # Ignore orphaned/mismatched closing glyphs.
    return dialogue, bool(stack)


def _paragraphs(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return [p.strip() for p in _BLANK.split(normalized) if p.strip()]


def _calculate(paragraphs: Iterable[str]) -> DialogueCounts:
    total = dialogue = unclosed = count = 0
    for paragraph in paragraphs:
        if not paragraph.strip():
            continue
        count += 1
        quoted, is_unclosed = _quoted_characters(paragraph)
        dialogue += quoted
        total += sum(not character.isspace() for character in paragraph)
        unclosed += int(is_unclosed)
    narration = total - dialogue
    return DialogueCounts(
        dialogue_characters=dialogue,
        narration_characters=narration,
        total_characters=total,
        dialogue_ratio=round(dialogue / total, 4) if total else 0.0,
        narration_ratio=round(narration / total, 4) if total else 0.0,
        paragraphs=count,
        unclosed_quote_paragraphs=unclosed,
    )


def measure_dialogue_text(text: str) -> DialogueCounts:
    """Analyse an in-memory string; no filesystem, DB, or network access."""
    if not isinstance(text, str):
        raise ReferenceParseError("대사 분석에는 문자열이 필요합니다.")
    return _calculate(_paragraphs(text))


def _body_paragraphs(blocks: Iterable[ParsedBlock]) -> list[str]:
    result: list[str] = []
    for block in blocks:
        if block.kind in _BODY_TYPES:
            result.extend(_paragraphs(block.text))
    return result


def measure_dialogue_reference(
    document: ParsedReference, *, split: SplitEpisodes | None = None,
) -> ReferenceDialogue:
    """Calculate total/preface/per-episode ratios using stage-17 boundaries.

    Reuses stage-18 validation to reject stale boundaries, excludes headings
    and code blocks, and aligns total visible characters with stage-18 figures.
    """
    if not isinstance(document, ParsedReference):
        raise ReferenceParseError("대사 분석에 사용할 문서가 올바르지 않습니다.")
    if split is None:
        split = split_episodes(document)
    baseline = measure_reference(document, split=split)
    blocks = document.blocks
    start = split.episodes[0].start_block
    preface_parts = _body_paragraphs(blocks[:start])
    chunks = [preface_parts]
    episodes: list[EpisodeDialogue] = []
    for episode in split.episodes:
        first = episode.start_block + int(split.detected_markers)
        parts = _body_paragraphs(blocks[first:episode.end_block + 1])
        chunks.append(parts)
        episodes.append(EpisodeDialogue(episode.number, _calculate(parts)))
    all_parts = [part for chunk in chunks for part in chunk]
    totals = _calculate(all_parts)
    if totals.total_characters != baseline.total.characters_no_whitespace:
        raise ReferenceParseError("대사 통계와 원문 분량이 일치하지 않습니다.")
    return ReferenceDialogue(document.format, totals, tuple(episodes), _calculate(preface_parts))
