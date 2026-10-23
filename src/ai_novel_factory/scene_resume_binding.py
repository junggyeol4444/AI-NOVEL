"""Author-approved scene resume scope; no automatic model launch.

A checkpoint can only be considered by the same project, planned chapter,
current author source stamp, and the *new* launch consent configuration. It
never turns cached AI text into a final manuscript or quality certification.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .scene_checkpoint_store import SceneCheckpointStore, SceneCheckpointError


@dataclass(frozen=True)
class SceneResumeScope:
    database_path: Path = field(repr=False)
    project_id: str = field(repr=False)
    episode: int
    root: Path = field(repr=False)
    launch_fingerprint: str = field(repr=False)
    source_stamp: object = field(repr=False)
    plan_stamp: object = field(repr=False)
    scenes_per_episode: int

    def open_store(self) -> SceneCheckpointStore:
        if (type(self.scenes_per_episode) is not int
                or not 1 <= self.scenes_per_episode <= 20):
            raise SceneCheckpointError('재개할 장면 개수가 올바르지 않습니다.')
        return SceneCheckpointStore(
            self.root, self.database_path, self.project_id, self.episode,
            self.launch_fingerprint, self.source_stamp, self.plan_stamp)

    def preview(self) -> tuple[str, ...]:
        """Read-only stage labels. Stage 0 is the unapproved plot outline."""
        store = self.open_store()
        return tuple('CACHED_UNAPPROVED' if store.load_stage(stage) is not None
                     else 'MISSING' for stage in range(self.scenes_per_episode + 1))
