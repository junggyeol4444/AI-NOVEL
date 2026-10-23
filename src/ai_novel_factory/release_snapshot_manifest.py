"""Local publication-readiness manifest; no publication, export or upload.

A stored final chapter, current QC and separate author authorization must
all match the exact project snapshot. This only builds an in-memory manifest.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from .publication_release_gate import publication_authorization_state


@dataclass(frozen=True)
class ReleaseSnapshotManifest:
    through_episode: int
    snapshot_sha256: str
    approved: bool
    chapters: tuple[tuple[int, str], ...]
    missing_or_unreviewed: tuple[int, ...]
    status: str
    exported: bool = False
    uploaded: bool = False
    published: bool = False


def plan_release_snapshot(store, project_id: str, *, through_episode: int) -> ReleaseSnapshotManifest:
    """Read stored chapter hashes; never copy prose or turn QC into consent."""
    state = publication_authorization_state(
        store, project_id, through_episode=through_episode)
    if not state.publication_approved or state.incomplete_episodes:
        return ReleaseSnapshotManifest(
            through_episode, state.source_sha256, False, (),
            state.incomplete_episodes, 'RELEASE_BLOCKED_NO_CURRENT_AUTHOR_AUTHORIZATION')
    saved = {row.episode: row for row in store.list_episodes(project_id)}
    chapters = []
    for number in range(1, through_episode + 1):
        row = saved.get(number)
        if row is None or not row.final_text.strip():
            return ReleaseSnapshotManifest(
                through_episode, state.source_sha256, False, (), (number,),
                'RELEASE_BLOCKED_MISSING_FINAL')
        chapters.append((number, sha256(row.final_text.encode('utf-8')).hexdigest()))
    # Read the authorization again after hashing all final texts; fail closed
    # when another window changed a manuscript or its human/QC review.
    current = publication_authorization_state(
        store, project_id, through_episode=through_episode)
    if (not current.publication_approved or
            current.source_sha256 != state.source_sha256):
        return ReleaseSnapshotManifest(
            through_episode, current.source_sha256, False, (),
            current.incomplete_episodes, 'RELEASE_BLOCKED_CHANGED_SNAPSHOT')
    return ReleaseSnapshotManifest(
        through_episode, state.source_sha256, True, tuple(chapters), (),
        'LOCAL_MANIFEST_AUTHORIZED_NOT_PUBLISHED')
