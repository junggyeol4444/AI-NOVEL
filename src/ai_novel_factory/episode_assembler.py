"""Stage 65: assemble ordered, unapproved scene drafts in memory only.

No model invocation, file/DB writes, similarity verdict or publishing action.
Reference text is not accepted as an assembly input; only stage-64 previews.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re

from .episode_planner import EpisodePlan
from .local_models import MAX_DRAFT_CHARS, SceneDraftResult
from .scene_planner import ScenePlan, validate_scene_plans
from .scene_writer import SceneDraftPreview

MAX_SCENES_PER_EPISODE = 100
MAX_EPISODE_DRAFT_CHARS = 1_000_000
SCENE_SEPARATOR = '\n\n'
_SHA256 = re.compile(r'[0-9a-f]{64}\Z')
_ALLOWED_ORIGINS = {
    'offline-mock-v1': 'DETERMINISTIC_MOCK_NOT_AI',
    'local-executable-v1': 'LOCAL_EXECUTABLE_OUTPUT_NOT_VERIFIED_AS_AI',
}


class EpisodeAssemblyError(ValueError):
    """Invalid or inconsistent draft metadata; never echo manuscript text."""


@dataclass(frozen=True)
class SceneSpan:
    """Python string index offsets into the assembled episode (end exclusive)."""
    scene_number: int
    start: int
    end: int
    draft_sha256: str
    prompt_sha256: str
    supporting_fact_ids: tuple[str, ...]


@dataclass(frozen=True)
class EpisodeDraftPreview:
    project_id: str
    episode_number: int
    draft: str
    draft_sha256: str
    scenes: tuple[SceneSpan, ...]
    canon_fact_ids: tuple[str, ...]
    provider: str
    origin: str
    status: str = 'DRAFT_REQUIRES_USER_APPROVAL'
    persisted: bool = False
    publication_approved: bool = False


def assemble_episode_draft(
    project_id: str,
    episode: EpisodePlan,
    scenes: tuple[ScenePlan, ...],
    previews: tuple[SceneDraftPreview, ...],
    *,
    maximum_chars: int = MAX_EPISODE_DRAFT_CHARS,
) -> EpisodeDraftPreview:
    """Merge every scene once, in plan order, preserving draft text exactly.

    Caller must provide previously generated stage-64 previews; no implicit
    regeneration or provider invocation happens. Reject mixed mock/real origins,
    altered content, unfinished scenes, and inconsistent Novel Bible provenance.
    """
    if type(project_id) is not str or not project_id.strip() or len(project_id) > 128 or '\x00' in project_id:
        raise EpisodeAssemblyError('invalid project identifier')
    if type(episode) is not EpisodePlan or episode.status != 'DRAFT_REQUIRES_USER_APPROVAL':
        raise EpisodeAssemblyError('episode plan is not a reviewable draft')
    if type(scenes) is not tuple or not 1 <= len(scenes) <= MAX_SCENES_PER_EPISODE:
        raise EpisodeAssemblyError('invalid scene count')
    if not validate_scene_plans(episode, scenes, require_details=True) or any(
        type(s) is not ScenePlan or s.status != 'DRAFT_REQUIRES_USER_APPROVAL' for s in scenes
    ):
        raise EpisodeAssemblyError('scene plans must be complete, ordered and reviewable')
    if type(previews) is not tuple or len(previews) != len(scenes):
        raise EpisodeAssemblyError('exactly one preview per scene is required')
    if type(maximum_chars) is not int or not 1 <= maximum_chars <= MAX_EPISODE_DRAFT_CHARS:
        raise EpisodeAssemblyError('invalid episode length limit')

    parts: list[str] = []
    spans: list[SceneSpan] = []
    position = 0
    common_provider = None
    common_canon = None
    common_origin = None
    for scene, preview in zip(scenes, previews):
        if type(preview) is not SceneDraftPreview or type(preview.result) is not SceneDraftResult:
            raise EpisodeAssemblyError('invalid scene draft preview')
        result = preview.result
        if (result.project_id != project_id or result.episode_number != episode.episode_number
                or type(result.scene_number) is not int or result.scene_number != scene.scene_number):
            raise EpisodeAssemblyError('scene draft belongs to a different scene or project')
        if (result.status != 'DRAFT_REQUIRES_USER_APPROVAL' or type(result.persisted) is not bool
                or result.persisted or preview.status != 'DRAFT_REQUIRES_USER_APPROVAL'
                or type(preview.persisted) is not bool or preview.persisted
                or type(preview.publication_approved) is not bool or preview.publication_approved):
            raise EpisodeAssemblyError('only unapproved, unpersisted drafts can be assembled')
        if (type(result.draft) is not str or not result.draft.strip() or '\x00' in result.draft
                or len(result.draft) > MAX_DRAFT_CHARS):
            raise EpisodeAssemblyError('invalid scene draft text')
        if (type(result.provider) is not str or result.provider not in _ALLOWED_ORIGINS
                or preview.origin != _ALLOWED_ORIGINS[result.provider]):
            raise EpisodeAssemblyError('unsupported scene draft provenance')
        if (type(preview.draft_sha256) is not str or _SHA256.fullmatch(preview.draft_sha256) is None
                or preview.draft_sha256 != sha256(result.draft.encode('utf-8')).hexdigest()
                or type(preview.prompt_sha256) is not str
                or _SHA256.fullmatch(preview.prompt_sha256) is None):
            raise EpisodeAssemblyError('scene draft provenance mismatch')
        if (type(preview.canon_fact_ids) is not tuple or not preview.canon_fact_ids
                or any(type(i) is not str or not i for i in preview.canon_fact_ids)
                or type(preview.supporting_fact_ids) is not tuple
                or any(type(i) is not str or not i for i in preview.supporting_fact_ids)):
            raise EpisodeAssemblyError('invalid Novel Bible provenance')
        if common_provider is None:
            common_provider = result.provider
            common_origin = preview.origin
            common_canon = preview.canon_fact_ids
        elif (result.provider != common_provider or preview.origin != common_origin
              or preview.canon_fact_ids != common_canon):
            raise EpisodeAssemblyError('inconsistent scene providers or Novel Bible provenance')

        if parts:
            position += len(SCENE_SEPARATOR)
        start = position
        position += len(result.draft)
        if position > maximum_chars:
            raise EpisodeAssemblyError('assembled draft exceeds limit')
        spans.append(SceneSpan(scene.scene_number, start, position,
                               preview.draft_sha256, preview.prompt_sha256,
                               preview.supporting_fact_ids))
        parts.append(result.draft)

    combined = SCENE_SEPARATOR.join(parts)
    return EpisodeDraftPreview(
        project_id=project_id, episode_number=episode.episode_number,
        draft=combined, draft_sha256=sha256(combined.encode('utf-8')).hexdigest(),
        scenes=tuple(spans), canon_fact_ids=common_canon,
        provider=common_provider, origin=common_origin,
    )
