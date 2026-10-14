"""Stage 88 / ANF-REQ-061: offline, conservative ending-readiness inspection.

Only explicit local Novel Bible, foreshadow, chronology, episode and conflict
records are examined. This is not natural-language interpretation, author
approval, a manuscript finalization API or a publication gate integration.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import json
import sqlite3
from uuid import uuid4

from .database.novel_bible import NovelBibleStore, NovelBibleError, _id, _now, _revision, _text
from .database.foreshadow import ForeshadowStore, ForeshadowError
from .database.event_timeline import EventTimelineStore, TimelineError
from .database.episodes import EpisodeStore, EpisodeError


class EndingAuditError(NovelBibleError):
    """Never includes manuscript, titles, paths, or secret contents."""


@dataclass(frozen=True)
class ConflictRecord:
    project_id: str
    conflict_id: str
    title: str
    opened_episode: int
    closed_episode: int | None
    status: str
    revision: int


@dataclass(frozen=True)
class EndingFinding:
    code: str
    item_ids: tuple[str, ...]
    blocking: bool = True


@dataclass(frozen=True)
class EndingReport:
    project_id: str
    ending_episode: int
    project_revision: int
    foreshadow_count: int
    conflict_count: int
    timeline_event_count: int
    final_manuscript_count: int
    findings: tuple[EndingFinding, ...]
    evidence_digest: str
    ready_for_human_review: bool
    status: str = 'NOT_FINALIZED_REQUIRES_USER_APPROVAL'


def _ep(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 1000:
        raise EndingAuditError('완결 회차 범위가 올바르지 않습니다.')
    return value


def _record(row: sqlite3.Row) -> ConflictRecord:
    try:
        item = ConflictRecord(*(row[k] for k in ('project_id', 'conflict_id', 'title',
            'opened_episode', 'closed_episode', 'status', 'revision')))
        _id(item.project_id)
        _id(item.conflict_id)
        _text(item.title, title=True)
        _ep(item.opened_episode)
        if item.closed_episode is not None:
            _ep(item.closed_episode)
        if item.status not in ('OPEN', 'RESOLVED', 'ABANDONED'):
            raise ValueError
        if (item.status == 'OPEN') != (item.closed_episode is None):
            raise ValueError
        if item.closed_episode is not None and item.closed_episode < item.opened_episode:
            raise ValueError
        _revision(item.revision)
        return item
    except (KeyError, IndexError, TypeError, ValueError, NovelBibleError):
        raise EndingAuditError('저장된 갈등 기록이 손상되었습니다.') from None


class EndingReviewStore(NovelBibleStore):
    """Local conflict inventory plus read-only cross-store ending audit.

    A real filesystem-backed DB is required to share canon among the existing
    independent SQLite stores; ':memory:' would create *different* databases.
    No method marks a work final, changes final_text, or publishes anything.
    """

    def __init__(self, database_path: str | Path):
        path = str(database_path)
        if path == ':memory:':
            raise EndingAuditError('완결 검토에는 공유 가능한 로컬 DB 파일이 필요합니다.')
        super().__init__(database_path)
        self._path = path
        # Initialize existing schema without mutating user data.
        for store_type in (ForeshadowStore, EventTimelineStore, EpisodeStore):
            with store_type(path):
                pass
        with self._db:
            self._db.execute('''CREATE TABLE IF NOT EXISTS bible_ending_conflicts (
                project_id TEXT NOT NULL REFERENCES bible_projects(project_id) ON DELETE CASCADE,
                conflict_id TEXT NOT NULL CHECK(length(conflict_id)=32),
                title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
                opened_episode INTEGER NOT NULL CHECK(opened_episode BETWEEN 1 AND 1000),
                closed_episode INTEGER CHECK(closed_episode BETWEEN 1 AND 1000),
                status TEXT NOT NULL CHECK(status IN ('OPEN','RESOLVED','ABANDONED')),
                revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 2147483647),
                PRIMARY KEY(project_id, conflict_id),
                CHECK((status='OPEN') = (closed_episode IS NULL)),
                CHECK(closed_episode IS NULL OR closed_episode >= opened_episode)
            )''')

    def create_conflict(self, project_id: str, *, title: str,
                        opened_episode: int) -> ConflictRecord:
        project_id, opened_episode = _id(project_id), _ep(opened_episode)
        try:
            title = _text(title, title=True)
        except NovelBibleError:
            raise EndingAuditError('갈등 제목 형식이 올바르지 않습니다.') from None
        conflict_id = uuid4().hex
        with self._db:
            self._db.execute('BEGIN IMMEDIATE')
            self.get_project(project_id)
            if self._db.execute('SELECT COUNT(*) FROM bible_ending_conflicts WHERE project_id=?',
                                (project_id,)).fetchone()[0] >= 512:
                raise EndingAuditError('갈등 기록 한도를 초과했습니다.')
            self._db.execute('''INSERT INTO bible_ending_conflicts VALUES
                (?, ?, ?, ?, NULL, 'OPEN', 1)''', (project_id, conflict_id, title, opened_episode))
            self._db.execute('UPDATE bible_projects SET revision=revision+1 WHERE project_id=?',
                             (project_id,))
        return self.get_conflict(project_id, conflict_id)

    def get_conflict(self, project_id: str, conflict_id: str) -> ConflictRecord:
        project_id, conflict_id = _id(project_id), _id(conflict_id)
        self.get_project(project_id)
        row = self._db.execute('''SELECT * FROM bible_ending_conflicts
            WHERE project_id=? AND conflict_id=?''', (project_id, conflict_id)).fetchone()
        if row is None:
            raise EndingAuditError('갈등 기록을 찾을 수 없습니다.')
        return _record(row)

    def list_conflicts(self, project_id: str) -> tuple[ConflictRecord, ...]:
        project_id = _id(project_id)
        self.get_project(project_id)
        rows = self._db.execute('''SELECT * FROM bible_ending_conflicts
            WHERE project_id=? ORDER BY opened_episode, conflict_id''', (project_id,))
        result = tuple(_record(row) for row in rows)
        if len(result) > 512:
            raise EndingAuditError('갈등 기록 한도를 초과했습니다.')
        return result

    def close_conflict(self, project_id: str, conflict_id: str, *,
                       closed_episode: int, outcome: str,
                       expected_revision: int) -> ConflictRecord:
        project_id, conflict_id = _id(project_id), _id(conflict_id)
        closed_episode = _ep(closed_episode)
        if type(outcome) is not str or outcome not in ('RESOLVED', 'ABANDONED'):
            raise EndingAuditError('갈등 종료 유형이 올바르지 않습니다.')
        expected_revision = _revision(expected_revision)
        with self._db:
            self._db.execute('BEGIN IMMEDIATE')
            current = self.get_conflict(project_id, conflict_id)
            if current.revision != expected_revision or current.status != 'OPEN':
                raise EndingAuditError('갈등 기록이 변경되었거나 이미 종료되었습니다.')
            if closed_episode < current.opened_episode:
                raise EndingAuditError('갈등 종료 회차가 시작 회차보다 빠릅니다.')
            cursor = self._db.execute('''UPDATE bible_ending_conflicts
                SET closed_episode=?, status=?, revision=revision+1
                WHERE project_id=? AND conflict_id=? AND revision=? AND status='OPEN' ''',
                (closed_episode, outcome, project_id, conflict_id, expected_revision))
            if cursor.rowcount != 1:
                raise EndingAuditError('갈등 기록이 변경되었습니다.')
            self._db.execute('UPDATE bible_projects SET revision=revision+1 WHERE project_id=?',
                             (project_id,))
        return self.get_conflict(project_id, conflict_id)

    def inspect_ending(self, project_id: str, ending_episode: int, *,
                       foreshadow_inventory_reviewed: bool = False,
                       conflict_inventory_reviewed: bool = False,
                       timeline_inventory_reviewed: bool = False) -> EndingReport:
        """Fail closed on missing human inventory declarations or uncertain facts.

        Inventory flags are caller assertions, not authenticated approval.
        A clear report is ONLY ready for human review, never finalization.
        """
        project_id, ending_episode = _id(project_id), _ep(ending_episode)
        for flag in (foreshadow_inventory_reviewed, conflict_inventory_reviewed,
                     timeline_inventory_reviewed):
            if type(flag) is not bool:
                raise EndingAuditError('검토 범위 확인값이 올바르지 않습니다.')
        revision_before = self.get_project(project_id).revision
        findings: list[EndingFinding] = []
        evidence: dict[str, object] = {'project_id': project_id, 'ending_episode': ending_episode,
                                      'project_revision': revision_before}

        def add(code: str, ids=()):
            findings.append(EndingFinding(code, tuple(sorted(ids))))

        if not foreshadow_inventory_reviewed:
            add('FORESHADOW_INVENTORY_NOT_REVIEWED')
        if not conflict_inventory_reviewed:
            add('CONFLICT_INVENTORY_NOT_REVIEWED')
        if not timeline_inventory_reviewed:
            add('TIMELINE_INVENTORY_NOT_REVIEWED')

        with ForeshadowStore(self._path) as store:
            try:
                store.audit(project_id)
                threads = store.list_threads(project_id)
                states = []
                for thread in threads:
                    history = store.history(project_id, thread.thread_id)
                    relevant = [event for event in history if event.episode <= ending_episode]
                    future = [event for event in history if event.episode > ending_episode]
                    if future:
                        add('FORESHADOW_AFTER_ENDING', (thread.thread_id,))
                    if not relevant:
                        add('FORESHADOW_NOT_INSTALLED_BY_ENDING', (thread.thread_id,))
                        status = 'NOT_INSTALLED'
                    else:
                        status = store.get_at(project_id, thread.thread_id, ending_episode).status
                        if status in ('OPEN', 'DEVELOPING'):
                            add('FORESHADOW_UNRESOLVED', (thread.thread_id,))
                        elif status == 'ABANDONED':
                            add('FORESHADOW_ABANDONED_NEEDS_REVIEW', (thread.thread_id,))
                    states.append((thread.thread_id, thread.revision, status,
                                   [(event.episode, event.action, event.sequence) for event in history]))
                evidence['foreshadow'] = states
            except ForeshadowError:
                threads = ()
                add('FORESHADOW_DATA_INVALID')
                evidence['foreshadow'] = 'INVALID'

        conflicts = self.list_conflicts(project_id)
        evidence['conflicts'] = [(c.conflict_id, c.revision, c.opened_episode,
                                  c.closed_episode, c.status) for c in conflicts]
        for c in conflicts:
            if c.opened_episode > ending_episode or (
                    c.closed_episode is not None and c.closed_episode > ending_episode):
                add('CONFLICT_EVENT_AFTER_ENDING', (c.conflict_id,))
            elif c.status == 'OPEN':
                add('CONFLICT_UNRESOLVED', (c.conflict_id,))
            elif c.status == 'ABANDONED':
                add('CONFLICT_ABANDONED_NEEDS_REVIEW', (c.conflict_id,))

        with EventTimelineStore(self._path) as store:
            try:
                audit = store.audit(project_id)
                events = store.list_events(project_id)
                evidence['timeline'] = [(e.event_id, e.revision, e.when,
                                         e.anchor_event_id, e.offset_minutes) for e in events]
                evidence['timeline_checked_pairs'] = audit.checked_pairs
                if audit.unresolved_event_ids:
                    add('TIMELINE_UNKNOWN_DATES_NEEDS_REVIEW', audit.unresolved_event_ids)
                timeline_count = audit.event_count
            except TimelineError:
                add('TIMELINE_INVALID')
                evidence['timeline'] = 'INVALID'
                timeline_count = 0

        with EpisodeStore(self._path) as store:
            try:
                episodes = store.list_episodes(project_id)
                by_number = {e.episode: e for e in episodes}
                missing = [str(i) for i in range(1, ending_episode + 1)
                           if i not in by_number or not by_number[i].final_text.strip()]
                if missing:
                    add('ENDING_MANUSCRIPTS_MISSING', missing)
                if any(e.episode > ending_episode and (e.draft or e.final_text) for e in episodes):
                    add('MANUSCRIPT_AFTER_ENDING')
                final_count = sum(bool(e.final_text.strip()) for e in episodes
                                  if e.episode <= ending_episode)
                evidence['episodes'] = [(e.episode, e.revision,
                    sha256(e.final_text.encode('utf-8')).hexdigest()) for e in episodes]
            except EpisodeError:
                add('EPISODE_DATA_INVALID')
                final_count = 0
                evidence['episodes'] = 'INVALID'

        revision_after = self.get_project(project_id).revision
        if revision_after != revision_before:
            add('CONCURRENT_CANON_CHANGE')
        findings.sort(key=lambda f: (f.code, f.item_ids))
        evidence['inventory_flags'] = (foreshadow_inventory_reviewed,
                                        conflict_inventory_reviewed, timeline_inventory_reviewed)
        evidence['findings'] = [(f.code, f.item_ids) for f in findings]
        digest = sha256(json.dumps(evidence, sort_keys=True, ensure_ascii=False,
                                   separators=(',', ':')).encode('utf-8')).hexdigest()
        return EndingReport(project_id, ending_episode, revision_after, len(threads),
                            len(conflicts), timeline_count, final_count,
                            tuple(findings), digest, not findings)

    def require_current_review(self, report: EndingReport, *,
                               foreshadow_inventory_reviewed: bool,
                               conflict_inventory_reviewed: bool,
                               timeline_inventory_reviewed: bool) -> EndingReport:
        """Reject blocked/stale reviews; DOES NOT change manuscript state."""
        if type(report) is not EndingReport or not report.ready_for_human_review:
            raise EndingAuditError('완결 검토에 미해결 항목이 있습니다.')
        current = self.inspect_ending(report.project_id, report.ending_episode,
            foreshadow_inventory_reviewed=foreshadow_inventory_reviewed,
            conflict_inventory_reviewed=conflict_inventory_reviewed,
            timeline_inventory_reviewed=timeline_inventory_reviewed)
        if not current.ready_for_human_review or current.evidence_digest != report.evidence_digest:
            raise EndingAuditError('완결 검토 근거가 변경되었거나 검사에 실패했습니다.')
        return current
