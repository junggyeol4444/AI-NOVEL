"""Stage 30: deterministic, text-free reference-novel analysis profile.

All values are aggregate numbers or members of fixed vocabularies. Source text,
characters' names, word lists, filenames and matched quotations never enter the
profile. This is an offline lexical/statistical profile, NOT semantic AI analysis.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .basic_statistics import measure_reference
from .cliffhanger_analysis import TYPE_PRIORITY, analyze_reference_cliffhangers
from .dialogue_statistics import measure_dialogue_reference
from .episode_splitter import SplitEpisodes, split_episodes
from .event_pacing import analyze_reference_pacing
from .foreshadow_emotion import analyze_reference_foreshadow_emotion
from .plaintext_parser import ParsedReference, ReferenceParseError
from .style_statistics import analyze_reference_style

PROFILE_SCHEMA_VERSION = 1
ALLOWED_HOOK_TYPES = frozenset((*TYPE_PRIORITY, "none"))
_ALLOWED_FORMATS = frozenset({"txt", "markdown", "docx", "pdf", "epub"})


@dataclass(frozen=True)
class EpisodeProfile:
    number: int
    characters: int
    paragraphs: int
    dialogue_ratio: float
    event_cue_candidates: int
    event_cue_density_per_1000: float
    cliffhanger_candidate: bool
    cliffhanger_type: str
    average_sentence_characters: float
    lexical_diversity: float
    emotion_balance: float
    foreshadow_setup_cues: int
    foreshadow_reveal_cues: int


@dataclass(frozen=True)
class ReferenceProfile:
    schema_version: int
    source_format: str
    episode_count: int
    total_characters: int  # includes preface; excludes headings/code
    total_paragraphs: int
    total_words: int
    dialogue_ratio: float
    narration_ratio: float
    event_cue_candidates: int  # episode body only
    event_cue_density_per_1000: float
    cliffhanger_candidate_episodes: int
    average_sentence_characters: float
    lexical_diversity: float
    emotion_balance: float
    episodes: tuple[EpisodeProfile, ...]


def validate_profile(profile: ReferenceProfile) -> None:
    """Reject untrusted/hand-built data before it reaches SQLite.

    Only numbers, booleans and fixed enumerations are accepted; strings cannot
    carry arbitrary source fragments or external addresses.
    """
    if type(profile) is not ReferenceProfile:
        raise ReferenceParseError("참고작 프로필 자료형이 올바르지 않습니다.")
    if (type(profile.schema_version) is not int or profile.schema_version != PROFILE_SCHEMA_VERSION
            or type(profile.source_format) is not str or profile.source_format not in _ALLOWED_FORMATS
            or type(profile.episode_count) is not int or not 1 <= profile.episode_count <= 10000
            or type(profile.episodes) is not tuple or len(profile.episodes) != profile.episode_count):
        raise ReferenceParseError("참고작 프로필 버전 또는 구조가 올바르지 않습니다.")

    def count(value: object) -> bool:
        return type(value) is int and 0 <= value <= 1_000_000_000

    def ratio(value: object, lo: float, hi: float) -> bool:
        return type(value) in {int, float} and isfinite(value) and lo <= value <= hi

    if not all(count(getattr(profile, key)) for key in (
        "total_characters", "total_paragraphs", "total_words", "event_cue_candidates",
        "cliffhanger_candidate_episodes",
    )):
        raise ReferenceParseError("참고작 프로필 집계값이 올바르지 않습니다.")
    if not (ratio(profile.dialogue_ratio, 0, 1) and ratio(profile.narration_ratio, 0, 1)
            and abs(profile.dialogue_ratio + profile.narration_ratio
                    - (1.0 if profile.total_characters else 0.0)) <= 0.0002
            and ratio(profile.event_cue_density_per_1000, 0, 1_000_000)
            and ratio(profile.average_sentence_characters, 0, 1_000_000_000)
            and ratio(profile.lexical_diversity, 0, 1)
            and ratio(profile.emotion_balance, -1, 1)
            and profile.cliffhanger_candidate_episodes <= profile.episode_count):
        raise ReferenceParseError("참고작 프로필 비율이 올바르지 않습니다.")

    last_number = 0
    summed_cues = summed_hooks = summed_chars = summed_paragraphs = 0
    for episode in profile.episodes:
        if type(episode) is not EpisodeProfile:
            raise ReferenceParseError("회차 프로필 자료형이 올바르지 않습니다.")
        if (type(episode.number) is not int or not last_number < episode.number <= 10000
                or any(not count(getattr(episode, field)) for field in (
                    "characters", "paragraphs", "event_cue_candidates",
                    "foreshadow_setup_cues", "foreshadow_reveal_cues",
                ))
                or type(episode.cliffhanger_candidate) is not bool
                or type(episode.cliffhanger_type) is not str
                or episode.cliffhanger_type not in ALLOWED_HOOK_TYPES
                or episode.cliffhanger_candidate != (episode.cliffhanger_type != "none")
                or not ratio(episode.dialogue_ratio, 0, 1)
                or not ratio(episode.event_cue_density_per_1000, 0, 1_000_000)
                or not ratio(episode.average_sentence_characters, 0, 1_000_000_000)
                or not ratio(episode.lexical_diversity, 0, 1)
                or not ratio(episode.emotion_balance, -1, 1)):
            raise ReferenceParseError("회차 프로필 집계값이 올바르지 않습니다.")
        last_number = episode.number
        summed_cues += episode.event_cue_candidates
        summed_hooks += int(episode.cliffhanger_candidate)
        summed_chars += episode.characters
        summed_paragraphs += episode.paragraphs
    if (summed_cues != profile.event_cue_candidates
            or summed_hooks != profile.cliffhanger_candidate_episodes
            or summed_chars > profile.total_characters
            or summed_paragraphs > profile.total_paragraphs):
        raise ReferenceParseError("참고작 프로필의 회차별 합계가 일치하지 않습니다.")


def build_reference_profile(
    document: ParsedReference, *, split: SplitEpisodes | None = None,
) -> ReferenceProfile:
    """Produce an immutable, source-free summary from a transient parsed work."""
    if not isinstance(document, ParsedReference):
        raise ReferenceParseError("참고작 프로필에 사용할 문서 형식이 아닙니다.")
    if split is None:
        split = split_episodes(document)
    baseline = measure_reference(document, split=split)
    dialogue = measure_dialogue_reference(document, split=split)
    pacing = analyze_reference_pacing(document, split=split)
    cliff = analyze_reference_cliffhangers(document, split=split)
    style = analyze_reference_style(document, split=split)
    emotion = analyze_reference_foreshadow_emotion(document, split=split)
    count = baseline.episode_count
    if any(len(value.episodes) != count for value in (dialogue, pacing, cliff, style, emotion)):
        raise ReferenceParseError("참고작 분석 결과의 회차 수가 일치하지 않습니다.")
    episodes: list[EpisodeProfile] = []
    for index in range(count):
        item = baseline.episodes[index]
        d = dialogue.episodes[index]
        p = pacing.episodes[index]
        c = cliff.episodes[index]
        s = style.episodes[index]
        e = emotion.episodes[index]
        if any(n != item.number for n in (d.number, p.episode_number, c.number, s.number, e.number)):
            raise ReferenceParseError("참고작 분석 결과의 회차 번호가 일치하지 않습니다.")
        episodes.append(EpisodeProfile(
            number=item.number,
            characters=item.statistics.characters_no_whitespace,
            paragraphs=item.statistics.paragraphs,
            dialogue_ratio=d.counts.dialogue_ratio,
            event_cue_candidates=p.candidate_count,
            event_cue_density_per_1000=p.candidates_per_1000_characters,
            cliffhanger_candidate=c.possible_cliffhanger,
            cliffhanger_type=c.primary_type,
            average_sentence_characters=s.metrics.sentence_length.mean,
            lexical_diversity=s.metrics.type_token_ratio,
            emotion_balance=e.emotion_balance,
            foreshadow_setup_cues=e.cues.setup,
            foreshadow_reveal_cues=e.cues.reveal,
        ))
    result = ReferenceProfile(
        schema_version=PROFILE_SCHEMA_VERSION,
        source_format=document.format,
        episode_count=count,
        total_characters=baseline.total.characters_no_whitespace,
        total_paragraphs=baseline.total.paragraphs,
        total_words=baseline.total.words,
        dialogue_ratio=dialogue.total.dialogue_ratio,
        narration_ratio=dialogue.total.narration_ratio,
        event_cue_candidates=pacing.candidate_count,
        event_cue_density_per_1000=pacing.candidates_per_1000_characters,
        cliffhanger_candidate_episodes=cliff.possible_cliffhanger_count,
        average_sentence_characters=style.total.sentence_length.mean,
        lexical_diversity=style.total.type_token_ratio,
        emotion_balance=emotion.overall_emotion_balance,
        episodes=tuple(episodes),
    )
    validate_profile(result)
    return result


def render_reference_profile(profile: ReferenceProfile, *, episode_limit: int = 30) -> str:
    """Human-readable report made exclusively of stored numbers/fixed labels."""
    validate_profile(profile)
    if type(episode_limit) is not int or not 0 <= episode_limit <= 10000:
        raise ReferenceParseError("표시할 회차 수가 올바르지 않습니다.")
    lines = [
        "참고작 분석 프로필 (규칙 기반 참고 지표)",
        f"형식: {profile.source_format} | 회차: {profile.episode_count}",
        f"본문 공백 제외 글자: {profile.total_characters:,} | 문단: {profile.total_paragraphs:,} | 단어: {profile.total_words:,}",
        f"대사 비율: {profile.dialogue_ratio:.1%} | 서술 비율: {profile.narration_ratio:.1%}",
        f"사건 단서 후보: {profile.event_cue_candidates} | 1,000자당 {profile.event_cue_density_per_1000:.2f}",
        f"말미 연결 단서 회차: {profile.cliffhanger_candidate_episodes}/{profile.episode_count}",
        f"평균 문장 길이: {profile.average_sentence_characters:.2f} | 어휘 다양도: {profile.lexical_diversity:.4f}",
        f"감정 어휘 균형: {profile.emotion_balance:+.4f} (-1~+1, 의미 분석 아님)",
        "--- 회차별 ---",
    ]
    for episode in profile.episodes[:episode_limit]:
        lines.append(
            f"{episode.number}화 | {episode.characters:,}자 | 대사 {episode.dialogue_ratio:.1%}"
            f" | 사건 단서 {episode.event_cue_candidates}"
            f" | 말미 단서 {episode.cliffhanger_type}"
            f" | 감정 균형 {episode.emotion_balance:+.3f}"
        )
    if episode_limit < len(profile.episodes):
        lines.append(f"... 나머지 {len(profile.episodes) - episode_limit}개 회차는 생략")
    lines.append("주의: 인물·사건·감정의 의미를 AI가 판단한 결과가 아닌 통계적 단서입니다.")
    return "\n".join(lines)
