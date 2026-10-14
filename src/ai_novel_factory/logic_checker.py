"""Stage 75 / ANF-REQ-052: bounded, reviewer-evidenced story logic checks.

This is *not* semantic understanding: a human labels story-order premises and
actions, and the checker evaluates the explicit dependency graph. It never
loads reference texts, changes Novel Bible, persists drafts or approves output.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re

MAX_MANUSCRIPT_CHARS = 1_000_000
MAX_EVIDENCE_CHARS = 4000
MAX_PREMISES = 1000
MAX_ACTIONS = 500
MAX_REQUIREMENTS = 32
KINDS = frozenset({'MOTIVE', 'ABILITY', 'CAUSE', 'RESOLUTION'})
_KEY = re.compile(r'[a-z][a-z0-9_]{0,63}\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')


class LogicCheckerError(ValueError):
    """Safe validation error; never includes manuscript or premise contents."""


@dataclass(frozen=True)
class LogicPremise:
    """A human-asserted fact, true or false, at a declared STORY step.

    `story_step` is author-supplied chronological order, NOT prose offset.
    Multiple entries for a fact are permitted across steps (changed facts).
    """
    project_id: str
    fact_key: str
    kind: str
    story_step: int
    scene_number: int
    start: int
    end: int
    evidence: str
    established: bool = True


@dataclass(frozen=True)
class LogicAction:
    """Human-marked action/decision/resolution with dependencies of one kind.

    An empty `required_facts` reports missing stated justification. This does
    not imply an action is objectively unreasonable in the full novel.
    `COINCIDENCE` is not a dependency kind; set `coincidence=True` to request
    human examination of a manually identified coincidence.
    """
    project_id: str
    action_id: str
    kind: str
    story_step: int
    scene_number: int
    start: int
    end: int
    evidence: str
    required_facts: tuple[str, ...] = ()
    coincidence: bool = False


@dataclass(frozen=True)
class LogicFinding:
    action_id: str
    kind: str
    fact_key: str | None
    code: str
    start: int
    end: int
    evidence_sha256: str
    premise_sha256: str | None = None


@dataclass(frozen=True)
class LogicReport:
    project_id: str
    episode_number: int
    manuscript_sha256: str
    examined_actions: int
    examined_premises: int
    findings: tuple[LogicFinding, ...]
    status: str = 'REQUIRES_HUMAN_REVIEW_NOT_FULL_QC'
    persisted: bool = False
    publication_approved: bool = False

    @property
    def passed_declared_dependencies(self) -> bool:
        """Only supplied annotations have no findings, NOT a full logic verdict."""
        return not self.findings


def _digest(value: str) -> str:
    try:
        return sha256(value.encode('utf-8')).hexdigest()
    except UnicodeError:
        raise LogicCheckerError('invalid text encoding') from None


def _project(value: object) -> str:
    if type(value) is not str or not value.strip() or len(value) > 128 or any(
        ord(c) < 32 or ord(c) == 127 for c in value
    ):
        raise LogicCheckerError('invalid project identifier')
    _digest(value)
    return value


def _key(value: object) -> str:
    if type(value) is not str or _KEY.fullmatch(value) is None:
        raise LogicCheckerError('invalid logic identifier')
    return value


def _positive(value: object, label: str, *, limit: int = 1_000_000) -> int:
    if type(value) is not int or not 1 <= value <= limit:
        raise LogicCheckerError('invalid ' + label)
    return value


def _span(manuscript: str, start: object, end: object, evidence: object) -> str:
    if (type(start) is not int or type(end) is not int or
        not 0 <= start < end <= len(manuscript) or type(evidence) is not str or
        not evidence.strip() or len(evidence) > MAX_EVIDENCE_CHARS or
        manuscript[start:end] != evidence):
        raise LogicCheckerError('invalid manuscript evidence')
    return _digest(evidence)


def _kind(value: object) -> str:
    if type(value) is not str or value not in KINDS:
        raise LogicCheckerError('unsupported logic kind')
    return value


def check_logic(
    project_id: str,
    episode_number: int,
    manuscript: str,
    premises: tuple[LogicPremise, ...],
    actions: tuple[LogicAction, ...],
    *,
    expected_manuscript_sha256: str | None = None,
) -> LogicReport:
    """Inspect explicit dependencies. Never infer facts from unmarked prose.

    Premises apply only when their story_step is strictly less than the action's.
    Equal-step support is inconclusive, not silently presumed to precede it.
    When no prior premise exists: absent => NOT_ESTABLISHED, future =>
    NOT_YET_ESTABLISHED, same step => SAME_STEP_UNVERIFIABLE. The last prior
    truth value wins; contradictory entries on that step => AMBIGUOUS_PREMISE.
    """
    _project(project_id)
    _positive(episode_number, 'episode number')
    if (type(manuscript) is not str or not manuscript.strip() or
        len(manuscript) > MAX_MANUSCRIPT_CHARS):
        raise LogicCheckerError('invalid manuscript')
    manuscript_sha = _digest(manuscript)
    if expected_manuscript_sha256 is not None and (
        type(expected_manuscript_sha256) is not str or
        _SHA.fullmatch(expected_manuscript_sha256) is None or
        expected_manuscript_sha256 != manuscript_sha
    ):
        raise LogicCheckerError('manuscript integrity mismatch')
    if (type(premises) is not tuple or len(premises) > MAX_PREMISES or
        type(actions) is not tuple or len(actions) > MAX_ACTIONS):
        raise LogicCheckerError('invalid logic annotations')

    facts: dict[tuple[str, str], list[tuple[LogicPremise, str]]] = {}
    seen_premises: set[tuple[str, str, int, int, int]] = set()
    for premise in premises:
        if type(premise) is not LogicPremise or premise.project_id != project_id:
            raise LogicCheckerError('invalid or cross-project premise')
        key = _key(premise.fact_key)
        kind = _kind(premise.kind)
        step = _positive(premise.story_step, 'story step')
        _positive(premise.scene_number, 'scene number', limit=100)
        if type(premise.established) is not bool:
            raise LogicCheckerError('invalid premise truth value')
        fingerprint = _span(manuscript, premise.start, premise.end, premise.evidence)
        identity = (key, kind, step, premise.start, premise.end)
        if identity in seen_premises:
            raise LogicCheckerError('duplicate premise annotation')
        seen_premises.add(identity)
        facts.setdefault((key, kind), []).append((premise, fingerprint))

    findings: list[LogicFinding] = []
    action_ids: set[str] = set()
    for action in actions:
        if type(action) is not LogicAction or action.project_id != project_id:
            raise LogicCheckerError('invalid or cross-project action')
        action_id = _key(action.action_id)
        if action_id in action_ids:
            raise LogicCheckerError('duplicate action identifier')
        action_ids.add(action_id)
        kind = _kind(action.kind)
        step = _positive(action.story_step, 'story step')
        _positive(action.scene_number, 'scene number', limit=100)
        fingerprint = _span(manuscript, action.start, action.end, action.evidence)
        if type(action.coincidence) is not bool:
            raise LogicCheckerError('invalid coincidence flag')
        if (type(action.required_facts) is not tuple or
            len(action.required_facts) > MAX_REQUIREMENTS):
            raise LogicCheckerError('invalid action dependencies')
        requirements = tuple(_key(key) for key in action.required_facts)
        if len(set(requirements)) != len(requirements):
            raise LogicCheckerError('duplicate action dependency')

        def finding(code: str, key: str | None = None, premise_sha: str | None = None) -> None:
            findings.append(LogicFinding(action_id, kind, key, code,
                                         action.start, action.end, fingerprint, premise_sha))

        if not requirements:
            finding('NO_DECLARED_JUSTIFICATION')
        for key in requirements:
            history = facts.get((key, kind), [])
            prior = [(item, digest) for item, digest in history if item.story_step < step]
            if not prior:
                if any(item.story_step == step for item, _ in history):
                    finding('SAME_STEP_UNVERIFIABLE', key)
                elif any(item.story_step > step for item, _ in history):
                    finding('NOT_YET_ESTABLISHED', key)
                else:
                    finding('NOT_ESTABLISHED', key)
                continue
            latest_step = max(item.story_step for item, _ in prior)
            recent = [(item, digest) for item, digest in prior if item.story_step == latest_step]
            if len({item.established for item, _ in recent}) != 1:
                finding('AMBIGUOUS_PREMISE', key)
            elif recent[0][0].established is False:
                finding('CONTRADICTED_PREMISE', key, recent[0][1])
        if action.coincidence:
            # Marked coincidence is advisory, never an objective logic failure.
            finding('COINCIDENCE_REVIEW')

    return LogicReport(project_id, episode_number, manuscript_sha,
                       len(actions), len(premises), tuple(findings))


def check_episode_logic(
    preview: object,
    premises: tuple[LogicPremise, ...],
    actions: tuple[LogicAction, ...],
) -> LogicReport:
    """Validate immutable stage-65 draft provenance and per-scene evidence.

    Story steps are human chronology labels; scene numbers only tie evidence
    spans to their proper assembled draft, even for flashback scenes.
    """
    from .episode_assembler import EpisodeDraftPreview, SceneSpan

    if (type(preview) is not EpisodeDraftPreview or
        preview.status != 'DRAFT_REQUIRES_USER_APPROVAL' or
        preview.persisted is not False or preview.publication_approved is not False or
        type(preview.draft) is not str or
        type(preview.scenes) is not tuple or not preview.scenes or
        type(preview.draft_sha256) is not str or
        preview.draft_sha256 != _digest(preview.draft)):
        raise LogicCheckerError('invalid or altered episode draft')
    scene_map: dict[int, SceneSpan] = {}
    expected_start = 0
    for scene in preview.scenes:
        if (type(scene) is not SceneSpan or
            type(scene.scene_number) is not int or scene.scene_number in scene_map or
            not 1 <= scene.scene_number <= 100 or
            type(scene.start) is not int or type(scene.end) is not int or
            not 0 <= scene.start < scene.end <= len(preview.draft) or
            type(scene.draft_sha256) is not str or
            _digest(preview.draft[scene.start:scene.end]) != scene.draft_sha256 or
            scene.start != expected_start):
            raise LogicCheckerError('invalid scene provenance')
        scene_map[scene.scene_number] = scene
        expected_start = scene.end + 2
        if scene is not preview.scenes[-1] and preview.draft[scene.end:expected_start] != '\n\n':
            raise LogicCheckerError('invalid scene separator')
    if preview.scenes[-1].end != len(preview.draft):
        raise LogicCheckerError('incomplete scene coverage')
    for annotation in (*premises, *actions):
        if type(annotation) not in (LogicPremise, LogicAction):
            raise LogicCheckerError('invalid annotation')
        scene = scene_map.get(annotation.scene_number)
        if scene is None or not (scene.start <= annotation.start < annotation.end <= scene.end):
            raise LogicCheckerError('evidence crosses scene boundary')
    return check_logic(preview.project_id, preview.episode_number, preview.draft,
                       premises, actions, expected_manuscript_sha256=preview.draft_sha256)
