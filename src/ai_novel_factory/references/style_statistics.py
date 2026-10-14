"""Stage 29: deterministic offline measurements of observable writing style.

Sentence segmentation and Korean 'words' use transparent heuristics, not
morphological/semantic AI. Results contain numbers and fixed schema labels
only: no source novel text, tokens, quotations, filenames, or file paths.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
import re

from .basic_statistics import _SENTENCE_END, _body_paragraphs, _paragraphs, measure_reference
from .dialogue_statistics import measure_dialogue_reference, measure_dialogue_text
from .episode_splitter import SplitEpisodes, split_episodes
from .plaintext_parser import ParsedReference, ReferenceParseError

MAX_STYLE_TEXT_CHARS = 2_000_000
MAX_STYLE_TOKENS = 250_000
_ELLIPSES = re.compile(r"\.{3,}|…+")
_BOUNDARY = re.compile(r"^\W+|\W+$", flags=re.UNICODE)


@dataclass(frozen=True)
class LengthSummary:
    count: int
    minimum: int
    maximum: int
    mean: float
    median: float
    p90: int  # nearest rank, not interpolated
    standard_deviation: float  # population deviation


@dataclass(frozen=True)
class PunctuationCounts:
    period: int
    question: int
    exclamation: int
    ellipsis: int
    comma: int
    colon: int
    semicolon: int


@dataclass(frozen=True)
class ScriptCounts:
    hangul: int  # modern syllables plus Hangul jamo
    ascii_latin: int  # only A-Z and a-z
    digits: int  # Unicode decimal digits
    other: int  # remaining non-whitespace characters


@dataclass(frozen=True)
class StyleMetrics:
    paragraphs: int
    sentences: int
    words: int  # whitespace-delimited, not Korean morphological words
    characters_no_whitespace: int
    sentence_length: LengthSummary
    paragraph_length: LengthSummary
    analyzed_tokens: int  # normalized nonempty whitespace tokens
    unique_tokens: int
    type_token_ratio: float  # sample-length-dependent; NOT semantic diversity
    repeated_token_occurrences: int
    repetition_ratio: float
    dialogue_ratio: float  # stage-21 balanced quote estimate
    punctuation: PunctuationCounts
    scripts: ScriptCounts


@dataclass(frozen=True)
class EpisodeStyle:
    number: int
    metrics: StyleMetrics


@dataclass(frozen=True)
class ReferenceStyle:
    format: str
    total: StyleMetrics  # includes preface
    preface: StyleMetrics
    episode_count: int
    episodes: tuple[EpisodeStyle, ...]


def _length_summary(lengths: list[int]) -> LengthSummary:
    if not lengths:
        return LengthSummary(0, 0, 0, 0.0, 0.0, 0, 0.0)
    ordered = sorted(lengths)
    count = len(ordered)
    mean = sum(ordered) / count
    mid = count // 2
    median = (ordered[mid] if count % 2 else (ordered[mid - 1] + ordered[mid]) / 2)
    variance = sum((value - mean) ** 2 for value in ordered) / count
    return LengthSummary(count, ordered[0], ordered[-1], round(mean, 2),
                         round(median, 2), ordered[(9 * count + 9) // 10 - 1],
                         round(sqrt(variance), 2))


def _sentence_lengths(paragraph: str) -> list[int]:
    """Keep stage-18 punctuation rules so sentence counts are comparable."""
    lengths: list[int] = []
    start = 0
    for match in _SENTENCE_END.finditer(paragraph):
        piece = paragraph[start:match.end()]
        if piece.strip():
            lengths.append(sum(not ch.isspace() for ch in piece))
        start = match.end()
    if paragraph[start:].strip():
        lengths.append(sum(not ch.isspace() for ch in paragraph[start:]))
    return lengths


def _script_kind(character: str) -> str:
    value = ord(character)
    if (0xAC00 <= value <= 0xD7A3 or 0x1100 <= value <= 0x11FF
            or 0x3130 <= value <= 0x318F or 0xA960 <= value <= 0xA97F
            or 0xD7B0 <= value <= 0xD7FF):
        return "hangul"
    if "a" <= character <= "z" or "A" <= character <= "Z":
        return "ascii_latin"
    if character.isdecimal():
        return "digits"
    return "other"


def _validate(number: int, max_tokens: int) -> None:
    if type(number) is not int or not 1 <= number <= 10_000:
        raise ReferenceParseError("회차 번호가 올바르지 않습니다.")
    if type(max_tokens) is not int or not 1 <= max_tokens <= MAX_STYLE_TOKENS:
        raise ReferenceParseError("문체 분석 토큰 개수 제한이 올바르지 않습니다.")


def _measure(paragraphs: list[str], max_tokens: int) -> StyleMetrics:
    sentence_lengths: list[int] = []
    paragraph_lengths: list[int] = []
    tokens: set[str] = set()  # transient only: never returned or logged
    words = analyzed_tokens = 0
    punctuation = dict.fromkeys(PunctuationCounts.__dataclass_fields__, 0)
    scripts = dict.fromkeys(ScriptCounts.__dataclass_fields__, 0)

    for paragraph in paragraphs:
        paragraph_lengths.append(sum(not ch.isspace() for ch in paragraph))
        sentence_lengths.extend(_sentence_lengths(paragraph))
        chunks = paragraph.split()
        words += len(chunks)
        if words > max_tokens:
            raise ReferenceParseError("문체 분석 토큰 수가 제한을 초과했습니다.")
        for chunk in chunks:
            token = _BOUNDARY.sub("", chunk.casefold())
            if token:
                analyzed_tokens += 1
                tokens.add(token)
        ellipsis_count = ellipsis_dots = 0
        for match in _ELLIPSES.finditer(paragraph):
            ellipsis_count += 1
            ellipsis_dots += match.group().count(".")
        punctuation["ellipsis"] += ellipsis_count
        punctuation["period"] += paragraph.count(".") + paragraph.count("。") - ellipsis_dots
        punctuation["question"] += paragraph.count("?") + paragraph.count("？")
        punctuation["exclamation"] += paragraph.count("!") + paragraph.count("！")
        punctuation["comma"] += paragraph.count(",") + paragraph.count("，")
        punctuation["colon"] += paragraph.count(":") + paragraph.count("：")
        punctuation["semicolon"] += paragraph.count(";") + paragraph.count("；")
        for character in paragraph:
            if not character.isspace():
                scripts[_script_kind(character)] += 1

    visible = sum(paragraph_lengths)
    unique = len(tokens)
    repetition = analyzed_tokens - unique
    dialogue = measure_dialogue_text("\n\n".join(paragraphs))
    if dialogue.total_characters != visible or dialogue.paragraphs != len(paragraphs):
        raise ReferenceParseError("문체 지표와 대사 분량이 일치하지 않습니다.")
    return StyleMetrics(
        paragraphs=len(paragraphs), sentences=len(sentence_lengths), words=words,
        characters_no_whitespace=visible,
        sentence_length=_length_summary(sentence_lengths),
        paragraph_length=_length_summary(paragraph_lengths),
        analyzed_tokens=analyzed_tokens, unique_tokens=unique,
        type_token_ratio=round(unique / analyzed_tokens, 4) if analyzed_tokens else 0.0,
        repeated_token_occurrences=repetition,
        repetition_ratio=round(repetition / analyzed_tokens, 4) if analyzed_tokens else 0.0,
        dialogue_ratio=dialogue.dialogue_ratio,
        punctuation=PunctuationCounts(**punctuation), scripts=ScriptCounts(**scripts),
    )


def analyze_style_text(
    text: str, *, number: int = 1, max_tokens: int = MAX_STYLE_TOKENS,
) -> EpisodeStyle:
    """Measure standalone in-memory prose without persistence or external I/O."""
    if not isinstance(text, str) or len(text) > MAX_STYLE_TEXT_CHARS:
        raise ReferenceParseError("문체 분석 본문이 올바르지 않거나 너무 깁니다.")
    _validate(number, max_tokens)
    return EpisodeStyle(number, _measure(_paragraphs(text), max_tokens))


def analyze_reference_style(
    document: ParsedReference, *, split: SplitEpisodes | None = None,
    max_tokens: int = MAX_STYLE_TOKENS,
) -> ReferenceStyle:
    """Measure only prose/table blocks; omit headings/code and split markers.

    The preface is included in the whole-work metrics but not in any episode.
    Stage-18 and stage-21 baselines reject stale splits and verify counts.
    Budget covers the WHOLE work, including the preface.
    """
    if not isinstance(document, ParsedReference):
        raise ReferenceParseError("문체 분석 문서 형식이 올바르지 않습니다.")
    _validate(1, max_tokens)
    if len(document.text) > MAX_STYLE_TEXT_CHARS:
        raise ReferenceParseError("문체 분석 본문이 너무 깁니다.")
    if split is None:
        split = split_episodes(document)
    baseline = measure_reference(document, split=split)
    dialogue = measure_dialogue_reference(document, split=split)
    first = split.episodes[0].start_block
    preface_parts = _body_paragraphs(document.blocks[:first])
    episode_parts: list[list[str]] = []
    for episode in split.episodes:
        start = episode.start_block + int(split.detected_markers)
        episode_parts.append(_body_paragraphs(document.blocks[start:episode.end_block + 1]))
    all_parts = [*preface_parts, *(p for part in episode_parts for p in part)]
    # Guard the full-word total before running independent/partial calculations.
    if sum(len(p.split()) for p in all_parts) > max_tokens:
        raise ReferenceParseError("문체 분석 토큰 수가 제한을 초과했습니다.")
    total = _measure(all_parts, max_tokens)
    preface = _measure(preface_parts, max_tokens)
    episodes: list[EpisodeStyle] = []
    for index, (episode, parts) in enumerate(zip(split.episodes, episode_parts)):
        metrics = _measure(parts, max_tokens)
        expected = baseline.episodes[index].statistics
        if (metrics.paragraphs != expected.paragraphs
                or metrics.sentences != expected.sentences
                or metrics.words != expected.words
                or metrics.characters_no_whitespace != expected.characters_no_whitespace
                or metrics.dialogue_ratio != dialogue.episodes[index].counts.dialogue_ratio):
            raise ReferenceParseError("회차 문체 지표와 기존 통계가 일치하지 않습니다.")
        episodes.append(EpisodeStyle(episode.number, metrics))
    if (total.paragraphs != baseline.total.paragraphs
            or total.sentences != baseline.total.sentences
            or total.words != baseline.total.words
            or total.characters_no_whitespace != baseline.total.characters_no_whitespace
            or total.dialogue_ratio != dialogue.total.dialogue_ratio
            or preface.characters_no_whitespace != baseline.preface.characters_no_whitespace
            or preface.sentences != baseline.preface.sentences):
        raise ReferenceParseError("전체 문체 지표와 기존 통계가 일치하지 않습니다.")
    return ReferenceStyle(document.format, total, preface, len(episodes), tuple(episodes))
