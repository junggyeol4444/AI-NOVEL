"""Read-only per-episode reference similarity scope and evidence coverage.

A PASS is scoped to the recorded comparison, never copyright clearance,
full semantic originality, human review or publication approval.
"""
from __future__ import annotations

from dataclasses import dataclass
from .database.episodes import EpisodeStore


@dataclass(frozen=True)
class ReferenceEpisodeCoverage:
    episode: int
    content_revision: int | None
    status: str
    selected: int
    compared: int
    groups: int
    unexamined: int
    direct_overlap_flagged: int
    explanation: str
    human_review_required: bool = True
    publication_approved: bool = False


@dataclass(frozen=True)
class ReferenceCoverageSummary:
    project_id: str
    through_episode: int
    chapters: tuple[ReferenceEpisodeCoverage, ...]
    not_examined: int
    incomplete: int
    blocked_or_failed: int
    checked_scope_only: int
    publication_approved: bool = False


def _numbers(detail: str) -> dict[str, int]:
    values = {}
    for part in detail.split(';'):
        if '=' not in part:
            continue
        key, raw = part.split('=', 1)
        if key in {'selected', 'compared', 'groups', 'unexamined', 'flagged', 'blocked'}:
            if not raw.isdecimal() or len(raw) > 10:
                return {}
            values[key] = int(raw)
    return values


def summarize_reference_coverage(store: EpisodeStore, project_id: str, *,
                                 through_episode: int) -> ReferenceCoverageSummary:
    if not isinstance(store, EpisodeStore):
        raise ValueError('기존 작품 DB를 열어야 합니다.')
    if type(through_episode) is not int or not 1 <= through_episode <= 1000:
        raise ValueError('참고작 검사 조회 회차는 1~1000화입니다.')
    episodes = {item.episode: item for item in store.list_episodes(project_id)}
    chapters = []
    for number in range(1, through_episode + 1):
        ep = episodes.get(number)
        if ep is None:
            chapters.append(ReferenceEpisodeCoverage(number, None, 'NOT_RUN', 0, 0, 0,
                                                      0, 0, '저장된 회차 없음'))
            continue
        records = [item for item in store.list_checks(project_id, number)
                   if item.category == 'reference_similarity']
        current = [item for item in records if item.content_revision == ep.revision]
        if not current:
            status = 'STALE' if records else 'NOT_RUN'
            chapters.append(ReferenceEpisodeCoverage(number, ep.revision, status, 0, 0,
                                                      0, 0, 0, '현재 원고 검사 기록 없음'))
            continue
        latest = current[-1]
        values = _numbers(latest.note)
        selected = values.get('selected', 0)
        compared = values.get('compared', 0)
        groups = values.get('groups', 0)
        unexamined = values.get('unexamined', 0)
        flagged = values.get('flagged', 0)
        blocked = values.get('blocked', 0)
        if latest.outcome == 'FAIL' or blocked:
            status = 'BLOCKED_OR_FAILED'
        elif latest.outcome == 'NOT_RUN':
            status = 'NOT_RUN'
        elif (not values or selected == 0 or compared != selected
              or groups == 0 or unexamined > 0):
            status = 'INCOMPLETE'
        elif latest.outcome == 'PASS':
            status = 'CHECKED_SCOPE_ONLY'
        else:
            status = 'INCOMPLETE'
        chapters.append(ReferenceEpisodeCoverage(number, ep.revision, status,
                        selected, compared, groups, unexamined, flagged,
                        '검사 범위 외 의미·구조·저작권 검토는 별도 작가 확인 필요'))
    rows = tuple(chapters)
    return ReferenceCoverageSummary(
        project_id, through_episode, rows,
        sum(r.status in {'NOT_RUN', 'STALE'} for r in rows),
        sum(r.status == 'INCOMPLETE' for r in rows),
        sum(r.status == 'BLOCKED_OR_FAILED' for r in rows),
        sum(r.status == 'CHECKED_SCOPE_ONLY' for r in rows))
