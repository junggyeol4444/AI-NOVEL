"""Stage 26: privacy-preserving, deterministic character-role *candidates*.

Names must be supplied by the caller; this is NOT named-entity discovery or
semantic character understanding. Korean particle-aware mentions, episode
coverage, prominence, and narrowly explicit role phrases are measured locally.
Outputs contain opaque character IDs and aggregate counts, never source names.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import re
import unicodedata
from typing import Sequence

from .basic_statistics import measure_reference
from .episode_splitter import SplitEpisodes, split_episodes
from .episode_structure import _body_paragraphs, _paragraphs
from .plaintext_parser import ParsedReference, ReferenceParseError

MAX_CHARACTERS = 64
MAX_ALIASES_PER_CHARACTER = 8
MAX_MENTIONS = 20000
MAX_ANALYZED_CHARACTERS = 2_000_000
_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,47}$")
# A very small, explicit dictionary. These words are not proof of the role.
_ROLE_WORDS: dict[str, tuple[str, ...]] = {
    "protagonist": ("주인공", "주역"),
    "antagonist": ("악역", "적대자", "빌런"),
    "mentor": ("스승", "멘토"),
    "ally": ("조력자", "동료"),
    "rival": ("경쟁자", "라이벌", "숙적"),
}
_ROLE_RE = "(?:" + "|".join(re.escape(w) for ws in _ROLE_WORDS.values() for w in ws) + ")"
_BEFORE_ROLE = re.compile(r"(?<!\w)(" + _ROLE_RE + r")\s+$")
_AFTER_ROLE = re.compile(
    r"^(?:은|는|이|가)?\s*(" + _ROLE_RE +
    r")(?:이었(?:다|습니다)?|였다|이다|입니다)?(?=$|[\s.!?。！？,，])"
)
_WORD_TO_ROLE = {word: role for role, words in _ROLE_WORDS.items() for word in words}
# Length-descending suffixes, supporting the most common attached particles.
_PARTICLE = ("에게서", "으로", "부터", "까지", "에게", "한테", "께서", "에서", "처럼",
             "보다", "하고", "은", "는", "이", "가", "을", "를", "의", "와", "과",
             "도", "만", "로", "랑", "께")
_PARTICLE_RE = "(?:" + "|".join(_PARTICLE) + ")?"


@dataclass(frozen=True)
class CharacterSpec:
    """Transient alias input; never serialize/log this object or its names."""
    character_id: str
    aliases: tuple[str, ...] = field(repr=False)


@dataclass(frozen=True)
class CharacterRoleCandidate:
    character_id: str
    mentions: int
    mention_share: float
    episodes_present: int
    episode_coverage: float
    prominence: str  # central_candidate, recurring_candidate, minor_candidate, not_detected
    explicit_role_hints: tuple[tuple[str, int], ...]  # fixed vocabulary only


@dataclass(frozen=True)
class EpisodeCharacterRoles:
    number: int
    total_mentions: int
    mentions: tuple[tuple[str, int], ...]  # (opaque id, count)
    explicit_role_hints: tuple[tuple[str, str, int], ...]  # id, fixed role, count


@dataclass(frozen=True)
class ReferenceCharacterRoles:
    format: str
    episode_count: int
    total_mentions: int
    characters: tuple[CharacterRoleCandidate, ...]
    episodes: tuple[EpisodeCharacterRoles, ...]


def _validated_specs(specs: Sequence[CharacterSpec]) -> tuple[tuple[str, tuple[re.Pattern[str], ...]], ...]:
    if not isinstance(specs, (list, tuple)) or not 1 <= len(specs) <= MAX_CHARACTERS:
        raise ReferenceParseError("분석 대상 인물 목록이 올바르지 않습니다.")
    compiled = []
    seen_ids: set[str] = set()
    seen_aliases: set[str] = set()
    for spec in specs:
        if not isinstance(spec, CharacterSpec) or not isinstance(spec.character_id, str) or not _ID.fullmatch(spec.character_id):
            raise ReferenceParseError("인물 식별자가 올바르지 않습니다.")
        if spec.character_id in seen_ids:
            raise ReferenceParseError("인물 식별자가 중복되었습니다.")
        seen_ids.add(spec.character_id)
        if not isinstance(spec.aliases, tuple) or not 1 <= len(spec.aliases) <= MAX_ALIASES_PER_CHARACTER:
            raise ReferenceParseError("인물 별칭 목록이 올바르지 않습니다.")
        patterns = []
        for alias in spec.aliases:
            if (not isinstance(alias, str) or not 1 <= len(alias) <= 40
                    or alias != alias.strip() or not any(ch.isalpha() for ch in alias)
                    or any(ch in "\r\n\t\x00" for ch in alias)):
                raise ReferenceParseError("인물 별칭이 올바르지 않습니다.")
            alias = unicodedata.normalize("NFC", alias)
            norm = alias.casefold()
            if norm in seen_aliases:
                raise ReferenceParseError("다른 인물과 중복되는 별칭이 있습니다.")
            seen_aliases.add(norm)
            # An attached Korean particle is permitted, but arbitrary adjoining
            # Hangul is not: '하린은' matches '하린', '하린별' does not.
            suffix = _PARTICLE_RE
            patterns.append(re.compile(r"(?<!\w)" + re.escape(alias) + r"(?=" + suffix + r"(?!\w))", re.IGNORECASE))
        compiled.append((spec.character_id, tuple(patterns)))
        if sum(len(row[1]) for row in compiled) > 128:
            raise ReferenceParseError("인물 별칭의 총수가 제한을 초과했습니다.")
    return tuple(compiled)


def _validate_budget(max_mentions: int) -> None:
    if type(max_mentions) is not int or not 1 <= max_mentions <= MAX_MENTIONS:
        raise ReferenceParseError("인물 언급 제한값이 올바르지 않습니다.")


def _role_hint(text: str, start: int, end: int) -> str | None:
    """Require nearby *explicit naming* grammar, not mere co-occurrence."""
    prefix = _BEFORE_ROLE.search(text[max(0, start - 32):start])
    if prefix:
        return _WORD_TO_ROLE[prefix.group(1)]
    suffix = _AFTER_ROLE.match(text[end:end + 32])
    return _WORD_TO_ROLE[suffix.group(1)] if suffix else None


def _one_episode(
    paragraphs: list[str], number: int,
    compiled: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...],
    remaining: int,
) -> EpisodeCharacterRoles:
    counts: Counter[str] = Counter()
    roles: Counter[tuple[str, str]] = Counter()
    total = 0
    for paragraph in paragraphs:
        # Resolve competing aliases by the longest matching span, then
        # deterministic character/alias declaration order. No double counting.
        hits: list[tuple[int, int, int, int, str]] = []
        for index, (character_id, patterns) in enumerate(compiled):
            for alias_index, pattern in enumerate(patterns):
                for match in pattern.finditer(paragraph):
                    hits.append((match.start(), match.end(), index, alias_index, character_id))
        hits.sort(key=lambda h: (h[0], -(h[1] - h[0]), h[2], h[3]))
        blocked_until = 0
        for start, end, _, _, character_id in hits:
            if start < blocked_until:
                continue
            blocked_until = end
            total += 1
            if total > remaining:
                raise ReferenceParseError("인물 언급 수가 제한을 초과했습니다.")
            counts[character_id] += 1
            role = _role_hint(paragraph, start, end)
            if role:
                roles[(character_id, role)] += 1
    return EpisodeCharacterRoles(
        number=number,
        total_mentions=total,
        mentions=tuple((character_id, counts[character_id]) for character_id, _ in compiled),
        explicit_role_hints=tuple((character_id, role, n) for (character_id, role), n in sorted(roles.items())),
    )


def _result(format_name: str, episodes: list[EpisodeCharacterRoles], compiled: tuple) -> ReferenceCharacterRoles:
    total = sum(ep.total_mentions for ep in episodes)
    scores: list[CharacterRoleCandidate] = []
    for character_id, _ in compiled:
        mentions = sum(dict(ep.mentions)[character_id] for ep in episodes)
        episode_count = sum(dict(ep.mentions)[character_id] > 0 for ep in episodes)
        coverage = round(episode_count / len(episodes), 4)
        share = round(mentions / total, 4) if total else 0.0
        if not mentions:
            prominence = "not_detected"
        elif mentions >= 2 and share >= 0.3 and coverage >= 0.5:
            prominence = "central_candidate"
        elif episode_count >= 2:
            prominence = "recurring_candidate"
        else:
            prominence = "minor_candidate"
        role_counts: Counter[str] = Counter()
        for ep in episodes:
            for e_id, role, count in ep.explicit_role_hints:
                if e_id == character_id:
                    role_counts[role] += count
        scores.append(CharacterRoleCandidate(
            character_id, mentions, share, episode_count, coverage, prominence,
            tuple((role, role_counts[role]) for role in _ROLE_WORDS if role_counts[role]),
        ))
    return ReferenceCharacterRoles(format_name, len(episodes), total, tuple(scores), tuple(episodes))


def analyze_character_text(
    text: str, characters: Sequence[CharacterSpec], *, number: int = 1,
    max_mentions: int = MAX_MENTIONS,
) -> EpisodeCharacterRoles:
    """Read-only one-episode analysis, including Korean topic particles."""
    if not isinstance(text, str) or len(text) > MAX_ANALYZED_CHARACTERS:
        raise ReferenceParseError("분석 본문이 올바르지 않거나 너무 깁니다.")
    if type(number) is not int or not 1 <= number <= 10000:
        raise ReferenceParseError("회차 번호가 올바르지 않습니다.")
    _validate_budget(max_mentions)
    compiled = _validated_specs(characters)
    return _one_episode(_paragraphs(text), number, compiled, max_mentions)


def analyze_reference_character_roles(
    document: ParsedReference, characters: Sequence[CharacterSpec], *,
    split: SplitEpisodes | None = None, max_mentions: int = MAX_MENTIONS,
) -> ReferenceCharacterRoles:
    """Report only counts and fixed labels; discard source, alias and evidence.

    Exclude preface, headings and fenced code. Check split identity through
    the existing stage-18 reference statistics; no DB/API/model is involved.
    """
    if not isinstance(document, ParsedReference):
        raise ReferenceParseError("인물 분석 대상 문서가 올바르지 않습니다.")
    _validate_budget(max_mentions)
    compiled = _validated_specs(characters)
    if split is None:
        split = split_episodes(document)
    baseline = measure_reference(document, split=split)
    if baseline.total.characters > MAX_ANALYZED_CHARACTERS:
        raise ReferenceParseError("인물 분석 본문이 너무 깁니다.")
    episodes = []
    remaining = max_mentions
    for ep in split.episodes:
        first = ep.start_block + int(split.detected_markers)
        paragraphs = _body_paragraphs(document.blocks[first:ep.end_block + 1])
        measured = _one_episode(paragraphs, ep.number, compiled, remaining)
        episodes.append(measured)
        remaining -= measured.total_mentions
    return _result(document.format, episodes, compiled)
