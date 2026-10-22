"""Stage 78 / ANF-REQ-030: local, review-only reference similarity check.

Combines the stage-38/39 direct and paragraph gates with bounded sentence,
scene and *manually annotated abstract beat* comparisons. Never stores source
text, approves a manuscript, or makes copyright/plagiarism determinations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import re
from typing import TYPE_CHECKING

from .references.copy_protection import MAX_REFERENCES, _normalize
from .references.similarity_baseline import (
    SimilarityCheckError, analyze_similarity_baseline, _shingles,
)
from .repetition_checker import _sentences
from .database.novel_bible import NovelBibleError, _id

if TYPE_CHECKING:
    from .database.reference_catalog import ReferenceCatalog

_ID = re.compile(r'[0-9a-f]{32}\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')
BEATS = frozenset({'setup', 'inciting', 'escalation', 'setback', 'reversal',
                   'climax', 'resolution', 'hook', 'transition'})
MAX_SENTENCE_UNITS = 500
MIN_SENTENCE_UNITS = 16
MAX_SENTENCES_DRAFT = 2000
MAX_SENTENCES_REFERENCE = 4000
MAX_SENTENCE_POSTINGS = 300_000
MAX_SCENES_DRAFT = 100
MAX_SCENES_REFERENCE = 300
MAX_EVIDENCE = 40
MIN_SCENE_UNITS = 24
SENTENCE_JACCARD = 0.62
SCENE_JACCARD = 0.70
STRUCTURE_RATIO = 0.90


class ReferenceSimilarityError(ValueError):
    """Generic error without manuscript excerpts, paths or reference names."""


@dataclass(frozen=True)
class TextSpan:
    start: int
    end: int


@dataclass(frozen=True)
class ReferenceMaterial:
    reference_id: str
    source_sha256: str
    text: str = field(repr=False)
    scenes: tuple[TextSpan, ...] = ()
    beats: tuple[str, ...] = ()


@dataclass(frozen=True)
class SimilarityEvidence:
    channel: str  # SENTENCE / SCENE / STRUCTURE
    reference_number: int
    draft_start: int | None
    draft_end: int | None
    reference_start: int | None
    reference_end: int | None
    score: float


@dataclass(frozen=True)
class ReferenceSimilarityReport:
    project_id: str
    episode_number: int
    draft_sha256: str
    reference_ids: tuple[str, ...]
    reference_text_sha256: tuple[str, ...]
    status: str  # blocked/review/inconclusive/clear
    direct_status: str
    paragraph_status: str
    sentence_matches: int
    scene_matches: int
    structure_matches: int
    evidence: tuple[SimilarityEvidence, ...]
    unexamined: tuple[str, ...]
    registration_checked: bool
    status_detail: str = 'HUMAN_REVIEW_REQUIRED_NOT_COPYRIGHT_VERDICT'
    persisted: bool = False
    manuscript_approved: bool = False
    publication_approved: bool = False

    @property
    def passed_checked_scope(self) -> bool:
        return self.status == 'clear' and not self.unexamined


def _digest(value: str) -> str:
    try:
        return sha256(value.encode('utf-8')).hexdigest()
    except UnicodeError:
        raise ReferenceSimilarityError('invalid text encoding') from None


def _valid_text(value: object) -> str:
    if (type(value) is not str or not value.strip()
            or any((ord(c) < 32 and c not in '\n\r\t') or ord(c) == 127 for c in value)):
        raise ReferenceSimilarityError('invalid text')
    _digest(value)
    return value


def _validate_spans(text: str, spans: object, maximum: int) -> tuple[TextSpan, ...]:
    if type(spans) is not tuple or len(spans) > maximum:
        raise ReferenceSimilarityError('invalid scene spans')
    cursor = 0
    for span in spans:
        if (type(span) is not TextSpan or type(span.start) is not int
                or type(span.end) is not int or not cursor <= span.start < span.end <= len(text)
                or text[cursor:span.start].strip() or not text[span.start:span.end].strip()):
            raise ReferenceSimilarityError('invalid scene spans')
        cursor = span.end
    if spans and text[cursor:].strip():
        raise ReferenceSimilarityError('incomplete scene coverage')
    return spans


def _validate_beats(beats: object) -> tuple[str, ...]:
    if (type(beats) is not tuple or len(beats) > 100
            or any(type(beat) is not str or beat not in BEATS for beat in beats)):
        raise ReferenceSimilarityError('invalid abstract structure')
    return beats


def _validate_inputs(project_id: object, episode_number: object, manuscript: object,
                     draft_scenes: object, draft_beats: object, references: object,
                     required_reference_ids: object, catalog: object):
    try:
        if type(project_id) is not str:
            raise NovelBibleError('invalid')
        project_id = _id(project_id)
    except NovelBibleError:
        raise ReferenceSimilarityError('invalid project') from None
    if type(episode_number) is not int or not 1 <= episode_number <= 1_000_000:
        raise ReferenceSimilarityError('invalid episode')
    manuscript = _valid_text(manuscript)
    draft_scenes = _validate_spans(manuscript, draft_scenes, MAX_SCENES_DRAFT)
    draft_beats = _validate_beats(draft_beats)
    if type(references) is not tuple or not 1 <= len(references) <= MAX_REFERENCES:
        raise ReferenceSimilarityError('invalid references')
    seen: set[str] = set()
    for ref in references:
        if (type(ref) is not ReferenceMaterial or type(ref.reference_id) is not str
                or not _ID.fullmatch(ref.reference_id) or ref.reference_id in seen
                or type(ref.source_sha256) is not str or not _SHA.fullmatch(ref.source_sha256)):
            raise ReferenceSimilarityError('invalid reference identity')
        _valid_text(ref.text)
        _validate_spans(ref.text, ref.scenes, MAX_SCENES_REFERENCE)
        _validate_beats(ref.beats)
        seen.add(ref.reference_id)
    if required_reference_ids is not None:
        if (type(required_reference_ids) is not tuple or not required_reference_ids
                or len(required_reference_ids) > MAX_REFERENCES or
                any(type(i) is not str or not _ID.fullmatch(i) for i in required_reference_ids)
                or len(set(required_reference_ids)) != len(required_reference_ids)
                or set(required_reference_ids) != seen):
            raise ReferenceSimilarityError('reference set does not match project selection')
    if catalog is not None:
        from .database.reference_catalog import ReferenceCatalog, CatalogError
        if type(catalog) is not ReferenceCatalog:
            raise ReferenceSimilarityError('invalid reference catalog')
        try:
            for ref in references:
                record = catalog.get(ref.reference_id)
                if record.status != 'analyzed' or record.sha256 != ref.source_sha256:
                    raise ReferenceSimilarityError('reference metadata mismatch')
        except (CatalogError, KeyError):
            raise ReferenceSimilarityError('reference metadata unavailable') from None
    return project_id, episode_number, manuscript, draft_scenes, draft_beats


def _sentence_matches(manuscript: str, references: tuple[ReferenceMaterial, ...],
                      unexamined: set[str], add_evidence) -> int:
    draft = []
    for start, end, sentence in _sentences(manuscript):
        norm = _normalize(sentence)
        if len(norm) > MAX_SENTENCE_UNITS:
            unexamined.add('long_sentences_not_compared')
        elif len(norm) >= MIN_SENTENCE_UNITS:
            draft.append((start, end, norm))
    source_groups = []
    for number, ref in enumerate(references, 1):
        group = []
        for start, end, sentence in _sentences(ref.text):
            norm = _normalize(sentence)
            if len(norm) > MAX_SENTENCE_UNITS:
                unexamined.add('long_sentences_not_compared')
            elif len(norm) >= MIN_SENTENCE_UNITS:
                group.append((number, start, end, norm))
        if not group:
            unexamined.add('reference_sentence_coverage_insufficient')
        source_groups.append(group)
    # Preserve input order within each source while sharing a limited budget
    # across ALL selected references, not just the earliest files.
    from itertools import zip_longest
    sources = [sentence for round_items in zip_longest(*source_groups)
               for sentence in round_items if sentence is not None]
    if not draft or not sources:
        unexamined.add('sentence_comparison_insufficient')
        return 0
    if len(draft) > MAX_SENTENCES_DRAFT or len(sources) > MAX_SENTENCES_REFERENCE:
        unexamined.add('sentence_count_budget_exceeded')
        draft = draft[:MAX_SENTENCES_DRAFT]
        sources = sources[:MAX_SENTENCES_REFERENCE]
    # Five-character shingles are a conservative lexical candidate filter.
    # This is not an exhaustive paraphrase/semantic similarity search.
    index: dict[str, list[int]] = {}
    source_sets = []
    for index_no, (_, _, _, norm) in enumerate(sources):
        grams = _shingles(norm)
        source_sets.append(grams)
        for gram in grams:
            index.setdefault(gram, []).append(index_no)
    postings = 0
    count = 0
    for start, end, norm in draft:
        grams = _shingles(norm)
        overlaps: dict[int, int] = {}
        for gram in grams:
            found = index.get(gram, ())
            postings += len(found)
            if postings > MAX_SENTENCE_POSTINGS:
                unexamined.add('sentence_posting_budget_exceeded')
                return count
            for position in found:
                overlaps[position] = overlaps.get(position, 0) + 1
        best = None
        for position, shared in overlaps.items():
            source_grams = source_sets[position]
            jaccard = shared / (len(grams) + len(source_grams) - shared)
            containment = shared / len(grams)
            if jaccard >= SENTENCE_JACCARD or (containment >= 0.88 and jaccard >= 0.45):
                if best is None or jaccard > best[0]:
                    best = jaccard, position
        if best is not None:
            score, position = best
            number, ref_start, ref_end, _ = sources[position]
            count += 1
            add_evidence('SENTENCE', number, start, end, ref_start, ref_end, score)
    return count


def _scene_matches(manuscript: str, draft_scenes: tuple[TextSpan, ...],
                   references: tuple[ReferenceMaterial, ...], unexamined: set[str],
                   add_evidence) -> int:
    if not draft_scenes:
        unexamined.add('scene_annotations_missing')
        return 0
    # Missing annotations in ONE reference must not erase matching evidence
    # from other references. The missing coverage still fails closed.
    if any(not ref.scenes for ref in references):
        unexamined.add('scene_annotations_missing')
    sources = []
    for number, ref in enumerate(references, 1):
        for scene in ref.scenes:
            norm = _normalize(ref.text[scene.start:scene.end])
            if len(norm) >= MIN_SCENE_UNITS:
                sources.append((number, scene, _shingles(norm)))
            else:
                unexamined.add('short_reference_scenes_not_compared')
    if not sources:
        unexamined.add('scene_comparison_insufficient')
        return 0
    count = 0
    checked = 0
    for scene in draft_scenes:
        norm = _normalize(manuscript[scene.start:scene.end])
        if len(norm) < MIN_SCENE_UNITS:
            unexamined.add('short_scenes_not_compared')
            continue
        checked += 1
        grams = _shingles(norm)
        best = None
        for number, source_span, source_grams in sources:
            shared = len(grams & source_grams)
            if not shared:
                continue
            jaccard = shared / (len(grams) + len(source_grams) - shared)
            containment = shared / len(grams)
            if jaccard >= SCENE_JACCARD or (containment >= 0.80 and jaccard >= 0.40):
                if best is None or jaccard > best[0]:
                    best = jaccard, number, source_span
        if best:
            score, number, source_span = best
            count += 1
            add_evidence('SCENE', number, scene.start, scene.end,
                         source_span.start, source_span.end, score)
    if not checked:
        unexamined.add('scene_comparison_insufficient')
    return count


def _structure_matches(draft_beats: tuple[str, ...],
                       references: tuple[ReferenceMaterial, ...],
                       unexamined: set[str], add_evidence) -> int:
    from difflib import SequenceMatcher
    if len(draft_beats) < 4:
        unexamined.add('structure_annotations_missing')
        return 0
    # Evaluate available, manually annotated references independently;
    # a different reference without beats must never suppress a match.
    if any(len(ref.beats) < 4 for ref in references):
        unexamined.add('structure_annotations_missing')
    count = 0
    for number, ref in enumerate(references, 1):
        if len(ref.beats) < 4:
            continue
        ratio = SequenceMatcher(None, draft_beats, ref.beats, autojunk=False).ratio()
        if ratio >= STRUCTURE_RATIO:
            count += 1
            add_evidence('STRUCTURE', number, None, None, None, None, ratio)
    return count


def check_reference_similarity(
    project_id: str, episode_number: int, manuscript: str, *,
    references: tuple[ReferenceMaterial, ...],
    draft_scenes: tuple[TextSpan, ...] = (),
    draft_beats: tuple[str, ...] = (),
    required_reference_ids: tuple[str, ...] | None = None,
    catalog: ReferenceCatalog | None = None,
) -> ReferenceSimilarityReport:
    """Review transient supplied reference text; fail closed for missing coverage.

    `required_reference_ids` is caller's selected-reference set, NOT a verified
    project-reference mapping. Catalog checks IDs/status/file hashes, but does
    not prove that the caller's extracted text came from those original bytes.
    """
    project_id, episode_number, manuscript, draft_scenes, draft_beats = _validate_inputs(
        project_id, episode_number, manuscript, draft_scenes, draft_beats,
        references, required_reference_ids, catalog,
    )
    try:
        baseline = analyze_similarity_baseline(manuscript, tuple(ref.text for ref in references))
    except SimilarityCheckError:
        raise ReferenceSimilarityError('baseline comparison unavailable') from None
    unexamined: set[str] = set()
    registration_checked = catalog is not None and required_reference_ids is not None
    if not registration_checked:
        unexamined.add('reference_registration_not_verified')
    evidence: list[SimilarityEvidence] = []

    def add_evidence(channel, number, start, end, ref_start, ref_end, score):
        if len(evidence) >= MAX_EVIDENCE:
            unexamined.add('evidence_limit_exceeded')
            return
        evidence.append(SimilarityEvidence(channel, number, start, end,
                                           ref_start, ref_end, round(score, 4)))

    sentence_matches = _sentence_matches(manuscript, references, unexamined, add_evidence)
    scene_matches = _scene_matches(manuscript, draft_scenes, references, unexamined, add_evidence)
    structure_matches = _structure_matches(draft_beats, references, unexamined, add_evidence)
    if baseline.status == 'blocked':
        status = 'blocked'
    elif baseline.status == 'review' or sentence_matches or scene_matches or structure_matches:
        status = 'review'
    elif baseline.status == 'inconclusive' or unexamined:
        status = 'inconclusive'
    else:
        status = 'clear'
    return ReferenceSimilarityReport(
        project_id, episode_number, _digest(manuscript),
        tuple(ref.reference_id for ref in references),
        tuple(_digest(ref.text) for ref in references),
        status, baseline.exact_overlap_status, baseline.status,
        sentence_matches, scene_matches, structure_matches,
        tuple(evidence), tuple(sorted(unexamined)), registration_checked,
    )


def check_episode_reference_similarity(
    preview: object, *, references: tuple[ReferenceMaterial, ...],
    draft_beats: tuple[str, ...] = (),
    required_reference_ids: tuple[str, ...] | None = None,
    catalog: ReferenceCatalog | None = None,
) -> ReferenceSimilarityReport:
    """Verify stage-65 unapproved episode provenance, then review similarities."""
    from .episode_assembler import EpisodeDraftPreview, SceneSpan, SCENE_SEPARATOR
    if (type(preview) is not EpisodeDraftPreview or
            preview.status != 'DRAFT_REQUIRES_USER_APPROVAL' or
            preview.persisted is not False or preview.publication_approved is not False or
            type(preview.draft) is not str or _digest(preview.draft) != preview.draft_sha256 or
            type(preview.scenes) is not tuple or not preview.scenes):
        raise ReferenceSimilarityError('invalid episode draft')
    cursor = 0
    spans = []
    for index, scene in enumerate(preview.scenes):
        if (type(scene) is not SceneSpan or type(scene.start) is not int
                or type(scene.end) is not int or scene.start != cursor or
                not 0 <= scene.start < scene.end <= len(preview.draft) or
                _digest(preview.draft[scene.start:scene.end]) != scene.draft_sha256):
            raise ReferenceSimilarityError('invalid scene provenance')
        spans.append(TextSpan(scene.start, scene.end))
        cursor = scene.end
        if index < len(preview.scenes) - 1:
            if preview.draft[cursor:cursor + len(SCENE_SEPARATOR)] != SCENE_SEPARATOR:
                raise ReferenceSimilarityError('invalid scene separator')
            cursor += len(SCENE_SEPARATOR)
    if cursor != len(preview.draft):
        raise ReferenceSimilarityError('incomplete scene provenance')
    return check_reference_similarity(
        preview.project_id, preview.episode_number, preview.draft,
        references=references, draft_scenes=tuple(spans), draft_beats=draft_beats,
        required_reference_ids=required_reference_ids, catalog=catalog,
    )


def require_reference_similarity_clear(*args, **kwargs) -> ReferenceSimilarityReport:
    """Re-run the actual comparison; never accept a caller-forged report.

    A clear result permits only *this similarity gate* to proceed. This is NOT
    manuscript finalization, user approval, legal clearance, or publication.
    """
    report = check_reference_similarity(*args, **kwargs)
    if not report.passed_checked_scope or not report.registration_checked:
        raise ReferenceSimilarityError('reference similarity review required')
    return report