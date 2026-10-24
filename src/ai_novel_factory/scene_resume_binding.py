"""Author-approved scene resume scope; no automatic model launch.

A checkpoint can only be considered by the same project, planned chapter,
current author source stamp, and the *new* launch consent configuration. It
never turns cached AI text into a final manuscript or quality certification.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from hashlib import sha256

from .author_scene_checkpoint_integrity import SceneStageChoice, _read_file

from .scene_checkpoint_store import SceneCheckpointStore, SceneCheckpointError, MAX_SCENES


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



def require_explicit_scene_resume(
        checkpoint: SceneCheckpointStore, choice: SceneStageChoice,
        *, scenes_per_episode: int) -> None:
    """작가가 선택한 마지막 임시 장면을 동일 실행 설정에서만 재사용한다."""
    if (type(checkpoint) is not SceneCheckpointStore
            or type(choice) is not SceneStageChoice
            or type(scenes_per_episode) is not int
            or not 1 <= scenes_per_episode <= MAX_SCENES
            or choice.episode != checkpoint.episode
            or not 1 <= choice.stage <= scenes_per_episode
            or choice.folder_name != checkpoint.directory.name):
        raise SceneCheckpointError('선택 장면과 현재 승인된 집필 설정이 일치하지 않습니다.')
    for stage in range(scenes_per_episode + 1):
        cached = checkpoint.load_stage(stage)
        if stage <= choice.stage and cached is None:
            raise SceneCheckpointError('선택 장면 이전의 연속 임시 기록이 없습니다.')
        if stage > choice.stage and cached is not None:
            raise SceneCheckpointError('선택 장면 뒤에 다른 임시 기록이 있습니다. 마지막 단계를 선택하세요.')
    raw = _read_file(checkpoint.directory / f'{choice.stage:02d}.json')
    if sha256(raw).hexdigest() != choice.file_sha256:
        raise SceneCheckpointError('선택 장면 파일이 변경됐습니다. 다시 조회하세요.')
