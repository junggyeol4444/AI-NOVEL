"""Stage 79 / ANF-REQ-055: local, *annotated proxy* reader evaluation.

This is not a trained reader, an LLM, a prediction of actual reader response,
quality certification, or a manuscript approval. Human reviewers must explicitly
mark six observable scene attributes. No raw manuscript enters a report.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re

from .database.novel_bible import _id, NovelBibleError
from .episode_assembler import EpisodeDraftPreview, SceneSpan, SCENE_SEPARATOR

MAX_DRAFT_CHARS = 1_000_000
MAX_SCENES = 100
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_ATTRIBUTES = ('goal_visible', 'tension_present', 'development',
               'character_choice', 'consequence', 'closing_hook')
_DIMENSIONS = (
    ('engagement', (('goal_visible', .35), ('tension_present', .40), ('development', .25))),
    ('pacing', (('tension_present', .30), ('development', .50), ('consequence', .20))),
    ('character', (('character_choice', .60), ('consequence', .40))),
    ('hook', (('closing_hook', .70), ('tension_present', .30))),
)
_PROFILES = (
    ('momentum', (('engagement', .25), ('pacing', .40), ('character', .10), ('hook', .25))),
    ('character', (('engagement', .20), ('pacing', .10), ('character', .55), ('hook', .15))),
    ('cliffhanger', (('engagement', .15), ('pacing', .15), ('character', .10), ('hook', .60))),
)


class ReaderSimulationError(ValueError):
    """Redacted error: never contains text, annotations or file paths."""


@dataclass(frozen=True)
class SceneReaderAnnotation:
    scene_number: int
    start: int
    end: int
    evidence_sha256: str
    goal_visible: bool | None = None
    tension_present: bool | None = None
    development: bool | None = None
    character_choice: bool | None = None
    consequence: bool | None = None
    closing_hook: bool | None = None


@dataclass(frozen=True)
class ReaderMetric:
    dimension: str
    score: float | None  # 0..100; None when evidence is incomplete
    observations: int
    required_observations: int


@dataclass(frozen=True)
class ReaderProfile:
    profile: str
    score: float | None  # None unless all four dimensions are complete


@dataclass(frozen=True)
class ReaderSimulationReport:
    project_id: str
    episode_number: int
    draft_sha256: str
    annotation_sha256: str
    scene_count: int
    metrics: tuple[ReaderMetric, ...]
    profiles: tuple[ReaderProfile, ...]
    unexamined: tuple[str, ...]
    status: str
    methodology: str = 'MANUALLY_ANNOTATED_DETERMINISTIC_PROXY_NOT_REAL_READERS'
    persisted: bool = False
    manuscript_approved: bool = False
    publication_approved: bool = False


def _digest(text: str) -> str:
    try:
        return sha256(text.encode('utf-8')).hexdigest()
    except UnicodeError:
        raise ReaderSimulationError('invalid unicode') from None


def _check_inputs(project_id: str, episode_number: int, draft: str,
                  scenes: tuple[SceneReaderAnnotation, ...]) -> None:
    try:
        _id(project_id)
    except NovelBibleError:
        raise ReaderSimulationError('invalid project') from None
    if type(episode_number) is not int or not 1 <= episode_number <= 1_000_000:
        raise ReaderSimulationError('invalid episode')
    if (type(draft) is not str or not draft.strip() or len(draft) > MAX_DRAFT_CHARS
            or any((ord(c) < 32 and c not in '\n\r\t') or ord(c) == 127 for c in draft)):
        raise ReaderSimulationError('invalid draft')
    _digest(draft)
    if type(scenes) is not tuple or not 1 <= len(scenes) <= MAX_SCENES:
        raise ReaderSimulationError('invalid annotations')
    previous = 0
    for index, scene in enumerate(scenes, 1):
        if (type(scene) is not SceneReaderAnnotation
                or type(scene.scene_number) is not int or scene.scene_number != index
                or type(scene.start) is not int or type(scene.end) is not int
                or not previous <= scene.start < scene.end <= len(draft)
                or draft[previous:scene.start].strip()
                or not draft[scene.start:scene.end].strip()
                or type(scene.evidence_sha256) is not str
                or _SHA.fullmatch(scene.evidence_sha256) is None
                or scene.evidence_sha256 != _digest(draft[scene.start:scene.end])):
            raise ReaderSimulationError('invalid scene evidence')
        for key in _ATTRIBUTES:
            if type(getattr(scene, key)) not in (bool, type(None)):
                raise ReaderSimulationError('invalid annotation value')
        previous = scene.end
    if draft[previous:].strip():
        raise ReaderSimulationError('uncovered draft content')


def simulate_reader_profiles(project_id: str, episode_number: int, draft: str, *,
                             scenes: tuple[SceneReaderAnnotation, ...]) -> ReaderSimulationReport:
    """Calculate transparent 0..100 **annotation coverage** proxies, not prose quality.

    Every attribute is a human-supplied yes/no/unknown marker. Missing markers
    make affected metrics and all profile scores inconclusive; never infer 'no'.
    Scene averages are equally weighted, regardless of scene length. The hook
    dimension considers the final scene only (not earlier scene endings).
    """
    _check_inputs(project_id, episode_number, draft, scenes)
    payload = [[s.scene_number, s.start, s.end, s.evidence_sha256,
                *[getattr(s, k) for k in _ATTRIBUTES]] for s in scenes]
    fingerprint = _digest(json.dumps(payload, separators=(',', ':'), ensure_ascii=True))
    metrics: list[ReaderMetric] = []
    incomplete: list[str] = []
    for name, weights in _DIMENSIONS:
        selected = scenes[-1:] if name == 'hook' else scenes
        expected = len(selected) * len(weights)
        known = sum(getattr(scene, key) is not None for scene in selected for key, _ in weights)
        score = None
        if known == expected:
            score = round(100 * sum(
                sum(float(getattr(scene, key)) * weight for key, weight in weights)
                for scene in selected) / len(selected), 2)
        else:
            incomplete.append('incomplete_' + name + '_annotations')
        metrics.append(ReaderMetric(name, score, known, expected))
    by_name = {m.dimension: m.score for m in metrics}
    profiles = tuple(ReaderProfile(name,
        round(sum(by_name[key] * weight for key, weight in weights), 2)
        if all(by_name[key] is not None for key, _ in weights) else None)
        for name, weights in _PROFILES)
    return ReaderSimulationReport(
        project_id, episode_number, _digest(draft), fingerprint, len(scenes),
        tuple(metrics), profiles, tuple(incomplete),
        'ANNOTATED_PROXY_ONLY' if not incomplete else 'INCOMPLETE_ANNOTATIONS')


def annotations_from_episode_preview(preview: EpisodeDraftPreview, *,
                                     marks: tuple[dict[str, bool | None], ...]) -> tuple[SceneReaderAnnotation, ...]:
    """Bind stage-65 unapproved scene boundaries to explicit reviewer marks.

    Reject forged/changed preview content and non-whitespace scene separators.
    Caller-supplied marks are *not* inferred from the draft or a local LLM.
    """
    if (type(preview) is not EpisodeDraftPreview
            or preview.status != 'DRAFT_REQUIRES_USER_APPROVAL'
            or preview.persisted is not False or preview.publication_approved is not False
            or type(preview.draft) is not str
            or type(preview.draft_sha256) is not str
            or preview.draft_sha256 != _digest(preview.draft)
            or type(preview.scenes) is not tuple
            or type(marks) is not tuple or len(preview.scenes) != len(marks)
            or not 1 <= len(marks) <= MAX_SCENES):
        raise ReaderSimulationError('invalid episode preview')
    out = []
    previous = 0
    for index, (span, values) in enumerate(zip(preview.scenes, marks), 1):
        if (type(span) is not SceneSpan
                or type(span.scene_number) is not int or span.scene_number != index
                or type(span.start) is not int or type(span.end) is not int
                or not previous <= span.start < span.end <= len(preview.draft)
                or (index == 1 and span.start != 0)
                or (index > 1 and preview.draft[previous:span.start] != SCENE_SEPARATOR)
                or type(span.draft_sha256) is not str
                or span.draft_sha256 != _digest(preview.draft[span.start:span.end])
                or type(values) is not dict or set(values) != set(_ATTRIBUTES)):
            raise ReaderSimulationError('invalid episode scene evidence')
        out.append(SceneReaderAnnotation(index, span.start, span.end, span.draft_sha256,
                                         **values))
        previous = span.end
    if previous != len(preview.draft):
        raise ReaderSimulationError('invalid episode scene coverage')
    _check_inputs(preview.project_id, preview.episode_number, preview.draft, tuple(out))
    return tuple(out)
