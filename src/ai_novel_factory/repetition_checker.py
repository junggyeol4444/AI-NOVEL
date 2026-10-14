"""Stage 77 / ANF-REQ-054: deterministic offline repetition-frequency checks.

This is a *draft review aid*, not originality or prose-quality certification.
Findings expose only offsets and SHA-256 digests, never manuscript snippets.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from hashlib import sha256
import re
import unicodedata

from .database.novel_bible import NovelBibleError, _id

MAX_MANUSCRIPT_CHARS = 1_000_000
MAX_WATCHED_PHRASES = 100
MAX_FINDINGS = 1000
MAX_SPANS_PER_FINDING = 1000
MAX_AUTO_TOKENS = 60_000
MAX_FUZZY_SENTENCES = 3000
MAX_FUZZY_PAIRS = 5_000
MAX_FUZZY_SENTENCE_CHARS = 500
_SENTENCE = re.compile(r'[^.!?。！？\n]+(?:[.!?。！？]+|(?=\n|\Z))')
_WORD = re.compile(r'[^\W_]+', re.UNICODE)
_KEY = re.compile(r'[a-z][a-z0-9_]{0,63}\Z')


class RepetitionCheckerError(ValueError):
    """Deliberately redacted validation error."""


@dataclass(frozen=True)
class WatchedPhrase:
    key: str
    phrase: str
    allowed_occurrences: int = 3
    case_sensitive: bool = True


@dataclass(frozen=True)
class RepetitionPolicy:
    max_auto_phrase_occurrences: int = 3
    min_phrase_words: int = 2
    max_phrase_words: int = 3
    min_phrase_chars: int = 5
    min_sentence_chars: int = 10
    sentence_similarity_threshold: float = 0.88


@dataclass(frozen=True)
class RepetitionSpan:
    start: int
    end: int
    evidence_sha256: str


@dataclass(frozen=True)
class RepetitionFinding:
    code: str  # WATCHED_PHRASE_OVERUSED / REPEATED_PHRASE / REPEATED_SENTENCE / SIMILAR_SENTENCE
    pattern_sha256: str
    count: int
    allowed_occurrences: int
    spans: tuple[RepetitionSpan, ...]
    similarity: float | None = None
    watched_key: str | None = None


@dataclass(frozen=True)
class RepetitionReport:
    project_id: str
    episode_number: int
    manuscript_sha256: str
    sentence_count: int
    watched_phrases_checked: int
    findings: tuple[RepetitionFinding, ...]
    unexamined: tuple[str, ...]
    status: str = 'REQUIRES_HUMAN_REVIEW_NOT_FULL_QC'
    persisted: bool = False
    publication_approved: bool = False

    @property
    def passed_checked_scope(self) -> bool:
        return not self.findings and not self.unexamined


def _hash(text: str) -> str:
    try:
        return sha256(text.encode('utf-8')).hexdigest()
    except UnicodeError:
        raise RepetitionCheckerError('invalid unicode') from None


def _text(value: object) -> str:
    if (type(value) is not str or not value.strip() or len(value) > MAX_MANUSCRIPT_CHARS
            or any(ord(c) < 32 and c not in '\n\r\t' or ord(c) == 127 for c in value)):
        raise RepetitionCheckerError('invalid manuscript')
    _hash(value)
    return value


def _normalize(text: str) -> str:
    """Unicode compatibility + case + whitespace/punctuation-insensitive comparison."""
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())


def _validate_policy(policy: object) -> RepetitionPolicy:
    if type(policy) is not RepetitionPolicy:
        raise RepetitionCheckerError('invalid policy')
    for field, low, high in (
        ('max_auto_phrase_occurrences', 1, 1000), ('min_phrase_words', 2, 4),
        ('max_phrase_words', 2, 4), ('min_phrase_chars', 2, 200),
        ('min_sentence_chars', 8, 1000),
    ):
        value = getattr(policy, field)
        if type(value) is not int or not low <= value <= high:
            raise RepetitionCheckerError('invalid policy')
    if policy.min_phrase_words > policy.max_phrase_words:
        raise RepetitionCheckerError('invalid policy')
    threshold = policy.sentence_similarity_threshold
    if type(threshold) is not float or not 0.75 <= threshold <= 0.99:
        raise RepetitionCheckerError('invalid similarity threshold')
    return policy


def _validate_watched(phrases: object) -> tuple[WatchedPhrase, ...]:
    if type(phrases) is not tuple or len(phrases) > MAX_WATCHED_PHRASES:
        raise RepetitionCheckerError('invalid watched phrases')
    seen: set[str] = set()
    for phrase in phrases:
        if (type(phrase) is not WatchedPhrase or type(phrase.key) is not str
                or not _KEY.fullmatch(phrase.key) or phrase.key in seen
                or type(phrase.phrase) is not str or not phrase.phrase.strip()
                or len(phrase.phrase) > 200 or '\n' in phrase.phrase or '\r' in phrase.phrase
                or type(phrase.allowed_occurrences) is not int
                or not 0 <= phrase.allowed_occurrences <= 1000
                or type(phrase.case_sensitive) is not bool):
            raise RepetitionCheckerError('invalid watched phrase')
        _hash(phrase.phrase)
        seen.add(phrase.key)
    return phrases


def _sentences(text: str) -> list[tuple[int, int, str]]:
    out: list[tuple[int, int, str]] = []
    for match in _SENTENCE.finditer(text):
        segment = match.group()
        left = len(segment) - len(segment.lstrip())
        right = len(segment.rstrip())
        if right > left:
            start, end = match.start() + left, match.start() + right
            out.append((start, end, text[start:end]))
    return out


def check_repetition(
    project_id: str, episode_number: int, manuscript: str, *,
    watched_phrases: tuple[WatchedPhrase, ...] = (),
    policy: RepetitionPolicy = RepetitionPolicy(),
) -> RepetitionReport:
    """Report literal overuse, word n-grams, exact and near-duplicate sentences.

    Word n-grams never cross sentence boundaries. Similarity uses NFKC,
    case-folded alphanumeric codepoints and SequenceMatcher, with shared
    trigrams as a candidate filter. All caps are explicit in `unexamined`.
    """
    try:
        project_id = _id(project_id)
    except NovelBibleError:
        raise RepetitionCheckerError('invalid project') from None
    if type(episode_number) is not int or not 1 <= episode_number <= 1_000_000:
        raise RepetitionCheckerError('invalid episode')
    manuscript = _text(manuscript)
    watched_phrases = _validate_watched(watched_phrases)
    policy = _validate_policy(policy)
    findings: list[RepetitionFinding] = []
    unexamined: set[str] = set()

    def span(start: int, end: int) -> RepetitionSpan:
        return RepetitionSpan(start, end, _hash(manuscript[start:end]))

    def emit(code: str, pattern: str, occurrences: list[tuple[int, int]],
             allowed: int, *, watched_key: str | None = None,
             similarity: float | None = None, occurrence_count: int | None = None) -> None:
        if len(findings) >= MAX_FINDINGS:
            unexamined.add('finding_count_budget_exceeded')
            return
        count = len(occurrences) if occurrence_count is None else occurrence_count
        if count > MAX_SPANS_PER_FINDING:
            unexamined.add('occurrence_offsets_truncated')
        findings.append(RepetitionFinding(
            code, _hash(pattern), count, allowed,
            tuple(span(start, end) for start, end in occurrences[:MAX_SPANS_PER_FINDING]),
            similarity, watched_key,
        ))

    # Literal, non-overlapping watched phrases: explicit per-phrase limits.
    for watched in watched_phrases:
        haystack = manuscript if watched.case_sensitive else manuscript.casefold()
        needle = watched.phrase if watched.case_sensitive else watched.phrase.casefold()
        # Casefold can expand Unicode (e.g. ß), invalidating original offsets.
        # Require equal length for this mode; never return incorrect evidence.
        if len(haystack) != len(manuscript) or len(needle) != len(watched.phrase):
            raise RepetitionCheckerError('casefold changes character offsets')
        occurrences: list[tuple[int, int]] = []
        total_occurrences = 0
        cursor = 0
        while (at := haystack.find(needle, cursor)) != -1:
            total_occurrences += 1
            if len(occurrences) < MAX_SPANS_PER_FINDING:
                occurrences.append((at, at + len(watched.phrase)))
            cursor = at + len(needle)
        if total_occurrences > watched.allowed_occurrences:
            emit('WATCHED_PHRASE_OVERUSED', watched.phrase, occurrences,
                 watched.allowed_occurrences, watched_key=watched.key,
                 occurrence_count=total_occurrences)

    sentences = _sentences(manuscript)
    # Automatic repeated word phrases (bounded total token count).
    token_count = 0
    groups: dict[tuple[str, ...], list[tuple[int, int]]] = defaultdict(list)
    for start, _, sentence in sentences:
        words = [(unicodedata.normalize('NFKC', m.group()).casefold(),
                  start + m.start(), start + m.end()) for m in _WORD.finditer(sentence)]
        if token_count + len(words) > MAX_AUTO_TOKENS:
            unexamined.add('automatic_phrase_token_budget_exceeded')
            break
        token_count += len(words)
        for size in range(policy.min_phrase_words, policy.max_phrase_words + 1):
            for i in range(len(words) - size + 1):
                fragment = words[i:i + size]
                if fragment[-1][2] - fragment[0][1] < policy.min_phrase_chars:
                    continue
                groups[tuple(word for word, _, _ in fragment)].append(
                    (fragment[0][1], fragment[-1][2]))
    for key, occurrences in sorted(groups.items()):
        if len(occurrences) > policy.max_auto_phrase_occurrences:
            emit('REPEATED_PHRASE', ' '.join(key), occurrences,
                 policy.max_auto_phrase_occurrences)

    # Exact normalized repeated sentences, including distant occurrences.
    normalized_groups: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for start, end, sentence in sentences:
        norm = _normalize(sentence)
        if len(norm) >= policy.min_sentence_chars:
            normalized_groups[norm].append((start, end))
    for norm, occurrences in sorted(normalized_groups.items()):
        if len(occurrences) > 1:
            emit('REPEATED_SENTENCE', norm, occurrences, 1)

    # Near-duplicates among unique normalized sentences, not all O(n^2) pairs.
    # Each candidate must share a trigram; exhaustive candidate scanning is
    # bounded and partial coverage is explicitly recorded rather than 'pass'.
    unique = [(norm, occurrences[0]) for norm, occurrences in sorted(normalized_groups.items())]
    if len(unique) > MAX_FUZZY_SENTENCES:
        unexamined.add('fuzzy_sentence_count_budget_exceeded')
        unique = unique[:MAX_FUZZY_SENTENCES]
    index: dict[str, list[int]] = defaultdict(list)
    examined_pairs = 0
    stop = False
    for j, (norm, position) in enumerate(unique):
        if len(norm) > MAX_FUZZY_SENTENCE_CHARS:
            unexamined.add('fuzzy_sentence_length_budget_exceeded')
            continue
        grams = {norm[k:k + 3] for k in range(len(norm) - 2)}
        candidates: set[int] = set()
        for gram in grams:
            candidates.update(index.get(gram, ()))
        for i in sorted(candidates):
            other, other_position = unique[i]
            if abs(len(norm) - len(other)) > (1 - policy.sentence_similarity_threshold) * max(len(norm), len(other)):
                continue
            if examined_pairs >= MAX_FUZZY_PAIRS:
                unexamined.add('fuzzy_pair_budget_exceeded')
                stop = True
                break
            examined_pairs += 1
            ratio = SequenceMatcher(None, other, norm, autojunk=False).ratio()
            if ratio >= policy.sentence_similarity_threshold:
                emit('SIMILAR_SENTENCE', other + '\0' + norm,
                     [other_position, position], 1, similarity=round(ratio, 4))
        if stop:
            break
        for gram in grams:
            index[gram].append(j)
    return RepetitionReport(project_id, episode_number, _hash(manuscript),
                            len(sentences), len(watched_phrases), tuple(findings),
                            tuple(sorted(unexamined)))


def check_episode_repetition(
    preview: object, *, watched_phrases: tuple[WatchedPhrase, ...] = (),
    policy: RepetitionPolicy = RepetitionPolicy(),
) -> RepetitionReport:
    """Reject tampered/unapproved stage-65 episode previews before analysis."""
    from .episode_assembler import EpisodeDraftPreview, SceneSpan, SCENE_SEPARATOR
    if (type(preview) is not EpisodeDraftPreview or
            preview.status != 'DRAFT_REQUIRES_USER_APPROVAL' or
            preview.persisted is not False or preview.publication_approved is not False or
            type(preview.draft) is not str or _hash(preview.draft) != preview.draft_sha256 or
            type(preview.scenes) is not tuple or not preview.scenes):
        raise RepetitionCheckerError('invalid episode draft')
    cursor = 0
    for index, scene in enumerate(preview.scenes):
        if (type(scene) is not SceneSpan or type(scene.start) is not int or
                type(scene.end) is not int or scene.start != cursor or
                not 0 <= scene.start < scene.end <= len(preview.draft) or
                _hash(preview.draft[scene.start:scene.end]) != scene.draft_sha256):
            raise RepetitionCheckerError('invalid scene provenance')
        cursor = scene.end
        if index < len(preview.scenes) - 1:
            if preview.draft[cursor:cursor + len(SCENE_SEPARATOR)] != SCENE_SEPARATOR:
                raise RepetitionCheckerError('invalid scene separator')
            cursor += len(SCENE_SEPARATOR)
    if cursor != len(preview.draft):
        raise RepetitionCheckerError('incomplete scene provenance')
    return check_repetition(preview.project_id, preview.episode_number, preview.draft,
                            watched_phrases=watched_phrases, policy=policy)
