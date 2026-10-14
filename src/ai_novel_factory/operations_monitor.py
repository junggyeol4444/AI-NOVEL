"""Stage 90 / ANF-REQ-069: offline metadata-only job/error/cost monitoring.

Read paths never run jobs. Usage/cost numbers are *explicitly reported* by a caller:
there are no inferred provider prices, no network request and no automatic charge.
No traceback, error message, manuscript, prompt or credential can be recorded.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from .local_task_queue import LocalTaskQueue, _identifier


class OperationsError(ValueError):
    """Sanitized operational monitoring error."""


EVENTS = frozenset({'STARTED', 'CHECKPOINT', 'RETRIED', 'COMPLETED', 'FAILED', 'INTERRUPTED'})
ERROR_CODES = frozenset({'LOCAL_PROVIDER_TRANSIENT', 'HANDLER_EXCEPTION',
                         'CHECKPOINT_EXECUTION_FAILED', 'WORKER_INTERRUPTED',
                         'TASK_CANCELLED', 'UNEXPECTED_FAILURE', 'UNKNOWN_ERROR',
                         'RETRY_EXHAUSTED', 'SIMULATION_FAILURE'})
COST_KINDS = frozenset({'UNKNOWN', 'ESTIMATED', 'REPORTED'})
CURRENCIES = frozenset({'USD', 'KRW'})


def _safe_code(code: str | None) -> str | None:
    return code if code in ERROR_CODES else ('UNKNOWN_ERROR' if code else None)


def _utc_stamp(value: datetime | None) -> str:
    if value is None:
        value = datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise OperationsError('timezone-aware datetime required')
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds')


@dataclass(frozen=True)
class OperationalEvent:
    event_id: int
    task_id: str
    project_id: str
    episode_number: int
    event: str
    error_code: str | None
    duration_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    cost_kind: str
    cost_minor: int | None
    currency: str | None
    recorded_utc: str


@dataclass(frozen=True)
class JobStatus:
    task_id: str
    project_id: str
    episode_number: int
    status: str
    attempts: int
    progress: int
    stage: str
    error_code: str | None


@dataclass(frozen=True)
class ScheduleStatus:
    run_id: str
    task_id: str | None
    due_utc: str
    status: str
    attempts: int
    error_code: str | None


@dataclass(frozen=True)
class CostSummary:
    task_count: int
    failed_tasks: int
    event_count: int
    error_events: int
    unknown_cost_events: int
    estimated_minor_by_currency: tuple[tuple[str, int], ...]
    reported_minor_by_currency: tuple[tuple[str, int], ...]


class OperationsReader:
    """Reads existing local task queue in SQLite read-only mode; never creates it."""

    def __init__(self, path: str | Path):
        if not isinstance(path, (str, Path)) or not str(path):
            raise OperationsError('existing local database required')
        self.path = Path(path)
        if not self.path.is_file() or self.path.is_symlink():
            raise OperationsError('existing regular local database required')
        try:
            with self._connect() as db:
                if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='local_tasks'").fetchone():
                    raise OperationsError('not a local task queue')
        except sqlite3.DatabaseError:
            raise OperationsError('invalid local task queue') from None

    def _connect(self):
        # No SQLite create-if-missing semantics. 'ro' protects the source queue.
        return closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True))

    @staticmethod
    def _check_project(project_id: str | None) -> None:
        if project_id is not None and not _identifier(project_id):
            raise OperationsError('invalid project id')

    @staticmethod
    def _check_limit(limit: int) -> None:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise OperationsError('invalid result limit')

    def list_jobs(self, *, project_id: str | None = None, limit: int = 200) -> tuple[JobStatus, ...]:
        self._check_project(project_id)
        self._check_limit(limit)
        sql = ("SELECT t.task_id,t.project_id,t.episode_number,t.status,t.attempts,"
               "COALESCE(c.percent,0),COALESCE(c.stage,'PENDING'),t.error_code "
               "FROM local_tasks t LEFT JOIN task_controls c ON c.task_id=t.task_id")
        if project_id is not None:
            sql += ' WHERE t.project_id=?'
        sql += ' ORDER BY t.rowid DESC LIMIT ?'
        args = (project_id, limit) if project_id is not None else (limit,)
        try:
            with self._connect() as db:
                rows = db.execute(sql, args).fetchall()
        except sqlite3.DatabaseError:
            raise OperationsError('task history unavailable') from None
        return tuple(JobStatus(*row[:-1], _safe_code(row[-1])) for row in rows)

    def list_events(self, *, project_id: str | None = None, limit: int = 200) -> tuple[OperationalEvent, ...]:
        self._check_project(project_id)
        self._check_limit(limit)
        with self._connect() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='operation_events'").fetchone():
                return ()
            sql = ("SELECT e.event_id,e.task_id,t.project_id,t.episode_number,e.event,e.error_code,"
                   "e.duration_ms,e.input_tokens,e.output_tokens,e.cost_kind,e.cost_minor,"
                   "e.currency,e.recorded_utc FROM operation_events e "
                   "JOIN local_tasks t ON t.task_id=e.task_id")
            if project_id is not None:
                sql += ' WHERE t.project_id=?'
            sql += ' ORDER BY e.event_id DESC LIMIT ?'
            args = (project_id, limit) if project_id is not None else (limit,)
            try:
                rows = db.execute(sql, args).fetchall()
            except sqlite3.DatabaseError:
                raise OperationsError('event history unavailable') from None
        return tuple(OperationalEvent(*row[:5], _safe_code(row[5]), *row[6:]) for row in rows)

    def list_scheduled_runs(self, *, project_id: str | None = None, limit: int = 200) -> tuple[ScheduleStatus, ...]:
        self._check_project(project_id)
        self._check_limit(limit)
        with self._connect() as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'writing_schedule_runs', 'writing_schedules'} <= tables:
                return ()
            sql = ("SELECT r.run_id,r.task_id,r.due_utc,r.status,r.attempts,r.error_code "
                   "FROM writing_schedule_runs r JOIN writing_schedules s ON s.schedule_id=r.schedule_id")
            if project_id is not None:
                sql += ' WHERE s.project_id=?'
            sql += ' ORDER BY r.due_utc DESC,r.run_id DESC LIMIT ?'
            args = (project_id, limit) if project_id is not None else (limit,)
            try:
                rows = db.execute(sql, args).fetchall()
            except sqlite3.DatabaseError:
                raise OperationsError('schedule history unavailable') from None
        return tuple(ScheduleStatus(*row[:-1], _safe_code(row[-1])) for row in rows)

    def summary(self, *, project_id: str | None = None) -> CostSummary:
        """Totals all stored events (not just a paginated view), with unknown costs separate."""
        self._check_project(project_id)
        with self._connect() as db:
            filter_jobs = ' WHERE project_id=?' if project_id is not None else ''
            args = (project_id,) if project_id is not None else ()
            try:
                task_count, failed = db.execute(
                    'SELECT count(*),coalesce(sum(status IN (\'FAILED\',\'INTERRUPTED\')),0) '
                    'FROM local_tasks' + filter_jobs, args).fetchone()
                if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='operation_events'").fetchone():
                    return CostSummary(task_count, failed, 0, 0, 0, (), ())
                filt = ' WHERE t.project_id=?' if project_id is not None else ''
                base = ' FROM operation_events e JOIN local_tasks t ON t.task_id=e.task_id' + filt
                count, errors, unknown = db.execute(
                    "SELECT count(*),coalesce(sum(e.error_code IS NOT NULL),0),"
                    "coalesce(sum(e.cost_kind='UNKNOWN'),0)" + base, args).fetchone()
                rows = db.execute('SELECT e.cost_kind,e.currency,sum(e.cost_minor)'
                                  + base + (" AND" if filt else ' WHERE')
                                  + " e.cost_kind IN ('ESTIMATED','REPORTED') "
                                  'GROUP BY e.cost_kind,e.currency', args).fetchall()
            except sqlite3.DatabaseError:
                raise OperationsError('monitor summary unavailable') from None
        estimated = tuple(sorted((cur, minor) for kind, cur, minor in rows if kind == 'ESTIMATED'))
        reported = tuple(sorted((cur, minor) for kind, cur, minor in rows if kind == 'REPORTED'))
        return CostSummary(task_count, failed, count, errors, unknown, estimated, reported)


class OperationsLedger(OperationsReader):
    """Opt-in local accounting on an existing queue. Never creates or runs a task."""

    def __init__(self, queue: LocalTaskQueue):
        if type(queue) is not LocalTaskQueue:
            raise OperationsError('existing local task queue required')
        super().__init__(queue.path)
        self.queue = queue
        with queue._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS operation_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL REFERENCES local_tasks(task_id),
                event TEXT NOT NULL CHECK(event IN
                  ('STARTED','CHECKPOINT','RETRIED','COMPLETED','FAILED','INTERRUPTED')),
                error_code TEXT, duration_ms INTEGER,
                input_tokens INTEGER, output_tokens INTEGER,
                cost_kind TEXT NOT NULL CHECK(cost_kind IN ('UNKNOWN','ESTIMATED','REPORTED')),
                cost_minor INTEGER, currency TEXT,
                recorded_utc TEXT NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS operation_events_task_idx ON operation_events(task_id,event_id)')

    def record(self, task_id: str, event: str, *, error_code: str | None = None,
               duration_ms: int | None = None, input_tokens: int | None = None,
               output_tokens: int | None = None, cost_kind: str = 'UNKNOWN',
               cost_minor: int | None = None, currency: str | None = None,
               occurred_at: datetime | None = None) -> OperationalEvent:
        if not _identifier(task_id) or type(event) is not str or event not in EVENTS:
            raise OperationsError('invalid task/event identity')
        if error_code is not None and (type(error_code) is not str or error_code not in ERROR_CODES):
            raise OperationsError('use a predefined non-sensitive error code')
        if event not in ('FAILED','INTERRUPTED') and error_code is not None:
            raise OperationsError('error code only valid on failure')
        if event in ('FAILED','INTERRUPTED') and error_code is None:
            raise OperationsError('failure classification required')
        for number in (duration_ms, input_tokens, output_tokens):
            if number is not None and (type(number) is not int or not 0 <= number <= 10**12):
                raise OperationsError('invalid nonnegative measurement')
        if type(cost_kind) is not str or cost_kind not in COST_KINDS:
            raise OperationsError('invalid cost provenance')
        if cost_kind == 'UNKNOWN':
            if cost_minor is not None or currency is not None:
                raise OperationsError('unknown cost cannot have an amount')
        elif (type(cost_minor) is not int or not 0 <= cost_minor <= 10**12
              or type(currency) is not str or currency not in CURRENCIES):
            raise OperationsError('known cost requires nonnegative minor units and currency')
        stamp = _utc_stamp(occurred_at)
        with self.queue._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM local_tasks WHERE task_id=?', (task_id,)).fetchone():
                raise OperationsError('unknown task id')
            cur = db.execute('''INSERT INTO operation_events
                (task_id,event,error_code,duration_ms,input_tokens,output_tokens,
                 cost_kind,cost_minor,currency,recorded_utc)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (task_id,event,error_code,duration_ms,input_tokens,output_tokens,
                 cost_kind,cost_minor,currency,stamp))
            event_id = cur.lastrowid
        with self._connect() as db:
            row = db.execute("SELECT e.event_id,e.task_id,t.project_id,t.episode_number,"
                             "e.event,e.error_code,e.duration_ms,e.input_tokens,"
                             "e.output_tokens,e.cost_kind,e.cost_minor,e.currency,e.recorded_utc "
                             "FROM operation_events e JOIN local_tasks t ON t.task_id=e.task_id "
                             "WHERE e.event_id=?", (event_id,)).fetchone()
        if row is None:
            raise OperationsError('record lookup unavailable')
        return OperationalEvent(*row[:5], _safe_code(row[5]), *row[6:])
