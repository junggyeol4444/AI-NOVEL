"""Stage 27: local, privacy-minimal co-mention and relationship *cue* changes.

This is a deterministic signal estimator, NOT a character-relationship judge:
text in the same sentence does not prove interaction, and nearby positive or
negative words do not prove a relationship. No name, alias, source snippet, or
path is included in results or sent to a network service.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import combinations
import re
from typing import Sequence

from .basic_statistics import measure_reference
from .character_roles import (
    CharacterSpec, MAX_ANALYZED_CHARACTERS, _validated_specs,
)
from .episode_splitter import SplitEpisodes, split_episodes
from .episode_structure import _body_paragraphs, _paragraphs
from .plaintext_parser import ParsedReference, ReferenceParseError

MAX_PAIR_OBSERVATIONS = 20_000
MAX_PAIR_DISTANCE = 240  # character positions within one sentence, not semantics

# Fixed observable Korean cues: they are not classified *events*.
_POSITIVE = re.compile(r"도와|도왔|도움|구해|구했|협력|믿었|믿는다|화해|감사|지켜줬|지켜주")
_NEGATIVE = re.compile(r"공격|배신|위협|다투|다퉜|싸웠|싸우|증오|미워|적대|의심|갈등")
# A punctuation-ended sentence; closing quotation marks remain in that sentence.
_SENTENCE_END = re.compile(r"[.!?。！？]+[\"'”’」』)]*(?=\s|$)")


@dataclass(frozen=True)
class PairEvidence:
    """Evidence counts only, with caller-provided non-sensitive IDs."""
    character_ids: tuple[str, str]
    joint_sentences: int
    positive_cues: int
    negative_cues: int
    neutral_cues: int
    cue_balance: float  # (positive - negative) / joint_sentences; not sentiment


@dataclass(frozen=True)
class EpisodeRelationships:
    number: int
    joint_sentence_observations: int
    pairs: tuple[PairEvidence, ...]


@dataclass(frozen=True)
class PairSummary:
    character_ids: tuple[str, str]
    joint_sentences: int
    episodes_present: int
    first_episode: int
    last_episode: int
    positive_cues: int
    negative_cues: int


@dataclass(frozen=True)
class RelationshipChange:
    character_ids: tuple[str, str]
    from_episode: int
    to_episode: int
    previous_joint_sentences: int
    current_joint_sentences: int
    previous_cue_balance: float
    current_cue_balance: float
    signal: str  # first_joint_mention / stopped_joint_mention / more_* / unchanged


@dataclass(frozen=True)
class ReferenceRelationships:
    format: str
    episode_count: int
    total_joint_sentence_observations: int
    episodes: tuple[EpisodeRelationships, ...]
    pairs: tuple[PairSummary, ...]
    adjacent_changes: tuple[RelationshipChange, ...]


def _validate_limit(limit: int) -> None:
    if type(limit) is not int or not 1 <= limit <= MAX_PAIR_OBSERVATIONS:
        raise ReferenceParseError("관계 단서 관측 개수 제한이 올바르지 않습니다.")


def _sentences(paragraphs: list[str]):
    for paragraph in paragraphs:
        for line in paragraph.splitlines():
            start = 0
            for match in _SENTENCE_END.finditer(line):
                piece = line[start:match.end()].strip()
                if piece:
                    yield piece
                start = match.end()
            tail = line[start:].strip()
            if tail:
                yield tail


def _positions(sentence: str, compiled: tuple) -> dict[str, tuple[tuple[int, int], ...]]:
    """Resolve alias overlap exactly once, preferring the longest alias."""
    hits: list[tuple[int, int, int, int, str]] = []
    for index, (identity, patterns) in enumerate(compiled):
        for alias_index, pattern in enumerate(patterns):
            for match in pattern.finditer(sentence):
                hits.append((match.start(), match.end(), index, alias_index, identity))
    hits.sort(key=lambda hit: (hit[0], -(hit[1] - hit[0]), hit[2], hit[3]))
    positions: dict[str, list[tuple[int, int]]] = {}
    blocked_until = 0
    for start, end, _, _, identity in hits:
        if start < blocked_until:
            continue
        blocked_until = end
        positions.setdefault(identity, []).append((start, end))
    return {identity: tuple(spans) for identity, spans in positions.items()}


def _nearby(a: tuple[tuple[int, int], ...], b: tuple[tuple[int, int], ...]) -> bool:
    # Gap of 0 for touching spans; cannot match different sentences/paragraphs.
    return any(max(0, max(beg1, beg2) - min(end1, end2)) <= MAX_PAIR_DISTANCE
               for beg1, end1 in a for beg2, end2 in b)


def _as_evidence(pair: tuple[str, str], counters: list[int]) -> PairEvidence:
    joint, positive, negative, neutral = counters
    return PairEvidence(pair, joint, positive, negative, neutral,
                        round((positive - negative) / joint, 4) if joint else 0.0)


def _one_episode(paragraphs: list[str], number: int, compiled: tuple, budget: int) -> EpisodeRelationships:
    counts: dict[tuple[str, str], list[int]] = {}
    observations = 0
    for sentence in _sentences(paragraphs):
        found = _positions(sentence, compiled)
        if len(found) < 2:
            continue
        positive = bool(_POSITIVE.search(sentence))
        negative = bool(_NEGATIVE.search(sentence))
        # IDs are opaque and stable; pair order must not depend on mentions.
        for first, second in combinations(sorted(found), 2):
            if not _nearby(found[first], found[second]):
                continue
            observations += 1
            if observations > budget:
                raise ReferenceParseError("관계 단서 관측 수가 제한을 초과했습니다.")
            row = counts.setdefault((first, second), [0, 0, 0, 0])
            row[0] += 1
            row[1] += int(positive)
            row[2] += int(negative)
            row[3] += int(not positive and not negative)
    return EpisodeRelationships(number, observations,
                                tuple(_as_evidence(pair, counts[pair]) for pair in sorted(counts)))


def analyze_relationship_text(
    text: str, characters: Sequence[CharacterSpec], *, number: int = 1,
    max_observations: int = MAX_PAIR_OBSERVATIONS,
) -> EpisodeRelationships:
    """Analyze text in memory, never logging or persisting source content."""
    if not isinstance(text, str) or len(text) > MAX_ANALYZED_CHARACTERS:
        raise ReferenceParseError("관계 단서 분석 본문이 올바르지 않거나 너무 깁니다.")
    if type(number) is not int or not 1 <= number <= 10000:
        raise ReferenceParseError("회차 번호가 올바르지 않습니다.")
    _validate_limit(max_observations)
    compiled = _validated_specs(characters)
    return _one_episode(_paragraphs(text), number, compiled, max_observations)


def _summarize(episodes: list[EpisodeRelationships], format_name: str) -> ReferenceRelationships:
    pair_episodes: dict[tuple[str, str], list[tuple[int, PairEvidence]]] = {}
    for episode in episodes:
        for evidence in episode.pairs:
            pair_episodes.setdefault(evidence.character_ids, []).append((episode.number, evidence))
    summaries: list[PairSummary] = []
    for pair in sorted(pair_episodes):
        items = pair_episodes[pair]
        summaries.append(PairSummary(
            pair, sum(e.joint_sentences for _, e in items), len(items),
            items[0][0], items[-1][0],
            sum(e.positive_cues for _, e in items),
            sum(e.negative_cues for _, e in items),
        ))

    adjacent_changes: list[RelationshipChange] = []
    for before, after in zip(episodes, episodes[1:]):
        old_map = {p.character_ids: p for p in before.pairs}
        new_map = {p.character_ids: p for p in after.pairs}
        for pair in sorted(old_map.keys() | new_map.keys()):
            previous = old_map.get(pair)
            current = new_map.get(pair)
            if previous is None:
                signal = "first_joint_mention"
            elif current is None:
                signal = "stopped_joint_mention"
            elif current.cue_balance > previous.cue_balance:
                signal = "more_positive_cues"
            elif current.cue_balance < previous.cue_balance:
                signal = "more_negative_cues"
            else:
                signal = "unchanged_cue_balance"
            adjacent_changes.append(RelationshipChange(
                pair, before.number, after.number,
                previous.joint_sentences if previous else 0,
                current.joint_sentences if current else 0,
                previous.cue_balance if previous else 0.0,
                current.cue_balance if current else 0.0,
                signal,
            ))
    return ReferenceRelationships(
        format_name, len(episodes),
        sum(ep.joint_sentence_observations for ep in episodes),
        tuple(episodes), tuple(summaries), tuple(adjacent_changes),
    )


def analyze_reference_relationships(
    document: ParsedReference, characters: Sequence[CharacterSpec], *,
    split: SplitEpisodes | None = None,
    max_observations: int = MAX_PAIR_OBSERVATIONS,
) -> ReferenceRelationships:
    """Measure only episode bodies; skip preface, titles and fenced code.

    No inference of actual relationships or changes in intent is performed.
    """
    if not isinstance(document, ParsedReference):
        raise ReferenceParseError("관계 분석 대상 문서가 올바르지 않습니다.")
    _validate_limit(max_observations)
    compiled = _validated_specs(characters)
    if split is None:
        split = split_episodes(document)
    baseline = measure_reference(document, split=split)  # validates split boundaries
    if baseline.total.characters > MAX_ANALYZED_CHARACTERS:
        raise ReferenceParseError("관계 분석 본문이 너무 깁니다.")
    results: list[EpisodeRelationships] = []
    remaining = max_observations
    for episode in split.episodes:
        first = episode.start_block + int(split.detected_markers)
        paragraphs = _body_paragraphs(document.blocks[first:episode.end_block + 1])
        output = _one_episode(paragraphs, episode.number, compiled, remaining)
        results.append(output)
        remaining -= output.joint_sentence_observations
    return _summarize(results, document.format)
