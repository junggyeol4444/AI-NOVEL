"""Read-only per-episode bridge from author facts to persisted QC and review.

Author-marked facts cover only their declared scope. They never certify all
prose, originality, human review or publication. No AI or SQLite writes.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .database.episodes import EpisodeStore
from .author_fact_ledger import read_author_facts
from .manual_review_gate import review_state
from .review_worklist import get_review_worklist


@dataclass(frozen=True)
class FactReviewChapter:
    episode: int
    final_revision: int | None
    active_facts: int
    stale_facts: int
    conflicting_keys: int
    excluded_future_or_outside: int
    qc_unresolved: int
    human_review_current: bool
    blockers: tuple[str, ...]
    status: str = 'RELEASE_BLOCKED'
    publication_approved: bool = False


@dataclass(frozen=True)
class FactReviewMatrix:
    project_id: str
    through_episode: int
    chapters: tuple[FactReviewChapter, ...]
    attention_count: int
    status: str = 'AUTHOR_FACT_SCOPE_ONLY_NOT_CERTIFIED'
    publication_approved: bool = False


def build_author_fact_review_matrix(
    store: EpisodeStore, project_id: str, *, through_episode: int,
    fact_folder: str | Path | None,
) -> FactReviewMatrix:
    if not isinstance(store, EpisodeStore) or type(project_id) is not str or not project_id:
        raise ValueError('기존 작품을 먼저 열어야 합니다.')
    if type(through_episode) is not int or not 1 <= through_episode <= 1000:
        raise ValueError('검토 회차 범위는 1~1000화입니다.')
    store.get_project(project_id)
    saved = {row.episode: row for row in store.list_episodes(project_id)}
    work = {row.episode: row for row in get_review_worklist(store, project_id).chapters}
    facts = read_author_facts(fact_folder, project_id) if fact_folder is not None else ()
    valid_source = {}
    for fact in facts:
        source = saved.get(fact.source_episode)
        valid_source[fact.fact_id] = bool(
            source is not None and source.final_text.strip() and
            source.revision == fact.source_revision and
            sha256(source.final_text.encode('utf-8')).hexdigest() == fact.source_sha256)
    chapters = []
    for number in range(1, through_episode + 1):
        row = saved.get(number)
        blockers = []
        if row is None or not row.final_text.strip():
            blockers.append('MISSING_FINAL')
        active, stale, excluded = [], 0, 0
        for fact in facts:
            if fact.retracted:
                continue
            if fact.source_episode >= number or not fact.valid_from <= number <= fact.valid_until:
                excluded += 1
                continue
            if not valid_source[fact.fact_id]:
                stale += 1
                continue
            active.append(fact)
        groups: dict[tuple[str, str, str], set[str]] = {}
        for fact in active:
            key = (fact.kind, fact.subject.casefold(), fact.predicate.casefold())
            groups.setdefault(key, set()).add(fact.value)
        conflicts = sum(len(values) > 1 for values in groups.values())
        if fact_folder is None:
            blockers.append('AUTHOR_FACT_LEDGER_NOT_SELECTED')
        elif not active:
            blockers.append('NO_APPLICABLE_AUTHOR_FACT_EVIDENCE')
        if stale:
            blockers.append('STALE_AUTHOR_FACT_SOURCE')
        if conflicts:
            blockers.append('CONFLICTING_AUTHOR_FACTS')
        qc = work.get(number)
        qc_unresolved = (len(qc.missing_checks) + len(qc.stale_checks) +
                         len(qc.pending_checks) + len(qc.failed_checks)) if qc else 10
        if qc_unresolved:
            blockers.append('QC_NOT_COMPLETE_OR_CURRENT')
        reviewed = False
        if row is not None and row.final_text.strip():
            state = review_state(store, project_id, number)
            reviewed = (state.status.startswith('REVIEWED_') and
                        not state.incomplete_checks)
        if not reviewed:
            blockers.append('HUMAN_REVIEW_NOT_CURRENT')
        # A scoped annotation never proves the absence of unmarked errors.
        blockers.append('UNMARKED_PROSE_NOT_CERTIFIED')
        blockers.append('SEPARATE_PUBLICATION_APPROVAL_REQUIRED')
        chapters.append(FactReviewChapter(
            number, row.revision if row else None, len(active), stale,
            conflicts, excluded, qc_unresolved, reviewed, tuple(blockers)))
    return FactReviewMatrix(project_id, through_episode, tuple(chapters),
                            sum(bool(ch.blockers) for ch in chapters))
