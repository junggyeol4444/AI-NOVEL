"""Stage 85 / ANF-REQ-050: offline, opt-in draft-job scheduling and audit.

Only task metadata and UTC schedule slots are persisted. A caller must invoke
``tick`` while the PC is running, and explicitly authorize ``execute_run``.
There is no OS wake-up, unattended AI execution, finalization or publication.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

from .database.episodes import MAX_EPISODES
from .local_task_queue import LocalTaskQueue, _identifier
from .retry_checkpoint import MAX_ATTEMPTS, RETRYABLE_CODES


class ScheduleError(ValueError):
    """Sanitized schedule or execution failure; never includes manuscript text."""


UTC = timezone.utc
_INTERVALS = {'ONCE': None, 'HOURLY': 3600, 'DAILY': 86400}
_STATUSES = frozenset({'QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'INTERRUPTED', 'SKIPPED_BUSY'})


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ScheduleError('timezone-aware datetime required')
    try:
        result = value.astimezone(UTC)
        if result.microsecond:
            raise ScheduleError('schedule time must use whole seconds')
        return result
    except (OverflowError, ValueError):
        raise ScheduleError('invalid schedule time') from None


def _stamp(value: datetime) -> str:
    return _utc(value).strftime('%Y-%m-%dT%H:%M:%SZ')


def _parse(value: str) -> datetime:
    return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=UTC)


def _positive(value: object, maximum: int) -> bool:
    return type(value) is int and 1 <= value <= maximum


@dataclass(frozen=True)
class Schedule:
    schedule_id: str
    project_id: str
    episode_number: int
    frequency: str
    next_due_utc: str | None
    enabled: bool
    occurrence_count: int
    max_occurrences: int | None


@dataclass(frozen=True)
class ScheduledRun:
    run_id: str
    schedule_id: str
    due_utc: str
    task_id: str | None
    status: str
    attempts: int
    error_code: str | None
    skipped_missed_slots: int
    manuscript_approved: bool = False
    published: bool = False


@dataclass(frozen=True)
class ScheduleEvent:
    event_id: int
    run_id: str
    event: str
    attempts: int
    error_code: str | None
    recorded_utc: str


class LocalWritingScheduler:
    """SQLite scheduler sharing the queue DB for atomic enqueue + audit.

    A schedule targets one explicit draft episode. Recurrence never guesses
    the next episode; stage-84 handoff remains a separate guarded operation.
    """

    def __init__(self, queue: LocalTaskQueue):
        if type(queue) is not LocalTaskQueue:
            raise ScheduleError('local queue required')
        self.queue = queue
        with queue._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS writing_schedules (
                schedule_id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                episode_number INTEGER NOT NULL CHECK(episode_number BETWEEN 1 AND 1000),
                frequency TEXT NOT NULL CHECK(frequency IN ('ONCE','HOURLY','DAILY')),
                next_due_utc TEXT, enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
                occurrence_count INTEGER NOT NULL DEFAULT 0,
                max_occurrences INTEGER CHECK(max_occurrences BETWEEN 1 AND 1000))''')
            db.execute('''CREATE TABLE IF NOT EXISTS writing_schedule_runs (
                run_id TEXT PRIMARY KEY,
                schedule_id TEXT NOT NULL REFERENCES writing_schedules(schedule_id),
                due_utc TEXT NOT NULL, task_id TEXT UNIQUE REFERENCES local_tasks(task_id),
                status TEXT NOT NULL CHECK(status IN
                  ('QUEUED','RUNNING','COMPLETED','FAILED','INTERRUPTED','SKIPPED_BUSY')),
                attempts INTEGER NOT NULL DEFAULT 0,
                error_code TEXT, skipped_missed_slots INTEGER NOT NULL DEFAULT 0,
                UNIQUE(schedule_id,due_utc))''')
            db.execute('''CREATE TABLE IF NOT EXISTS writing_schedule_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES writing_schedule_runs(run_id),
                event TEXT NOT NULL, attempts INTEGER NOT NULL,
                error_code TEXT, recorded_utc TEXT NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS writing_schedule_due_idx '
                       'ON writing_schedules(enabled,next_due_utc)')

    @staticmethod
    def _schedule(row) -> Schedule:
        return Schedule(row[0], row[1], row[2], row[3], row[4], bool(row[5]), row[6], row[7])

    @staticmethod
    def _run(row) -> ScheduledRun:
        return ScheduledRun(*row)

    def create_schedule(self, project_id: str, episode_number: int, *,
                        start_at: datetime, frequency: str = 'ONCE',
                        max_occurrences: int | None = None) -> Schedule:
        if (not _identifier(project_id) or not _positive(episode_number, MAX_EPISODES)
                or type(frequency) is not str or frequency not in _INTERVALS
                or (max_occurrences is not None and not _positive(max_occurrences, 1000))
                or (frequency == 'ONCE' and max_occurrences not in (None, 1))):
            raise ScheduleError('invalid schedule configuration')
        stamp = _stamp(start_at)
        schedule_id = uuid4().hex
        with self.queue._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('''INSERT INTO writing_schedules
                (schedule_id,project_id,episode_number,frequency,next_due_utc,enabled,
                 occurrence_count,max_occurrences) VALUES (?,?,?,?,?,1,0,?)''',
                (schedule_id, project_id, episode_number, frequency, stamp,
                 1 if frequency == 'ONCE' else max_occurrences))
        return self.get_schedule(schedule_id)

    def get_schedule(self, schedule_id: str) -> Schedule | None:
        if not _identifier(schedule_id):
            raise ScheduleError('invalid schedule id')
        with self.queue._connect() as db:
            row = db.execute('''SELECT schedule_id,project_id,episode_number,frequency,
                next_due_utc,enabled,occurrence_count,max_occurrences
                FROM writing_schedules WHERE schedule_id=?''', (schedule_id,)).fetchone()
        return self._schedule(row) if row else None

    def disable_schedule(self, schedule_id: str) -> Schedule:
        if not _identifier(schedule_id):
            raise ScheduleError('invalid schedule id')
        with self.queue._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute('UPDATE writing_schedules SET enabled=0,next_due_utc=NULL '
                                 'WHERE schedule_id=?', (schedule_id,))
            if changed.rowcount != 1:
                raise ScheduleError('schedule not found')
        return self.get_schedule(schedule_id)

    def list_runs(self, schedule_id: str) -> tuple[ScheduledRun, ...]:
        if not _identifier(schedule_id):
            raise ScheduleError('invalid schedule id')
        with self.queue._connect() as db:
            rows = db.execute('''SELECT run_id,schedule_id,due_utc,task_id,status,
                attempts,error_code,skipped_missed_slots FROM writing_schedule_runs
                WHERE schedule_id=? ORDER BY due_utc,run_id''', (schedule_id,)).fetchall()
        return tuple(map(self._run, rows))

    def get_run(self, run_id: str) -> ScheduledRun | None:
        if not _identifier(run_id):
            raise ScheduleError('invalid run id')
        with self.queue._connect() as db:
            row = db.execute('''SELECT run_id,schedule_id,due_utc,task_id,status,
                attempts,error_code,skipped_missed_slots FROM writing_schedule_runs
                WHERE run_id=?''', (run_id,)).fetchone()
        return self._run(row) if row else None

    def events(self, run_id: str) -> tuple[ScheduleEvent, ...]:
        if not _identifier(run_id):
            raise ScheduleError('invalid run id')
        with self.queue._connect() as db:
            rows = db.execute('''SELECT event_id,run_id,event,attempts,error_code,recorded_utc
                FROM writing_schedule_events WHERE run_id=? ORDER BY event_id''',
                (run_id,)).fetchall()
        return tuple(ScheduleEvent(*row) for row in rows)

    @staticmethod
    def _event(db, run_id: str, event: str, attempts: int, error_code: str | None,
               now: str) -> None:
        db.execute('''INSERT INTO writing_schedule_events
            (run_id,event,attempts,error_code,recorded_utc) VALUES (?,?,?,?,?)''',
            (run_id, event, attempts, error_code, now))

    def tick(self, *, now: datetime, dispatch_authorized: bool,
             limit: int = 25) -> tuple[ScheduledRun, ...]:
        """Atomically enqueue due metadata-only draft jobs; never run a model.

        Missed intervals while offline are not replayed. One overdue slot is
        recorded per schedule, along with how many older slots were skipped.
        A busy episode is logged as SKIPPED_BUSY without a duplicate job.
        """
        if type(dispatch_authorized) is not bool or not dispatch_authorized:
            raise ScheduleError('explicit schedule dispatch authorization required')
        if not _positive(limit, 100):
            raise ScheduleError('invalid dispatch limit')
        stamp = _stamp(now)
        current = _utc(now)
        emitted = []
        with self.queue._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute('''SELECT schedule_id,project_id,episode_number,frequency,
                next_due_utc,enabled,occurrence_count,max_occurrences
                FROM writing_schedules WHERE enabled=1 AND next_due_utc<=?
                ORDER BY next_due_utc,schedule_id LIMIT ?''', (stamp, limit)).fetchall()
            for row in rows:
                schedule = self._schedule(row)
                due = _parse(schedule.next_due_utc)
                seconds = _INTERVALS[schedule.frequency]
                skipped = 0
                next_due = None
                if seconds is not None:
                    intervals = int((current - due).total_seconds() // seconds) + 1
                    skipped = max(0, intervals - 1)
                    try:
                        next_due = _stamp(due + timedelta(seconds=intervals * seconds))
                    except (OverflowError, ValueError):
                        next_due = None
                count = schedule.occurrence_count + 1
                enabled = int(next_due is not None and
                              (schedule.max_occurrences is None or count < schedule.max_occurrences))
                db.execute('''UPDATE writing_schedules SET next_due_utc=?,enabled=?,
                    occurrence_count=? WHERE schedule_id=?''',
                    (next_due if enabled else None, enabled, count, schedule.schedule_id))
                run_id = sha256(f'ANF85|{schedule.schedule_id}|{schedule.next_due_utc}'.encode('ascii')).hexdigest()[:32]
                busy = db.execute('''SELECT 1 FROM local_tasks WHERE project_id=?
                    AND episode_number=? AND status IN ('QUEUED','RUNNING','FAILED','INTERRUPTED') LIMIT 1''',
                    (schedule.project_id, schedule.episode_number)).fetchone()
                task_id = None if busy else run_id
                status = 'SKIPPED_BUSY' if busy else 'QUEUED'
                if task_id:
                    db.execute('''INSERT INTO local_tasks
                        (task_id,project_id,episode_number,status,attempts)
                        VALUES (?,?,?,'QUEUED',0)''',
                        (task_id, schedule.project_id, schedule.episode_number))
                db.execute('''INSERT INTO writing_schedule_runs
                    (run_id,schedule_id,due_utc,task_id,status,attempts,error_code,skipped_missed_slots)
                    VALUES (?,?,?,?,?,0,NULL,?)''',
                    (run_id, schedule.schedule_id, schedule.next_due_utc, task_id, status, skipped))
                self._event(db, run_id, status, 0, None, stamp)
                emitted.append(run_id)
        return tuple(self.get_run(run_id) for run_id in emitted)

    def _observe(self, db, run_id: str, stamp: str) -> ScheduledRun:
        row = db.execute('''SELECT r.run_id,r.schedule_id,r.due_utc,r.task_id,
            r.status,r.attempts,r.error_code,r.skipped_missed_slots,
            t.status,t.attempts,t.error_code FROM writing_schedule_runs r
            LEFT JOIN local_tasks t ON r.task_id=t.task_id WHERE r.run_id=?''',
            (run_id,)).fetchone()
        if row is None:
            raise ScheduleError('scheduled run not found')
        if row[3] is None:
            return self._run(row[:8])
        if row[8] not in _STATUSES - {'SKIPPED_BUSY'}:
            raise ScheduleError('queue state missing or invalid')
        if (row[4], row[5], row[6]) != (row[8], row[9], row[10]):
            db.execute('''UPDATE writing_schedule_runs SET status=?,attempts=?,error_code=?
                WHERE run_id=?''', (row[8], row[9], row[10], run_id))
            self._event(db, run_id, 'OBSERVED_' + row[8], row[9], row[10], stamp)
            return self._run((row[0], row[1], row[2], row[3], row[8], row[9], row[10], row[7]))
        return self._run(row[:8])

    def refresh_run(self, run_id: str, *, now: datetime) -> ScheduledRun:
        if not _identifier(run_id):
            raise ScheduleError('invalid run id')
        stamp = _stamp(now)
        with self.queue._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            result = self._observe(db, run_id, stamp)
        return result

    def execute_run(self, run_id: str, *, handler, local_execution_approved: bool,
                    now: datetime) -> ScheduledRun:
        """Explicitly run one claimed draft task; handler must enforce its own gates.

        The handler is user-supplied, local-only and receives project/episode IDs.
        It MUST NOT finalize, publish or perform remote calls; scheduler cannot
        inspect arbitrary callback internals. Only literal True is success.
        """
        if (not _identifier(run_id) or type(local_execution_approved) is not bool
                or not local_execution_approved or not callable(handler)):
            raise ScheduleError('explicit local execution authorization required')
        stamp = _stamp(now)
        with self.queue._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('''SELECT r.task_id,s.project_id,s.episode_number
                FROM writing_schedule_runs r JOIN writing_schedules s
                ON r.schedule_id=s.schedule_id WHERE r.run_id=?''', (run_id,)).fetchone()
            if row is None or row[0] is None:
                raise ScheduleError('no executable scheduled task')
            task_id, project_id, episode = row
        task = self.queue.claim_identified(task_id, project_id, episode)
        if task is None:
            raise ScheduleError('task is not queued or is controlled')
        self.refresh_run(run_id, now=now)
        try:
            ok = handler(project_id, episode) is True
            code = None if ok else 'HANDLER_NOT_SUCCESSFUL'
        except Exception:
            ok, code = False, 'HANDLER_EXCEPTION'
        self.queue.finish(task_id, succeeded=ok, error_code=code)
        return self.refresh_run(run_id, now=now)

    def retry_run(self, run_id: str, *, now: datetime, retry_authorized: bool,
                  max_attempts: int = 3) -> ScheduledRun:
        """Atomic opt-in retry only for stage-69's known transient error codes."""
        if (not _identifier(run_id) or type(retry_authorized) is not bool
                or not retry_authorized or not _positive(max_attempts, MAX_ATTEMPTS)):
            raise ScheduleError('explicit retry authorization required')
        stamp = _stamp(now)
        with self.queue._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            run = self._observe(db, run_id, stamp)
            if run.task_id is None:
                raise ScheduleError('skipped schedule cannot be retried')
            task = db.execute('''SELECT status,attempts,error_code FROM local_tasks
                WHERE task_id=?''', (run.task_id,)).fetchone()
            control = db.execute('SELECT request FROM task_controls WHERE task_id=?',
                                 (run.task_id,)).fetchone()
            if (task is None or task[0] != 'FAILED' or task[2] not in RETRYABLE_CODES
                    or task[1] >= max_attempts or (control and control[0] != 'NONE')):
                raise ScheduleError('retry not permitted for this task state')
            db.execute("UPDATE local_tasks SET status='QUEUED',error_code=NULL "
                       'WHERE task_id=?', (run.task_id,))
            db.execute("UPDATE task_controls SET percent=0,stage='PENDING',paused=0 "
                       'WHERE task_id=?', (run.task_id,))
            db.execute('''UPDATE writing_schedule_runs SET status='QUEUED',error_code=NULL
                WHERE run_id=?''', (run_id,))
            self._event(db, run_id, 'RETRY_QUEUED', task[1], None, stamp)
        return self.get_run(run_id)
