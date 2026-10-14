"""Stage 80 / ANF-REQ-056: offline selective Scene replacement and rechecking.

The replacement is explicitly supplied by a reviewer or by an already-created,
validated stage-64 preview. No model invocation, IO, approval, or publication.
Reports contain hashes/offsets only; only the transient preview contains prose.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import re

from .episode_assembler import EpisodeDraftPreview, SceneSpan, SCENE_SEPARATOR, MAX_EPISODE_DRAFT_CHARS
from .scene_writer import SceneDraftPreview
from .local_models import SceneDraftResult
from .repetition_checker import (
    check_repetition, RepetitionPolicy, WatchedPhrase, RepetitionReport, RepetitionCheckerError,
)
from .reference_similarity_checker import (
    check_reference_similarity, ReferenceMaterial, ReferenceSimilarityReport,
    ReferenceSimilarityError, TextSpan,
)
from .reader_simulation import (
    SceneReaderAnnotation, ReaderSimulationReport, ReaderSimulationError,
    simulate_reader_profiles,
)

_SHA = re.compile(r'[0-9a-f]{64}\Z')
_ALLOWED_ISSUES = frozenset({
    'REPETITION', 'STYLE', 'CONTINUITY', 'KNOWLEDGE', 'TIMELINE',
    'FORESHADOWING', 'LOGIC', 'REFERENCE_SIMILARITY', 'READER_PROXY', 'MANUAL',
})
_ALLOWED_PROVIDERS = {
    'offline-mock-v1': 'DETERMINISTIC_MOCK_NOT_AI',
    'local-executable-v1': 'LOCAL_EXECUTABLE_OUTPUT_NOT_VERIFIED_AS_AI',
}
MAX_ISSUES = 200
MAX_REVISIONS = 100


class SceneRevisionError(ValueError):
    """Redacted error that must not reveal manuscript or reference prose."""


@dataclass(frozen=True)
class SceneIssue:
    scene_number: int
    code: str
    start: int  # Absolute Python-string offsets into the ORIGINAL episode
    end: int
    evidence_sha256: str


@dataclass(frozen=True)
class SceneReplacement:
    scene_number: int
    original_sha256: str
    revised_text: str = field(repr=False)
    revised_sha256: str
    origin: str = 'REVIEWER_SUPPLIED'
    prompt_sha256: str | None = None


@dataclass(frozen=True)
class RevisionSceneSpan:
    scene_number: int
    start: int
    end: int
    original_sha256: str
    current_sha256: str
    changed: bool
    origin: str
    prompt_sha256: str | None
    supporting_fact_ids: tuple[str, ...]


@dataclass(frozen=True)
class SceneRevisionReport:
    project_id: str
    episode_number: int
    source_sha256: str
    revised_sha256: str
    changed_scene_numbers: tuple[int, ...]
    scene_count: int
    issue_count: int
    repetition: RepetitionReport
    reference_similarity: ReferenceSimilarityReport | None
    reader_simulation: ReaderSimulationReport | None
    pending_checks: tuple[str, ...]
    status: str = 'REVIEW_REQUIRED_NOT_APPROVED'
    manuscript_approved: bool = False
    publication_approved: bool = False
    persisted: bool = False


@dataclass(frozen=True)
class EpisodeRevisionPreview:
    project_id: str
    episode_number: int
    draft: str = field(repr=False)
    draft_sha256: str
    source_sha256: str
    scenes: tuple[RevisionSceneSpan, ...]
    canon_fact_ids: tuple[str, ...]
    report: SceneRevisionReport
    status: str = 'DRAFT_REQUIRES_USER_APPROVAL'
    persisted: bool = False
    publication_approved: bool = False


def _digest(text: str) -> str:
    try:
        return sha256(text.encode('utf-8')).hexdigest()
    except UnicodeError:
        raise SceneRevisionError('invalid unicode') from None


def _valid_text(text: object, *, maximum: int) -> str:
    if (type(text) is not str or not text.strip() or len(text) > maximum
            or any((ord(c) < 32 and c not in '\n\r\t') or ord(c) == 127 for c in text)):
        raise SceneRevisionError('invalid draft text')
    _digest(text)
    return text


def _valid_sha(value: object) -> bool:
    return type(value) is str and _SHA.fullmatch(value) is not None


def _source(preview: object) -> EpisodeDraftPreview:
    if (type(preview) is not EpisodeDraftPreview
            or type(preview.project_id) is not str or not preview.project_id.strip()
            or len(preview.project_id) > 128 or '\x00' in preview.project_id
            or type(preview.episode_number) is not int
            or not 1 <= preview.episode_number <= 1_000_000
            or preview.status != 'DRAFT_REQUIRES_USER_APPROVAL'
            or preview.persisted is not False or preview.publication_approved is not False
            or type(preview.provider) is not str or preview.provider not in _ALLOWED_PROVIDERS
            or preview.origin != _ALLOWED_PROVIDERS[preview.provider]
            or type(preview.canon_fact_ids) is not tuple or not preview.canon_fact_ids
            or any(type(x) is not str or not x for x in preview.canon_fact_ids)
            or type(preview.scenes) is not tuple
            or not 1 <= len(preview.scenes) <= MAX_REVISIONS):
        raise SceneRevisionError('invalid source preview')
    draft = _valid_text(preview.draft, maximum=MAX_EPISODE_DRAFT_CHARS)
    if not _valid_sha(preview.draft_sha256) or _digest(draft) != preview.draft_sha256:
        raise SceneRevisionError('source digest mismatch')
    position = 0
    for number, span in enumerate(preview.scenes, 1):
        if number > 1:
            if draft[position:position + len(SCENE_SEPARATOR)] != SCENE_SEPARATOR:
                raise SceneRevisionError('invalid scene separator')
            position += len(SCENE_SEPARATOR)
        if (type(span) is not SceneSpan or type(span.scene_number) is not int
                or span.scene_number != number or type(span.start) is not int
                or type(span.end) is not int or span.start != position
                or not span.start < span.end <= len(draft)
                or not _valid_sha(span.draft_sha256)
                or not _valid_sha(span.prompt_sha256)
                or type(span.supporting_fact_ids) is not tuple
                or any(type(x) is not str or not x for x in span.supporting_fact_ids)
                or not draft[span.start:span.end].strip()
                or _digest(draft[span.start:span.end]) != span.draft_sha256):
            raise SceneRevisionError('invalid source scene')
        position = span.end
    if position != len(draft):
        raise SceneRevisionError('source scene coverage mismatch')
    return preview


def replacement_from_scene_preview(source: EpisodeDraftPreview, preview: SceneDraftPreview) -> SceneReplacement:
    """Adapt a separately generated stage-64 draft without invoking its provider."""
    source = _source(source)
    if (type(preview) is not SceneDraftPreview or type(preview.result) is not SceneDraftResult
            or preview.status != 'DRAFT_REQUIRES_USER_APPROVAL'
            or preview.persisted is not False or preview.publication_approved is not False
            or preview.result.status != 'DRAFT_REQUIRES_USER_APPROVAL'
            or preview.result.persisted is not False
            or preview.result.project_id != source.project_id
            or preview.result.episode_number != source.episode_number
            or type(preview.result.scene_number) is not int
            or not 1 <= preview.result.scene_number <= len(source.scenes)
            or preview.result.provider != source.provider or preview.origin != source.origin
            or preview.canon_fact_ids != source.canon_fact_ids
            or preview.supporting_fact_ids != source.scenes[preview.result.scene_number - 1].supporting_fact_ids
            or not _valid_sha(preview.prompt_sha256)
            or not _valid_sha(preview.draft_sha256)):
        raise SceneRevisionError('invalid stage64 replacement preview')
    draft = _valid_text(preview.result.draft, maximum=MAX_EPISODE_DRAFT_CHARS)
    if _digest(draft) != preview.draft_sha256:
        raise SceneRevisionError('stage64 replacement digest mismatch')
    original = source.scenes[preview.result.scene_number - 1]
    return SceneReplacement(preview.result.scene_number, original.draft_sha256,
                            draft, preview.draft_sha256, 'STAGE64_PREVIEW', preview.prompt_sha256)


def rewrite_selected_scenes(
    source: EpisodeDraftPreview,
    *,
    issues: tuple[SceneIssue, ...],
    replacements: tuple[SceneReplacement, ...],
    watched_phrases: tuple[WatchedPhrase, ...] = (),
    repetition_policy: RepetitionPolicy = RepetitionPolicy(),
    references: tuple[ReferenceMaterial, ...] | None = None,
    draft_beats: tuple[str, ...] = (),
    required_reference_ids: tuple[str, ...] | None = None,
    catalog=None,
    reader_marks: tuple[dict[str, bool | None], ...] | None = None,
) -> EpisodeRevisionPreview:
    """Replace ONLY flagged scenes, reassemble, and rerun configured checks.

    The replacement text is caller-supplied; this function does not write or
    regenerate anything. All issue evidence must be bound to the source hash.
    Missing check inputs are explicitly pending, never silently passed.
    """
    source = _source(source)
    if (type(issues) is not tuple or not 1 <= len(issues) <= MAX_ISSUES
            or type(replacements) is not tuple or not 1 <= len(replacements) <= len(source.scenes)
            or len(replacements) > MAX_REVISIONS):
        raise SceneRevisionError('invalid issue/replacement count')
    issue_scenes: set[int] = set()
    issue_keys: set[tuple] = set()
    for issue in issues:
        if (type(issue) is not SceneIssue or type(issue.scene_number) is not int
                or not 1 <= issue.scene_number <= len(source.scenes)
                or type(issue.code) is not str or issue.code not in _ALLOWED_ISSUES
                or type(issue.start) is not int or type(issue.end) is not int
                or not _valid_sha(issue.evidence_sha256)):
            raise SceneRevisionError('invalid issue evidence')
        span = source.scenes[issue.scene_number - 1]
        if (not span.start <= issue.start < issue.end <= span.end
                or not source.draft[issue.start:issue.end].strip()
                or _digest(source.draft[issue.start:issue.end]) != issue.evidence_sha256):
            raise SceneRevisionError('stale issue evidence')
        key = (issue.scene_number, issue.code, issue.start, issue.end)
        if key in issue_keys:
            raise SceneRevisionError('duplicate issue')
        issue_keys.add(key)
        issue_scenes.add(issue.scene_number)
    changes: dict[int, SceneReplacement] = {}
    for item in replacements:
        if (type(item) is not SceneReplacement or type(item.scene_number) is not int
                or item.scene_number not in issue_scenes or item.scene_number in changes
                or not _valid_sha(item.original_sha256)
                or not _valid_sha(item.revised_sha256)
                or item.origin not in ('REVIEWER_SUPPLIED', 'STAGE64_PREVIEW')
                or (item.origin == 'REVIEWER_SUPPLIED' and item.prompt_sha256 is not None)
                or (item.origin == 'STAGE64_PREVIEW' and not _valid_sha(item.prompt_sha256))):
            raise SceneRevisionError('invalid replacement metadata')
        original = source.scenes[item.scene_number - 1]
        revised = _valid_text(item.revised_text, maximum=MAX_EPISODE_DRAFT_CHARS)
        if (item.original_sha256 != original.draft_sha256
                or _digest(revised) != item.revised_sha256
                or revised == source.draft[original.start:original.end]):
            raise SceneRevisionError('replacement is stale or unchanged')
        changes[item.scene_number] = item
    if set(changes) != issue_scenes:
        raise SceneRevisionError('each flagged scene requires exactly one replacement')
    if references is None and (draft_beats or required_reference_ids is not None or catalog is not None):
        raise SceneRevisionError('reference inputs without references')

    parts: list[str] = []
    spans: list[RevisionSceneSpan] = []
    position = 0
    for original in source.scenes:
        if parts:
            position += len(SCENE_SEPARATOR)
        replacement = changes.get(original.scene_number)
        text = (replacement.revised_text if replacement is not None
                else source.draft[original.start:original.end])
        start = position
        position += len(text)
        if position > MAX_EPISODE_DRAFT_CHARS:
            raise SceneRevisionError('revised episode exceeds limit')
        spans.append(RevisionSceneSpan(
            original.scene_number, start, position, original.draft_sha256,
            _digest(text), replacement is not None,
            replacement.origin if replacement else 'UNCHANGED_SOURCE',
            replacement.prompt_sha256 if replacement else original.prompt_sha256,
            original.supporting_fact_ids,
        ))
        parts.append(text)
    draft = SCENE_SEPARATOR.join(parts)
    if len(draft) > MAX_EPISODE_DRAFT_CHARS:
        raise SceneRevisionError('revised episode exceeds limit')
    try:
        repetition = check_repetition(source.project_id, source.episode_number, draft,
                                      watched_phrases=watched_phrases, policy=repetition_policy)
        similarity = None
        if references is not None:
            similarity = check_reference_similarity(
                source.project_id, source.episode_number, draft, references=references,
                draft_scenes=tuple(TextSpan(x.start, x.end) for x in spans),
                draft_beats=draft_beats, required_reference_ids=required_reference_ids,
                catalog=catalog,
            )
        reader = None
        if reader_marks is not None:
            if type(reader_marks) is not tuple or len(reader_marks) != len(spans):
                raise SceneRevisionError('invalid fresh reader annotations')
            attrs = ('goal_visible', 'tension_present', 'development',
                     'character_choice', 'consequence', 'closing_hook')
            annotations = []
            for span, marks in zip(spans, reader_marks):
                if (type(marks) is not dict or set(marks) != set(attrs)
                        or any(type(v) not in (bool, type(None)) for v in marks.values())):
                    raise SceneRevisionError('invalid fresh reader annotations')
                annotations.append(SceneReaderAnnotation(
                    span.scene_number, span.start, span.end, span.current_sha256, **marks))
            reader = simulate_reader_profiles(source.project_id, source.episode_number,
                                              draft, scenes=tuple(annotations))
    except (RepetitionCheckerError, ReferenceSimilarityError, ReaderSimulationError):
        raise SceneRevisionError('recheck input invalid') from None

    pending = {'human_issue_resolution_review', 'continuity_logic_style_and_canon_recheck',
               'user_approval_required'}
    if repetition.findings or repetition.unexamined:
        pending.add('repetition_findings_or_unexamined')
    if similarity is None:
        pending.add('reference_similarity_not_rechecked')
    elif similarity.status != 'clear' or not similarity.registration_checked:
        pending.add('reference_similarity_not_cleared')
    if reader is None:
        pending.add('fresh_reader_annotations_not_provided')
    elif reader.unexamined:
        pending.add('reader_annotations_incomplete')
    report = SceneRevisionReport(
        source.project_id, source.episode_number, source.draft_sha256, _digest(draft),
        tuple(sorted(changes)), len(spans), len(issues), repetition, similarity, reader,
        tuple(sorted(pending)),
    )
    return EpisodeRevisionPreview(source.project_id, source.episode_number, draft,
                                  report.revised_sha256, source.draft_sha256,
                                  tuple(spans), source.canon_fact_ids, report)
