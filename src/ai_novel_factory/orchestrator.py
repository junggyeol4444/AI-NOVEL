"""Stage 66: offline Planner -> Writer -> preliminary Checker control.

This is deliberately NOT the later full quality/rewrite/memory pipeline. All
outputs remain in memory and unapproved. No persistence, publication or network
API is performed by this module. A trusted local model executable requires the
separate explicit consent enforced by stage 64.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from .episode_assembler import EpisodeAssemblyError, EpisodeDraftPreview, assemble_episode_draft
from .episode_context import EpisodeContext
from .episode_planner import EpisodePlan
from .local_models import LocalExecutableProvider, MockSceneProvider
from .scene_planner import ScenePlan, validate_scene_plans
from .scene_writer import SceneWriterError, generate_scene_draft

MAX_CHECK_TERMS = 50
MAX_TERM_CHARS = 120


class OrchestrationError(ValueError):
    """Invalid workflow arguments; never disclose manuscript or provider stderr."""


@dataclass(frozen=True)
class WorkflowEvent:
    """Non-sensitive deterministic progression record; not a persistent audit log."""
    sequence: int
    step: str
    status: str
    scene_number: int | None = None


@dataclass(frozen=True)
class PreliminaryCheck:
    """Limited literal-text check; NOT full continuity, logic or similarity QC."""
    passed: bool
    finding_count: int
    finding_term_hashes: tuple[str, ...]
    scope: str = 'LITERAL_TERMS_ONLY_NOT_FULL_QC'


class OfflineLiteralChecker:
    """A bounded local demonstration checker; exact literal substring matching.

    Check strings are author-defined and never bundled from reference source
    texts. This is *not* the later Continuity/Similarity Checker.
    """
    def __init__(self, forbidden_terms: tuple[str, ...] = ()) -> None:
        if (type(forbidden_terms) is not tuple or len(forbidden_terms) > MAX_CHECK_TERMS
                or any(type(t) is not str or not t.strip() or '\x00' in t
                       or len(t) > MAX_TERM_CHARS for t in forbidden_terms)
                or len(set(forbidden_terms)) != len(forbidden_terms)):
            raise OrchestrationError('invalid local checker rules')
        self._terms = forbidden_terms

    def check(self, preview: EpisodeDraftPreview) -> PreliminaryCheck:
        if type(preview) is not EpisodeDraftPreview or preview.status != 'DRAFT_REQUIRES_USER_APPROVAL':
            raise OrchestrationError('invalid preliminary check input')
        if sha256(preview.draft.encode('utf-8')).hexdigest() != preview.draft_sha256:
            raise OrchestrationError('episode text integrity mismatch')
        found = tuple(sha256(term.encode('utf-8')).hexdigest()
                      for term in self._terms if term in preview.draft)
        return PreliminaryCheck(not found, len(found), found)


@dataclass(frozen=True)
class OrchestrationRun:
    project_id: str
    episode_number: int
    status: str
    events: tuple[WorkflowEvent, ...]
    preview: EpisodeDraftPreview | None
    preliminary_check: PreliminaryCheck | None
    error_code: str | None = None
    persisted: bool = False
    publication_approved: bool = False
    memory_updated: bool = False
    rewritten: bool = False
    origin: str = 'OFFLINE_STAGE66_CONTROL_NOT_FULL_QC'


def orchestrate_episode(
    project_id: str,
    episode: EpisodePlan,
    scenes: tuple[ScenePlan, ...],
    context: EpisodeContext,
    provider: MockSceneProvider | LocalExecutableProvider,
    checker: OfflineLiteralChecker,
    *,
    local_execution_approved: bool = False,
) -> OrchestrationRun:
    """Run vetted plans through scene drafting, assembly, limited check, review gate.

    On an operational failure, return FAILED with non-sensitive state history,
    discard incomplete previews, and never attempt saving/retry/rewriting.
    Invalid argument types are rejected before calling the provider. Stage 71+
    real checkers and stage 80+/81+ rewrite/memory will require new integration.
    """
    if (type(project_id) is not str or not project_id.strip() or len(project_id) > 128
            or '\x00' in project_id or type(episode) is not EpisodePlan
            or type(context) is not EpisodeContext or context.project_id != project_id
            or context.episode_number != episode.episode_number
            or context.status != 'DRAFT_REQUIRES_USER_APPROVAL'
            or episode.status != 'DRAFT_REQUIRES_USER_APPROVAL'
            or type(scenes) is not tuple or not 1 <= len(scenes) <= 100
            or not validate_scene_plans(episode, scenes, require_details=True)
            or any(type(scene) is not ScenePlan or scene.status != 'DRAFT_REQUIRES_USER_APPROVAL'
                   for scene in scenes)):
        raise OrchestrationError('invalid project, planning or context inputs')
    if type(checker) is not OfflineLiteralChecker:
        raise OrchestrationError('a supported offline checker is required')
    if type(provider) not in (MockSceneProvider, LocalExecutableProvider):
        raise OrchestrationError('a supported offline scene provider is required')
    if type(local_execution_approved) is not bool:
        raise OrchestrationError('invalid execution approval')
    if type(provider) is LocalExecutableProvider and not local_execution_approved:
        raise OrchestrationError('local process requires separate approval')

    events: list[WorkflowEvent] = []

    def event(step: str, status: str, scene_number: int | None = None) -> None:
        events.append(WorkflowEvent(len(events) + 1, step, status, scene_number))

    event('PLANNER', 'VALIDATED')
    previews = []
    try:
        for scene in scenes:
            # Caller-owned episode/scene plans, not generated unvetted details.
            previews.append(generate_scene_draft(
                project_id, episode, scene, context, provider,
                local_execution_approved=local_execution_approved))
            event('WRITER', 'DRAFTED', scene.scene_number)
        combined = assemble_episode_draft(project_id, episode, scenes, tuple(previews))
        event('ASSEMBLER', 'ASSEMBLED')
        check = checker.check(combined)
        event('CHECKER', 'PRELIMINARY_PASS' if check.passed else 'PRELIMINARY_ISSUES')
        status = 'AWAITING_HUMAN_REVIEW' if check.passed else 'REWRITE_REQUIRED_NOT_IMPLEMENTED'
        event('HUMAN_GATE', 'PENDING' if check.passed else 'BLOCKED')
        return OrchestrationRun(project_id, episode.episode_number, status,
                                tuple(events), combined, check)
    except (SceneWriterError, EpisodeAssemblyError, OrchestrationError) as exc:
        code = ('SCENE_DRAFT_FAILED' if isinstance(exc, SceneWriterError) else
                'ASSEMBLY_FAILED' if isinstance(exc, EpisodeAssemblyError) else
                'CHECK_FAILED')
        event('WORKFLOW', 'FAILED')
        return OrchestrationRun(project_id, episode.episode_number, 'FAILED',
                                tuple(events), None, None, error_code=code)
    except Exception:
        # Third-party/local-provider exceptions must not disclose source text.
        # Never return a partial manuscript after an unexpected failure.
        event('WORKFLOW', 'FAILED')
        return OrchestrationRun(project_id, episode.episode_number, 'FAILED',
                                tuple(events), None, None, error_code='UNEXPECTED_FAILURE')

