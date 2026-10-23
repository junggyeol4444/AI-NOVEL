"""작가가 선택한 장편 수정 영향 범위를 현재 저장 원고에 묶는 읽기 전용 인계.

잠재 영향은 오류 판정이나 출판 승인이 아니다. SQLite/원고/기록 수정 없음.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path

from .author_workflow_dependencies import (
    AuthorWorkflowDependencies, build_author_workflow_dependencies,
)
from .author_fact_ledger import read_author_facts
from .database.episodes import EpisodeStore
from .longform_revision_impact import RevisionImpactPlan, plan_revision_impact


class AuthorRevisionHandoffError(ValueError):
    """개인 원고나 로컬 파일 경로를 포함하지 않는 오류."""


@dataclass(frozen=True)
class AuthorRevisionHandoff:
    project_id: str = field(repr=False)
    source_episode: int = 0
    through_episode: int = 0
    plan: RevisionImpactPlan | None = field(default=None, repr=False)
    workflow: AuthorWorkflowDependencies | None = field(default=None, repr=False)
    fingerprint: str = field(default='', repr=False)
    publication_approved: bool = False
    status: str = 'REVIEW_SCOPE_ONLY_NOT_VERIFIED'


def preview_author_revision_handoff(
    store: EpisodeStore, project_id: str, *, source_episode: int,
    through_episode: int, fact_folder: str | Path | None = None,
) -> AuthorRevisionHandoff:
    """현재 회차·후속 회차·QC·참고작·작가 사실을 같은 지문으로 묶는다."""
    if not isinstance(store, EpisodeStore) or type(project_id) is not str or not project_id:
        raise AuthorRevisionHandoffError('기존 작품 SQLite를 먼저 여세요.')
    if (type(source_episode) is not int or type(through_episode) is not int
            or not 1 <= source_episode <= through_episode <= 1000):
        raise AuthorRevisionHandoffError('수정 영향 범위는 1~1000화의 순서 있는 회차입니다.')
    try:
        plan = plan_revision_impact(
            store, project_id, changed_episode=source_episode,
            through_episode=through_episode, fact_folder=fact_folder)
        workflow = build_author_workflow_dependencies(
            store, project_id, through_episode=through_episode)
        episodes = store.list_episodes(project_id)
        facts = read_author_facts(fact_folder, project_id) if fact_folder is not None else ()
    except (ValueError, OSError, LookupError) as exc:
        raise AuthorRevisionHandoffError('현재 원고·작가 사실·검수 범위를 읽지 못했습니다.') from exc
    # 각 회차의 원고 3종과 저장 revision, QC·참고작 기록, 명시된 사실 근거를
    # 모두 포함한다. 같은 revision의 외부 파일 수정도 다음 이동 시 무효화한다.
    record = (
        project_id, source_episode, through_episode,
        (plan.source_revision, plan.source_sha256),
        tuple((r.episode, r.current_revision, r.saved_final_present,
               r.linked_author_facts, r.stale_fact_sources, r.qc_requires_review,
               r.reasons) for r in plan.chapters),
        tuple((r.episode, r.revision, r.manuscript_sha256,
               r.review_status, r.reference_status, r.remaining_actions)
              for r in workflow.chapters),
        tuple((r.episode, r.revision,
               sha256(r.plot.encode('utf-8')).hexdigest(),
               sha256(r.draft.encode('utf-8')).hexdigest(),
               sha256(r.final_text.encode('utf-8')).hexdigest())
              for r in episodes if r.episode <= through_episode),
        tuple(repr(fact) for fact in facts),
    )
    fingerprint = sha256(json.dumps(record, ensure_ascii=False,
                                   separators=(',', ':')).encode('utf-8')).hexdigest()
    return AuthorRevisionHandoff(project_id, source_episode, through_episode,
                                 plan, workflow, fingerprint)


def require_current_author_revision_handoff(
    snapshot: AuthorRevisionHandoff, store: EpisodeStore, project_id: str,
    *, fact_folder: str | Path | None = None,
) -> None:
    """기존 GUI로 이동하기 직전에 현재 원고·검수·근거를 다시 읽는다."""
    if (not isinstance(snapshot, AuthorRevisionHandoff)
            or snapshot.project_id != project_id or not snapshot.fingerprint):
        raise AuthorRevisionHandoffError('작품 또는 영향 범위를 다시 선택하세요.')
    current = preview_author_revision_handoff(
        store, project_id, source_episode=snapshot.source_episode,
        through_episode=snapshot.through_episode, fact_folder=fact_folder)
    if current.fingerprint != snapshot.fingerprint:
        raise AuthorRevisionHandoffError('원고·참고작·QC·작가 사실이 변경됐습니다. 다시 조회하세요.')
