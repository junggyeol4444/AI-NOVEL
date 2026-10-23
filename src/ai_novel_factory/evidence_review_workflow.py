"""Explicit offline author evidence review for the EXISTING episode database.

This is application feature code, not a completed quality verification. It
only reviews spans the author annotated in a local JSON manifest. A positive
result for those spans NEVER certifies the unmarked prose or publication.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path

from .continuity_checker import load_continuity_canon
from .database.novel_bible import NovelBibleStore
from .database.characters import CharacterStore
from .database.world_canon import WorldCanonStore
from .database.episodes import EpisodeStore
from .database.character_knowledge import CharacterKnowledgeStore
from .database.foreshadow import ForeshadowStore
from .database.event_timeline import EventTimelineStore
from .episode_evidence_bundle import evaluate_evidence_bundle, EvidenceBundle
from .evidence_manifest import load_evidence_manifest


class EvidenceReviewWorkflowError(ValueError):
    """Errors do not contain a user's manuscript, reference work or path."""


@dataclass(frozen=True)
class EvidenceReviewPlan:
    project_id: str
    episode: int
    source: str
    revision: int
    manuscript_sha256: str
    project_revision: int
    status: str = 'AWAITING_AUTHOR_EVIDENCE'
    publication_approved: bool = False


def _source_text(store: EpisodeStore, project_id: str, episode: int,
                 source: str):
    if not isinstance(store, EpisodeStore) or type(project_id) is not str:
        raise EvidenceReviewWorkflowError('기존 작품 저장소가 필요합니다.')
    if type(episode) is not int or not 1 <= episode <= 1_000_000:
        raise EvidenceReviewWorkflowError('회차가 올바르지 않습니다.')
    if source not in ('final', 'draft'):
        raise EvidenceReviewWorkflowError('원고 유형이 올바르지 않습니다.')
    row = store.get_episode(project_id, episode)
    manuscript = row.final_text if source == 'final' else row.draft
    if not manuscript.strip():
        raise EvidenceReviewWorkflowError('선택한 원고가 저장되어 있지 않습니다.')
    return row, manuscript


def plan_evidence_review(store: EpisodeStore, project_id: str,
                         episode: int, *, source: str = 'final') -> EvidenceReviewPlan:
    row, manuscript = _source_text(store, project_id, episode, source)
    revision = store.get_project(project_id).revision
    return EvidenceReviewPlan(project_id, episode, source, row.revision,
                              sha256(manuscript.encode('utf-8')).hexdigest(), revision)


def write_empty_evidence_manifest(store: EpisodeStore, project_id: str,
                                  episode: int, *, source: str,
                                  destination: str | Path) -> EvidenceReviewPlan:
    """Author-click-only new-file template, never an inferred claim or PASS.

    O_EXCL prevents overwriting an author's existing JSON file. The manifest
    contains hashes and empty claim arrays, NOT any manuscript text.
    """
    import os
    plan = plan_evidence_review(store, project_id, episode, source=source)
    path = Path(destination)
    if (not path.is_absolute() or path.suffix.lower() != '.json'
            or path.is_symlink() or not path.parent.is_dir()):
        raise EvidenceReviewWorkflowError('새 로컬 JSON 파일 위치를 선택해야 합니다.')
    payload = dict(version=1, project_id=project_id, episode=episode,
                   manuscript_sha256=plan.manuscript_sha256, canon=[],
                   knowledge=[], foreshadow=[], timeline_mentions=[],
                   timeline_orders=[])
    body = (json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except (OSError, ValueError):
        raise EvidenceReviewWorkflowError('기존 파일 덮어쓰기 금지: 새 이름을 선택하세요.') from None
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(body)
    except OSError:
        # A failed write is never claimed to be a complete template.
        raise EvidenceReviewWorkflowError('근거 템플릿을 완전히 저장하지 못했습니다.') from None
    return plan


def review_saved_evidence(store: EpisodeStore, database_path: str | Path,
                          project_id: str, episode: int, *, source: str,
                          manifest_path: str | Path,
                          expected: EvidenceReviewPlan) -> EvidenceBundle:
    """Run existing four *features* only when author explicitly clicks review.

    This function is not invoked during development or import. The caller
    provides the already opened existing project and its local database path.
    The result is never persisted as a generic QC PASS.
    """
    if type(expected) is not EvidenceReviewPlan:
        raise EvidenceReviewWorkflowError('원고 근거 확인을 다시 시작해야 합니다.')
    before = plan_evidence_review(store, project_id, episode, source=source)
    if before != expected:
        raise EvidenceReviewWorkflowError('원고 또는 설정이 바뀌어 근거 확인을 중단했습니다.')
    db_path = Path(database_path)
    if (not db_path.is_absolute() or db_path.is_symlink()
            or not db_path.is_file()):
        raise EvidenceReviewWorkflowError('기존 로컬 DB 파일을 확인하지 못했습니다.')
    row, manuscript = _source_text(store, project_id, episode, source)
    manifest = load_evidence_manifest(manifest_path, manuscript=manuscript,
                                      project_id=project_id, episode=episode)
    if manifest.manuscript_sha256 != before.manuscript_sha256:
        raise EvidenceReviewWorkflowError('근거 파일과 원고가 다릅니다.')
    with (NovelBibleStore(db_path) as bible,
          CharacterStore(db_path) as characters,
          WorldCanonStore(db_path) as world,
          CharacterKnowledgeStore(db_path) as knowledge,
          ForeshadowStore(db_path) as foreshadow,
          EventTimelineStore(db_path) as timeline):
        canon = load_continuity_canon(project_id, bible=bible,
                                     characters=characters, world=world)
        result = evaluate_evidence_bundle(
            project_id=project_id, episode=episode, manuscript=manuscript,
            expected_manuscript_sha256=before.manuscript_sha256,
            expected_project_revision=before.project_revision, canon=canon,
            knowledge_store=knowledge, foreshadow_store=foreshadow,
            timeline_store=timeline, annotations=manifest.annotations)
    after = plan_evidence_review(store, project_id, episode, source=source)
    if before != after or row.revision != after.revision:
        raise EvidenceReviewWorkflowError('확인 중 원고가 변경되어 결과를 폐기했습니다.')
    return result
