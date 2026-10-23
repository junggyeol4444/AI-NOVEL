"""Read-only downstream review scope when an author edits an existing chapter.

The author chooses a chapter; this is a *potential* dependency report, not
proof that an edit occurred or that a later chapter is inconsistent. Only the
existing project and explicitly selected local author-fact folder are read.
No AI call, automatic rewrite, QC PASS, publication approval or SQLite write.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .database.episodes import EpisodeStore
from .author_fact_ledger import read_author_facts
from .review_worklist import get_review_worklist


class RevisionImpactError(ValueError):
    """Public errors never contain manuscript prose or private file paths."""


@dataclass(frozen=True)
class ImpactedEpisode:
    episode: int
    current_revision: int | None
    saved_final_present: bool
    linked_author_facts: int
    stale_fact_sources: int
    potential_downstream: bool
    qc_requires_review: bool
    reasons: tuple[str, ...]
    status: str = 'REVIEW_SCOPE_ONLY_NOT_VERIFIED'
    publication_approved: bool = False


@dataclass(frozen=True)
class RevisionImpactPlan:
    project_id: str
    source_episode: int
    through_episode: int
    source_revision: int
    source_sha256: str
    chapters: tuple[ImpactedEpisode, ...]
    linked_fact_count: int
    possible_downstream_count: int
    status: str = 'AUTHOR_REVIEW_REQUIRED_NOT_CERTIFIED'
    publication_approved: bool = False


def plan_revision_impact(
    store: EpisodeStore, project_id: str, *, changed_episode: int,
    through_episode: int, fact_folder: str | Path | None = None,
) -> RevisionImpactPlan:
    """Show possible affected chapters without changing or certifying them.

    An author fact is an *explicit* link only if its source chapter equals the
    chosen chapter. Later chapters without links are labeled POSSIBLE rather
    than silently considered unaffected. Stale facts remain visible as risks.
    """
    if not isinstance(store, EpisodeStore) or type(project_id) is not str or not project_id:
        raise RevisionImpactError('기존 작품을 먼저 열어야 합니다.')
    if (type(changed_episode) is not int or type(through_episode) is not int
            or not 1 <= changed_episode <= through_episode <= 1000):
        raise RevisionImpactError('변경 영향 범위는 1~1000화의 기존 회차여야 합니다.')
    store.get_project(project_id)
    saved = {ep.episode: ep for ep in store.list_episodes(project_id)}
    source = saved.get(changed_episode)
    if source is None or not source.final_text.strip():
        raise RevisionImpactError('영향 기준 회차에 저장된 최종본이 필요합니다.')
    current_source_sha = sha256(source.final_text.encode('utf-8')).hexdigest()
    try:
        facts = (read_author_facts(fact_folder, project_id)
                 if fact_folder is not None else ())
        worklist = {s.episode: s for s in get_review_worklist(store, project_id).chapters}
    except (ValueError, OSError):
        raise RevisionImpactError('현재 작품의 작가 근거 또는 QC 현황을 읽지 못했습니다.') from None
    linked = tuple(f for f in facts if f.source_episode == changed_episode and not f.retracted)
    result = []
    for number in range(changed_episode, through_episode + 1):
        episode = saved.get(number)
        affecting = tuple(f for f in linked if f.valid_from <= number <= f.valid_until)
        stale = sum(f.source_revision != source.revision or
                    f.source_sha256 != current_source_sha for f in affecting)
        reasons = []
        if number == changed_episode:
            reasons.append('SELECTED_SOURCE_REVIEW')
        if affecting:
            reasons.append('EXPLICIT_AUTHOR_FACT_DEPENDENCY')
        if stale:
            reasons.append('STALE_AUTHOR_FACT_SOURCE')
        if number > changed_episode:
            reasons.append('POSSIBLE_DOWNSTREAM_IMPACT_NOT_PROVEN')
        if episode is None or not episode.final_text.strip():
            reasons.append('SAVED_FINAL_MISSING')
        status = worklist.get(number)
        qc_pending = status is None or status.needs_human_review
        if qc_pending:
            reasons.append('CURRENT_QC_OR_FINAL_INCOMPLETE')
        result.append(ImpactedEpisode(
            episode=number, current_revision=episode.revision if episode else None,
            saved_final_present=bool(episode and episode.final_text.strip()),
            linked_author_facts=len(affecting), stale_fact_sources=stale,
            potential_downstream=number > changed_episode,
            qc_requires_review=qc_pending, reasons=tuple(reasons)))
    return RevisionImpactPlan(
        project_id, changed_episode, through_episode, source.revision,
        current_source_sha, tuple(result), len(linked),
        max(0, through_episode - changed_episode))
