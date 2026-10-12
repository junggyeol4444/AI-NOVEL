"""Stage 18: deterministic, local-only reference document statistics.

Counts the extracted prose/table body, not heading markers or code fences.
The source novel remains transient; result records contain counts only.
Korean 'words' here are whitespace-separated tokens, not morphological units.
Sentence segmentation is a transparent punctuation heuristic, not an AI claim.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from .episode_splitter import SplitEpisodes, split_episodes
from .plaintext_parser import ParsedBlock, ParsedReference, ReferenceParseError

_BODY_TYPES = frozenset({"paragraph", "table"})
_SENTENCE_END = re.compile(r"[.!?。！？]+[\"'”’）)\]]*(?=\s|$)")
_BLANK_PARAGRAPH = re.compile(r"\n[ \t]*\n+")


@dataclass(frozen=True)
class TextStatistics:
    """Prose statistics without exposing source content."""

    characters: int
    characters_no_whitespace: int
    words: int
    sentences: int
    paragraphs: int
    average_sentence_characters: float
    average_paragraph_characters: float


@dataclass(frozen=True)
class EpisodeStatistics:
    number: int
    statistics: TextStatistics


@dataclass(frozen=True)
class ReferenceStatistics:
    format: str
    total: TextStatistics
    episode_count: int
    average_episode_characters: float
    episodes: tuple[EpisodeStatistics, ...]
    preface: TextStatistics


def _paragraphs(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return [item.strip() for item in _BLANK_PARAGRAPH.split(normalized) if item.strip()]


def _sentences(text: str) -> int:
    """Count punctuation-ended units plus a final nonempty fragment."""
    count = 0
    pos = 0
    for match in _SENTENCE_END.finditer(text):
        if text[pos:match.end()].strip():
            count += 1
        pos = match.end()
    if text[pos:].strip():
        count += 1
    return count


def _from_paragraphs(paragraphs: Iterable[str]) -> TextStatistics:
    values = [p for p in paragraphs if p.strip()]
    chars = sum(len(p) for p in values)
    visible = sum(sum(not c.isspace() for c in p) for p in values)
    words = sum(len(p.split()) for p in values)
    sentences = sum(_sentences(p) for p in values)
    count = len(values)
    return TextStatistics(
        characters=chars,
        characters_no_whitespace=visible,
        words=words,
        sentences=sentences,
        paragraphs=count,
        average_sentence_characters=round(visible / sentences, 2) if sentences else 0.0,
        average_paragraph_characters=round(visible / count, 2) if count else 0.0,
    )


def measure_text(text: str) -> TextStatistics:
    """Count a standalone string without storing it or performing any I/O."""
    if not isinstance(text, str):
        raise ReferenceParseError("통계를 계산할 문자열이 필요합니다.")
    return _from_paragraphs(_paragraphs(text))


def _body_paragraphs(blocks: Iterable[ParsedBlock]) -> list[str]:
    result: list[str] = []
    for block in blocks:
        if block.kind in _BODY_TYPES:
            result.extend(_paragraphs(block.text))
    return result


def measure_reference(
    document: ParsedReference,
    *,
    split: SplitEpisodes | None = None,
) -> ReferenceStatistics:
    """Measure prose in document order and each episode; do not alter document.

    A previously computed SplitEpisodes may be provided by the caller. Its
    slice boundaries must refer to this exact document, otherwise we reject it.
    Explicit episode headings (even if typed as paragraph in TXT) are excluded
    from prose statistics. Prelude body counts toward total, not episode length.
    """
    if not isinstance(document, ParsedReference):
        raise ReferenceParseError("통계를 계산할 문서 형식이 아닙니다.")
    if split is None:
        split = split_episodes(document)
    if not isinstance(split, SplitEpisodes) or not split.episodes:
        raise ReferenceParseError("회차 분리 결과가 올바르지 않습니다.")
    # A provided split may be stale or derived from a different document.
    if split != split_episodes(document):
        raise ReferenceParseError("회차 분리 결과와 입력 문서가 일치하지 않습니다.")

    blocks = document.blocks
    episode_parts: list[list[str]] = []
    last_end = -1
    first_start = split.episodes[0].start_block
    for i, episode in enumerate(split.episodes):
        # All indices refer to the provided document. The start is the heading
        # marker when markers exist; it is body content when no markers exist.
        if (episode.start_block <= last_end or episode.start_block < 0
                or episode.end_block < episode.start_block
                or episode.end_block >= len(blocks)):
            raise ReferenceParseError("회차 구간과 본문이 일치하지 않습니다.")
        if i and episode.start_block != last_end + 1:
            raise ReferenceParseError("회차 사이에 처리되지 않은 내용이 있습니다.")
        start = episode.start_block + (1 if split.detected_markers else 0)
        episode_parts.append(_body_paragraphs(blocks[start:episode.end_block + 1]))
        last_end = episode.end_block
    if last_end != len(blocks) - 1:
        raise ReferenceParseError("회차 구간이 문서 끝까지 이어지지 않습니다.")
    if not split.detected_markers and first_start != 0:
        raise ReferenceParseError("회차 분리 결과가 올바르지 않습니다.")

    preface_parts = _body_paragraphs(blocks[:first_start])
    per_episode = tuple(
        EpisodeStatistics(e.number, _from_paragraphs(parts))
        for e, parts in zip(split.episodes, episode_parts)
    )
    complete = _from_paragraphs([*preface_parts, *(p for part in episode_parts for p in part)])
    return ReferenceStatistics(
        format=document.format,
        total=complete,
        episode_count=len(per_episode),
        average_episode_characters=round(
            sum(e.statistics.characters_no_whitespace for e in per_episode) / len(per_episode), 2,
        ),
        episodes=per_episode,
        preface=_from_paragraphs(preface_parts),
    )
