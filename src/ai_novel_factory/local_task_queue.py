"""Stage 67: durable, offline, metadata-only task queue.

The queue NEVER serializes plans, manuscript text, prompts, secrets or model
objects. Workers receive a handler supplied by the running application. Jobs
cannot automatically resume across process restarts without renewed dispatch.
No remote broker is accessed by this module.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3
import threading
from typing import Callable
from uuid import uuid4


class TaskQueueError(ValueError):
    """Non-sensitive queue validation or transition error."""


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    project_id: str
    episode_number: int
    status: str
    attempts: int
    error_code: str | None = None


def _identifier(value: str) -> bool:
    return (type(value) is str and 1 <= len(value) <= 128
            and value.strip() == value and bool(value)
            and all(ch.isascii() and (ch.isalnum() or ch in '-_') for ch in value))


class LocalTaskQueue:
    """SQLite-backed single-job claiming with transactional ownership.

    RUNNING jobs from a crashed process become INTERRUPTED on the next open;
    they are never silently retried because their in-memory input is gone.
    Task statuses never mean manuscript approval, saving or publication.
    """
    def __init__(self, path: str | Path, *, recover_running: bool = True) -> None:
        if not isinstance(path, (str, Path)) or not str(path) or str(path) == ':memory:':
            raise TaskQueueError('a local database file path is required')
        self.path = Path(path)
        if self.path.is_symlink() or (self.path.exists() and not self.path.is_file()):
            raise TaskQueueError('unsafe queue database path')
        if not self.path.parent.is_dir():
            raise TaskQueueError('queue directory must already exist')
        self._recover_running = recover_running
        self._initialize()

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            con.execute('PRAGMA busy_timeout=10000')
            yield con
            if con.in_transaction:
                con.commit()
        except BaseException:
            if con.in_transaction:
                con.rollback()
            raise
        finally:
            con.close()

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS local_tasks ('
                       'task_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, '
                       'episode_number INTEGER NOT NULL CHECK (episode_number > 0), '
                       'status TEXT NOT NULL CHECK (status IN '
                       '(\'QUEUED\',\'RUNNING\',\'COMPLETED\',\'FAILED\',\'INTERRUPTED\')), '
                       'attempts INTEGER NOT NULL DEFAULT 0, error_code TEXT)')
            db.execute("CREATE TABLE IF NOT EXISTS task_controls ("
                       "task_id TEXT PRIMARY KEY REFERENCES local_tasks(task_id), "
                       "request TEXT NOT NULL DEFAULT 'NONE' "
                       "CHECK (request IN ('NONE','PAUSE','CANCEL')), "
                       "percent INTEGER NOT NULL DEFAULT 0 "
                       "CHECK (percent BETWEEN 0 AND 100), "
                       "stage TEXT NOT NULL DEFAULT 'PENDING', "
                       "paused INTEGER NOT NULL DEFAULT 0 "
                       "CHECK (paused IN (0,1)))")
            if self._recover_running:
                db.execute("UPDATE local_tasks SET status='INTERRUPTED', "
                           "error_code='WORKER_INTERRUPTED' WHERE status='RUNNING'")

    @staticmethod
    def _record(row: tuple) -> TaskRecord:
        return TaskRecord(*row)

    def enqueue(self, project_id: str, episode_number: int, *, task_id: str | None = None) -> TaskRecord:
        if not _identifier(project_id) or type(episode_number) is not int or episode_number < 1:
            raise TaskQueueError('invalid queue identity')
        if task_id is None:
            task_id = uuid4().hex
        if not _identifier(task_id):
            raise TaskQueueError('invalid task id')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT task_id, project_id, episode_number, status, attempts, '
                             'error_code FROM local_tasks WHERE task_id=?', (task_id,)).fetchone()
            if row:
                if row[1:3] != (project_id, episode_number):
                    raise TaskQueueError('task id collision')
                return self._record(row)
            db.execute('INSERT INTO local_tasks '
                       '(task_id,project_id,episode_number,status,attempts) VALUES (?,?,?,?,0)',
                       (task_id, project_id, episode_number, 'QUEUED'))
        return self.get(task_id)

    def get(self, task_id: str) -> TaskRecord | None:
        if not _identifier(task_id):
            raise TaskQueueError('invalid task id')
        with self._connect() as db:
            row = db.execute('SELECT task_id,project_id,episode_number,status,attempts,error_code '
                             'FROM local_tasks WHERE task_id=?', (task_id,)).fetchone()
        return self._record(row) if row else None

    def claim(self) -> TaskRecord | None:
        """Atomically claim a queued task, with no implicit retry or reordering."""
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT t.task_id FROM local_tasks t '
                             'LEFT JOIN task_controls c ON t.task_id=c.task_id '
                             "WHERE t.status='QUEUED' AND (c.request IS NULL OR c.request='NONE') "
                             'ORDER BY t.rowid LIMIT 1').fetchone()
            if row is None:
                return None
            db.execute("UPDATE local_tasks SET status='RUNNING', attempts=attempts+1 "
                       "WHERE task_id=? AND status='QUEUED'", row)
            result = db.execute('SELECT task_id,project_id,episode_number,status,attempts,'
                                'error_code FROM local_tasks WHERE task_id=?', row).fetchone()
        return self._record(result)

    def claim_identified(self, task_id: str, project_id: str,
                         episode_number: int) -> TaskRecord | None:
        """Claim only an expected task identity; never dispatch another novel's plan.

        Separate from claim() to preserve the preexisting FIFO worker contract.
        """
        if (not _identifier(task_id) or not _identifier(project_id)
                or type(episode_number) is not int or episode_number < 1):
            raise TaskQueueError('invalid claim identity')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT t.task_id FROM local_tasks t '
                             'LEFT JOIN task_controls c ON t.task_id=c.task_id '
                             "WHERE t.task_id=? AND t.project_id=? AND t.episode_number=? "
                             "AND t.status='QUEUED' "
                             "AND (c.request IS NULL OR c.request='NONE')",
                             (task_id, project_id, episode_number)).fetchone()
            if row is None:
                return None
            db.execute("UPDATE local_tasks SET status='RUNNING',attempts=attempts+1 "
                       "WHERE task_id=? AND status='QUEUED'", (task_id,))
            result = db.execute('SELECT task_id,project_id,episode_number,status,attempts,'
                                'error_code FROM local_tasks WHERE task_id=?',
                                (task_id,)).fetchone()
        return self._record(result)

    def finish(self, task_id: str, *, succeeded: bool, error_code: str | None = None) -> TaskRecord:
        if not _identifier(task_id) or type(succeeded) is not bool:
            raise TaskQueueError('invalid finish arguments')
        if succeeded:
            if error_code is not None:
                raise TaskQueueError('successful tasks cannot have errors')
        elif not _identifier(error_code):
            raise TaskQueueError('failure requires a non-sensitive error code')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            cancel = db.execute('SELECT request FROM task_controls WHERE task_id=?',
                                (task_id,)).fetchone()
            if cancel and cancel[0] == 'CANCEL':
                status, code = 'INTERRUPTED', 'TASK_CANCELLED'
            else:
                status, code = ('COMPLETED' if succeeded else 'FAILED'), error_code
            update = db.execute('UPDATE local_tasks SET status=?,error_code=? '
                                "WHERE task_id=? AND status='RUNNING'",
                                (status, code, task_id))
            if status == 'COMPLETED':
                db.execute("UPDATE task_controls SET percent=100,stage='FINISHED',paused=0 "
                           'WHERE task_id=?', (task_id,))
            if update.rowcount != 1:
                raise TaskQueueError('task is not running')
        return self.get(task_id)

    def run_one(self, handler: Callable[[str, int], bool]) -> TaskRecord | None:
        """Execute one job synchronously; a caller may run it in its own thread.

        The handler is process-local and must perform its own 66-stage human gate;
        only a literal True is success. Exception strings are never persisted.
        """
        if not callable(handler):
            raise TaskQueueError('a local handler is required')
        task = self.claim()
        if task is None:
            return None
        try:
            result = handler(task.project_id, task.episode_number)
        except Exception:
            return self.finish(task.task_id, succeeded=False, error_code='HANDLER_EXCEPTION')
        return self.finish(task.task_id, succeeded=(result is True),
                           error_code=None if result is True else 'HANDLER_NOT_SUCCESSFUL')

    def run_one_async(self, handler: Callable[[str, int], bool]) -> threading.Thread:
        """Start exactly one opt-in local worker thread (no scheduler or network)."""
        if not callable(handler):
            raise TaskQueueError('a local handler is required')
        thread = threading.Thread(target=self.run_one, args=(handler,), daemon=True,
                                  name='anf-local-queue-worker')
        thread.start()
        return thread
