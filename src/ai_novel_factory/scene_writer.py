"""Stage 64: explicit, offline scene-level draft generation from vetted plans.

The result is an unapproved, transient preview.  No database write, file write,
reference-novel source loading, publishing or network transport is performed here.
The adapter does NOT attest that a user-provided executable is network isolated.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

from .episode_context import EpisodeContext
from .episode_planner import EpisodePlan
from .local_models import (
    LocalExecutableProvider, LocalModelError, MockSceneProvider,
    SceneDraftResult, _message, draft_scene,
)
from .planning import PlanningError
from .scene_planner import ScenePlan
from .writer_prompt import WriterPromptPreview, build_writer_prompt


class SceneWriterError(ValueError):
    """A draft cannot be produced safely; never include user text in messages."""


@dataclass(frozen=True)
class SceneDraftPreview:
    """A single non-persistent scene draft with review and provenance metadata."""
    result: SceneDraftResult
    prompt_sha256: str
    draft_sha256: str
    canon_fact_ids: tuple[str, ...]
    supporting_fact_ids: tuple[str, ...]
    origin: str
    status: str = 'DRAFT_REQUIRES_USER_APPROVAL'
    persisted: bool = False
    publication_approved: bool = False


def generate_scene_draft(
    project_id: str,
    episode: EpisodePlan,
    scene: ScenePlan,
    context: EpisodeContext,
    provider: MockSceneProvider | LocalExecutableProvider,
    *,
    local_execution_approved: bool = False,
) -> SceneDraftPreview:
    """Build canon-first prompt and call an expressly allowed offline provider.

    The local process requires a *second* explicit opt-in at call time.  We only
    accept the two concrete adapters from stage 61; arbitrarily supplied
    providers could make remote calls while masquerading as offline providers.
    Local executable code itself must be independently vetted by the owner.
    """
    if type(provider) is MockSceneProvider:
        origin = 'DETERMINISTIC_MOCK_NOT_AI'
    elif type(provider) is LocalExecutableProvider:
        if local_execution_approved is not True:
            raise SceneWriterError('local execution requires explicit approval')
        origin = 'LOCAL_EXECUTABLE_OUTPUT_NOT_VERIFIED_AS_AI'
    else:
        raise SceneWriterError('unsupported offline scene provider')

    try:
        prompt: WriterPromptPreview = build_writer_prompt(project_id, episode, scene, context)
        result = draft_scene(prompt.request, provider)
    except (PlanningError, LocalModelError) as exc:
        # Sanitized exception strings from the contract validators only.
        raise SceneWriterError(str(exc)) from None

    if (result.project_id != project_id
            or result.episode_number != episode.episode_number
            or result.scene_number != scene.scene_number
            or result.status != 'DRAFT_REQUIRES_USER_APPROVAL'
            or result.persisted is not False):
        raise SceneWriterError('scene provider returned inconsistent draft metadata')

    request_json = json.dumps(_message(prompt.request), ensure_ascii=False,
                              separators=(',', ':'), sort_keys=True)
    return SceneDraftPreview(
        result=result,
        prompt_sha256=sha256(request_json.encode('utf-8')).hexdigest(),
        draft_sha256=sha256(result.draft.encode('utf-8')).hexdigest(),
        canon_fact_ids=prompt.canon_fact_ids,
        supporting_fact_ids=prompt.supporting_fact_ids,
        origin=origin,
    )
