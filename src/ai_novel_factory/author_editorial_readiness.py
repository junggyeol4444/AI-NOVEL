"""작가가 직접 선택한 편집 이슈 기록과 저장 원고의 회차별 미완료 작업.

기존 SQLite 및 편집 이슈 JSON을 읽기만 한다. QC 합격·저작권·출판 승인 판정은 없다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path

from .author_workflow_dependencies import build_author_workflow_dependencies
from .database.episodes import EpisodeStore
from .editorial_issue_ledger import EditorialIssueError, _read_events


class EditorialReadinessError(ValueError):
    """개인 원고·경로·편집 메모를 포함하지 않는 오류."""


@dataclass(frozen=True)
class EditorialReadinessChapter:
    episode: int
    revision: int | None
    final_present: bool
    open_issues: int
    stale_closures: int
    closed_current: int
    review_status: str
    reference_status: str
    remaining_actions: tuple[str, ...]
    state: str


@dataclass(frozen=True)
class EditorialReadinessMatrix:
    project_id: str = field(repr=False)
    through_episode: int = 0
    chapters: tuple[EditorialReadinessChapter, ...] = ()
    pending_issues: int = 0
    missing_final: int = 0
    fingerprint: str = field(default='', repr=False)
    publication_approved: bool = False


def _issue_counts(events: list[dict], project_id: str, through: int) -> dict[int, tuple[int, int, int]]:
    opens: dict[str, dict] = {}
    closes: dict[str, list[dict]] = {}
    for event in events:
        if event['project_id'] != project_id or not 1 <= event['episode'] <= through:
            continue
        key = event['issue_id']
        if event['kind'] == 'OPEN':
            if key in opens:
                raise EditorialReadinessError('중복 편집 이슈 기록을 확인하세요.')
            opens[key] = event
        else:
            closes.setdefault(key, []).append(event)
    if set(closes) - set(opens):
        raise EditorialReadinessError('원본이 없는 편집 이슈 종료 기록이 있습니다.')
    counts: dict[int, list[int]] = {}
    for key, opening in opens.items():
        ep = opening['episode']
        if any(event['episode'] != ep for event in closes.get(key, ())):
            raise EditorialReadinessError('편집 이슈 회차 연결이 일치하지 않습니다.')
        bucket = counts.setdefault(ep, [0, 0, 0])
        # 현재 최종본과의 일치 여부는 아래에서 재검사한다.
        bucket[0] += 1
    return {ep: tuple(v) for ep, v in counts.items()}


def build_editorial_readiness_matrix(
    store: EpisodeStore, project_id: str, *, through_episode: int,
    issue_folder: str | Path,
) -> EditorialReadinessMatrix:
    """원고/검수/참고작/편집 기록을 한 번의 읽기 전용 조회로 묶는다."""
    if (not isinstance(store, EpisodeStore) or type(project_id) is not str
            or not project_id or type(through_episode) is not int
            or not 1 <= through_episode <= 1000):
        raise EditorialReadinessError('기존 작품과 1~1000화 범위를 확인하세요.')
    workflow = build_author_workflow_dependencies(
        store, project_id, through_episode=through_episode)
    try:
        events = _read_events(issue_folder)
    except (EditorialIssueError, OSError, ValueError) as exc:
        raise EditorialReadinessError('선택한 로컬 편집 기록을 읽을 수 없습니다.') from exc
    _issue_counts(events, project_id, through_episode)  # 중복/연결이 잘못된 기록 거부
    grouped: dict[int, dict[str, object]] = {}
    for event in events:
        if event['project_id'] != project_id or not 1 <= event['episode'] <= through_episode:
            continue
        data = grouped.setdefault(event['episode'], {'opens': {}, 'closes': {}})
        if event['kind'] == 'OPEN':
            data['opens'][event['issue_id']] = event
        else:
            data['closes'].setdefault(event['issue_id'], []).append(event)
    rows = []
    digest_records = []
    for chapter in workflow.chapters:
        bucket = grouped.get(chapter.episode, {'opens': {}, 'closes': {}})
        open_count = stale_count = closed_count = 0
        for key, opening in bucket['opens'].items():
            closings = sorted(bucket['closes'].get(key, ()),
                              key=lambda e: (e['created_at'], e['event_id']))
            last = closings[-1] if closings else None
            if last is None:
                open_count += 1
            elif (chapter.revision is not None and chapter.final_present
                  and last['revision'] == chapter.revision
                  and last['final_sha256'] == chapter.manuscript_sha256):
                closed_count += 1
            else:
                stale_count += 1
            digest_records.append((chapter.episode, key, opening['revision'],
                                   opening['final_sha256'], opening['category'],
                                   opening['note'], opening['created_at'],
                                   tuple((e['event_id'], e['revision'], e['final_sha256'],
                                          e['created_at']) for e in closings)))
        if not chapter.final_present:
            state = '최종본 없음'
        elif open_count or stale_count:
            state = '편집 이슈 재검토 필요'
        else:
            state = '편집 기록상 미해결 이슈 없음 (승인 아님)'
        rows.append(EditorialReadinessChapter(
            chapter.episode, chapter.revision, chapter.final_present,
            open_count, stale_count, closed_count, chapter.review_status,
            chapter.reference_status, chapter.remaining_actions, state))
    signature = (
        project_id, through_episode,
        tuple((c.episode, c.revision, c.manuscript_sha256,
               c.review_status, c.reference_status, c.remaining_actions)
              for c in workflow.chapters),
        tuple(sorted(digest_records)),
    )
    fingerprint = sha256(json.dumps(signature, ensure_ascii=False,
                                   separators=(',', ':')).encode('utf-8')).hexdigest()
    return EditorialReadinessMatrix(
        project_id, through_episode, tuple(rows),
        sum(c.open_issues + c.stale_closures for c in rows),
        sum(not c.final_present for c in rows), fingerprint)


def require_current_editorial_readiness(
    snapshot: EditorialReadinessMatrix, store: EpisodeStore, project_id: str,
    *, issue_folder: str | Path,
) -> None:
    """화면 이동 전 원고·QC·검수·참고작·편집 기록 변경을 다시 확인한다."""
    if not isinstance(snapshot, EditorialReadinessMatrix) or snapshot.project_id != project_id:
        raise EditorialReadinessError('작품이 변경됐습니다. 다시 조회하세요.')
    current = build_editorial_readiness_matrix(
        store, project_id, through_episode=snapshot.through_episode,
        issue_folder=issue_folder)
    if current.fingerprint != snapshot.fingerprint:
        raise EditorialReadinessError('원고 또는 편집 기록이 변경됐습니다. 다시 조회하세요.')