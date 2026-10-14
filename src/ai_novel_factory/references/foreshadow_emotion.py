"""Stage 28: local, privacy-preserving foreshadowing and emotion *word cues*.

Counts observable, fixed-vocabulary hints and affect words in episode bodies.
The program neither resolves planted plot threads nor judges actual emotions.
No source text or matched phrases are included in result objects.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .basic_statistics import measure_reference
from .episode_splitter import SplitEpisodes, split_episodes
from .episode_structure import _body_paragraphs, _paragraphs
from .plaintext_parser import ParsedReference, ReferenceParseError

MAX_ANALYZED_TEXT_CHARS = 2_000_000
MAX_FORESHADOW_EMOTION_CUES = 20_000

# Deliberately small lexicons of literal *signals*, not meaning classifiers.
# Prefix matching permits common Korean inflections; adjacent word-prefix
# matching can still yield false positives, so do not call this sentiment AI.
_WORDS: dict[str, tuple[str, ...]] = {
    "setup": ("복선", "단서", "암시", "예언", "징조", "수상", "비밀", "숨겨"),
    "reveal": ("진실", "밝혀", "드러", "알고 보니", "정체", "폭로", "회수"),
    "positive": ("행복", "기쁘", "즐겁", "안심", "희망", "감사", "웃었", "기뻤"),
    "negative": ("슬프", "두렵", "무섭", "불안", "분노", "화났", "절망", "괴롭", "울었"),
}
_CATEGORIES = ("setup", "reveal", "positive", "negative")
_PATTERNS = {
    key: re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)) + r")",
        re.IGNORECASE,
    )
    for key, words in _WORDS.items()
}


@dataclass(frozen=True)
class CueTotals:
    """Fixed-category word occurrences; never the matched original words."""

    setup: int = 0
    reveal: int = 0
    positive: int = 0
    negative: int = 0

    @property
    def count(self) -> int:
        return self.setup + self.reveal + self.positive + self.negative


@dataclass(frozen=True)
class EmotionWindow:
    """A position-only fifth of the episode paragraph sequence."""

    quintile: int
    paragraph_count: int
    characters_no_whitespace: int
    positive_cues: int
    negative_cues: int
    balance: float
    direction: str  # no_cues / more_positive_cues / more_negative_cues / balanced_cues


@dataclass(frozen=True)
class EpisodeForeshadowEmotion:
    number: int
    paragraph_count: int
    characters_no_whitespace: int
    cues: CueTotals
    emotion_balance: float
    emotion_direction: str
    emotion_curve: tuple[EmotionWindow, ...]  # exactly five windows
    prior_setup_before_reveal_candidate: bool


@dataclass(frozen=True)
class ReferenceForeshadowEmotion:
    format: str
    episode_count: int
    total_cues: CueTotals
    overall_emotion_balance: float
    episodes: tuple[EpisodeForeshadowEmotion, ...]
    prior_setup_before_reveal_episodes: tuple[int, ...]


def _balance(positive: int, negative: int) -> float:
    count = positive + negative
    return round((positive - negative) / count, 4) if count else 0.0


def _direction(positive: int, negative: int) -> str:
    if not positive and not negative:
        return "no_cues"
    if positive > negative:
        return "more_positive_cues"
    if negative > positive:
        return "more_negative_cues"
    return "balanced_cues"


def _validate_parameters(number: int, max_cues: int) -> None:
    if type(number) is not int or not 1 <= number <= 10_000:
        raise ReferenceParseError("회차 번호가 올바르지 않습니다.")
    if type(max_cues) is not int or not 1 <= max_cues <= MAX_FORESHADOW_EMOTION_CUES:
        raise ReferenceParseError("단서 분석 개수 제한값이 올바르지 않습니다.")


def _analyze_episode(paragraphs: list[str], number: int, budget: int, prior_setup: bool) -> EpisodeForeshadowEmotion:
    """``budget`` may be zero if earlier episodes consumed all slots."""
    count = len(paragraphs)
    windows = [[0, 0, 0, 0] for _ in range(5)]  # paragraphs, chars, positive, negative
    counts = dict.fromkeys(_CATEGORIES, 0)
    for index, paragraph in enumerate(paragraphs):
        window = windows[min(4, index * 5 // count)]
        window[0] += 1
        window[1] += sum(not ch.isspace() for ch in paragraph)
        for kind in _CATEGORIES:
            hits = len(_PATTERNS[kind].findall(paragraph))
            counts[kind] += hits
            if sum(counts.values()) > budget:
                raise ReferenceParseError("복선·감정 단서 수가 제한을 초과했습니다.")
            if kind == "positive":
                window[2] += hits
            elif kind == "negative":
                window[3] += hits
    cues = CueTotals(**counts)
    curve = tuple(
        EmotionWindow(quintile=i + 1, paragraph_count=p, characters_no_whitespace=c,
                      positive_cues=positive, negative_cues=negative,
                      balance=_balance(positive, negative),
                      direction=_direction(positive, negative))
        for i, (p, c, positive, negative) in enumerate(windows)
    )
    return EpisodeForeshadowEmotion(
        number=number, paragraph_count=count,
        characters_no_whitespace=sum(w.characters_no_whitespace for w in curve),
        cues=cues,
        emotion_balance=_balance(cues.positive, cues.negative),
        emotion_direction=_direction(cues.positive, cues.negative),
        emotion_curve=curve,
        prior_setup_before_reveal_candidate=bool(prior_setup and cues.reveal),
    )


def analyze_foreshadow_emotion_text(
    text: str, *, number: int = 1,
    max_cues: int = MAX_FORESHADOW_EMOTION_CUES,
) -> EpisodeForeshadowEmotion:
    """Analyze a single transient episode; no external calls, state or files."""
    if not isinstance(text, str) or len(text) > MAX_ANALYZED_TEXT_CHARS:
        raise ReferenceParseError("분석 본문이 올바르지 않거나 너무 깁니다.")
    _validate_parameters(number, max_cues)
    return _analyze_episode(_paragraphs(text), number, max_cues, False)


def analyze_reference_foreshadow_emotion(
    document: ParsedReference, *, split: SplitEpisodes | None = None,
    max_cues: int = MAX_FORESHADOW_EMOTION_CUES,
) -> ReferenceForeshadowEmotion:
    """Analyze episode bodies, excluding preface, headings and code blocks.

    Prior setup and later reveal co-occurrences are *order signals only*:
    they DO NOT match the same planted clue or verify a narrative payoff.
    """
    if not isinstance(document, ParsedReference):
        raise ReferenceParseError("복선·감정 분석 대상 문서가 올바르지 않습니다.")
    _validate_parameters(1, max_cues)
    if split is None:
        split = split_episodes(document)
    baseline = measure_reference(document, split=split)  # validates stale/tampered split
    if len(document.text) > MAX_ANALYZED_TEXT_CHARS:
        raise ReferenceParseError("분석 본문이 너무 깁니다.")
    remaining = max_cues
    prior_setup = False
    records: list[EpisodeForeshadowEmotion] = []
    for index, episode in enumerate(split.episodes):
        start = episode.start_block + int(split.detected_markers)
        paragraphs = _body_paragraphs(document.blocks[start:episode.end_block + 1])
        record = _analyze_episode(paragraphs, episode.number, remaining, prior_setup)
        expected = baseline.episodes[index].statistics
        if (record.characters_no_whitespace != expected.characters_no_whitespace
                or record.paragraph_count != expected.paragraphs):
            raise ReferenceParseError("복선·감정 단서와 문서 통계가 일치하지 않습니다.")
        records.append(record)
        remaining -= record.cues.count
        prior_setup = prior_setup or record.cues.setup > 0
    totals = CueTotals(**{
        key: sum(getattr(ep.cues, key) for ep in records) for key in _CATEGORIES
    })
    return ReferenceForeshadowEmotion(
        format=document.format, episode_count=len(records), total_cues=totals,
        overall_emotion_balance=_balance(totals.positive, totals.negative),
        episodes=tuple(records),
        prior_setup_before_reveal_episodes=tuple(
            ep.number for ep in records if ep.prior_setup_before_reveal_candidate
        ),
    )
