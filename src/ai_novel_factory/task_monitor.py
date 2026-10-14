"""Stage 68: local, metadata-only task progress and cooperative controls.

Never stores prompts/manuscript, never starts a worker when opening the screen.
Running jobs must explicitly call checkpoint() for prompt pause/cancel handling;
cancellation also wins a concurrent race with finish() in the stage-67 queue.
"""
from __future__ import annotations

from dataclasses import dataclass
import sqlite3
import threading
from typing import Callable

from .local_task_queue import LocalTaskQueue, TaskQueueError, _identifier


class TaskCancelled(Exception):
    """Internal control flow; never surface text from a writer exception."""


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: str
    project_id: str
    episode_number: int
    status: str
    progress: int
    stage: str
    attempts: int
    error_code: str | None


_STAGES = frozenset(('PENDING', 'PLANNING', 'WRITING', 'ASSEMBLING',
                     'CHECKING', 'REVIEW', 'FINISHED'))
_TERMINAL = frozenset(('COMPLETED', 'FAILED', 'INTERRUPTED'))


class TaskMonitor:
    def __init__(self, queue: LocalTaskQueue) -> None:
        if not isinstance(queue, LocalTaskQueue):
            raise TaskQueueError('local task queue required')
        self.queue = queue

    @staticmethod
    def _convert(row: tuple) -> TaskSnapshot:
        task_id, project, ep, status, attempts, error, request, percent, stage, paused = row
        if status == 'RUNNING':
            if request == 'CANCEL':
                status = 'CANCEL_REQUESTED'
            elif request == 'PAUSE':
                status = 'PAUSED' if paused else 'PAUSE_REQUESTED'
        elif status == 'QUEUED' and request == 'PAUSE':
            status = 'PAUSED'
        elif status == 'INTERRUPTED' and error == 'TASK_CANCELLED':
            status = 'CANCELLED'
        return TaskSnapshot(task_id, project, ep, status, percent, stage, attempts, error)

    _QUERY = ("SELECT t.task_id,t.project_id,t.episode_number,t.status,t.attempts,t.error_code,"
              "COALESCE(c.request,'NONE'),COALESCE(c.percent,0),"
              "COALESCE(c.stage,'PENDING'),COALESCE(c.paused,0) "
              "FROM local_tasks t LEFT JOIN task_controls c ON t.task_id=c.task_id")

    def list_tasks(self, *, project_id: str | None = None) -> tuple[TaskSnapshot, ...]:
        if project_id is not None and not _identifier(project_id):
            raise TaskQueueError('invalid project id')
        with self.queue._connect() as db:
            if project_id is None:
                rows = db.execute(self._QUERY + ' ORDER BY t.rowid DESC').fetchall()
            else:
                rows = db.execute(self._QUERY + ' WHERE t.project_id=? ORDER BY t.rowid DESC',
                                  (project_id,)).fetchall()
        return tuple(map(self._convert, rows))

    def get(self, task_id: str) -> TaskSnapshot | None:
        if not _identifier(task_id):
            raise TaskQueueError('invalid task id')
        with self.queue._connect() as db:
            row = db.execute(self._QUERY + ' WHERE t.task_id=?', (task_id,)).fetchone()
        return self._convert(row) if row else None

    @staticmethod
    def _require_row(db: sqlite3.Connection, task_id: str) -> str:
        row = db.execute('SELECT status FROM local_tasks WHERE task_id=?', (task_id,)).fetchone()
        if row is None:
            raise TaskQueueError('unknown task id')
        return row[0]

    @staticmethod
    def _ensure_controls(db: sqlite3.Connection, task_id: str) -> None:
        db.execute('INSERT OR IGNORE INTO task_controls(task_id) VALUES (?)', (task_id,))

    def request_pause(self, task_id: str) -> TaskSnapshot:
        if not _identifier(task_id):
            raise TaskQueueError('invalid task id')
        with self.queue._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            status = self._require_row(db, task_id)
            if status not in ('QUEUED', 'RUNNING'):
                raise TaskQueueError('task cannot be paused')
            self._ensure_controls(db, task_id)
            if db.execute('SELECT request FROM task_controls WHERE task_id=?',
                          (task_id,)).fetchone()[0] == 'CANCEL':
                raise TaskQueueError('cancellation already requested')
            db.execute("UPDATE task_controls SET request='PAUSE' WHERE task_id=?", (task_id,))
        return self.get(task_id)

    def request_resume(self, task_id: str) -> TaskSnapshot:
        if not _identifier(task_id):
            raise TaskQueueError('invalid task id')
        with self.queue._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            status = self._require_row(db, task_id)
            if status not in ('QUEUED', 'RUNNING'):
                raise TaskQueueError('task cannot be resumed')
            row = db.execute('SELECT request FROM task_controls WHERE task_id=?',
                             (task_id,)).fetchone()
            if row is None or row[0] != 'PAUSE':
                raise TaskQueueError('task is not paused')
            db.execute("UPDATE task_controls SET request='NONE',paused=0 WHERE task_id=?",
                       (task_id,))
        return self.get(task_id)

    def request_cancel(self, task_id: str) -> TaskSnapshot:
        if not _identifier(task_id):
            raise TaskQueueError('invalid task id')
        with self.queue._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            status = self._require_row(db, task_id)
            if status not in ('QUEUED', 'RUNNING'):
                raise TaskQueueError('task cannot be cancelled')
            self._ensure_controls(db, task_id)
            db.execute("UPDATE task_controls SET request='CANCEL',paused=0 WHERE task_id=?",
                       (task_id,))
            if status == 'QUEUED':
                db.execute("UPDATE local_tasks SET status='INTERRUPTED',"
                           "error_code='TASK_CANCELLED' WHERE task_id=? AND status='QUEUED'",
                           (task_id,))
        return self.get(task_id)

    def checkpoint(self, task_id: str, percent: int, stage: str,
                   *, polling_seconds: float = 0.05) -> None:
        """Call from a worker BETWEEN safe steps; blocking pause is cooperative.

        Never call this on the Qt GUI thread. A pause request acknowledged here
        blocks until resumed/cancelled. Control updates are committed before wait.
        """
        if (not _identifier(task_id) or type(percent) is not int or not 0 <= percent <= 99
                or type(stage) is not str or stage not in _STAGES - {'FINISHED'}):
            raise TaskQueueError('invalid progress checkpoint')
        if not 0.01 <= polling_seconds <= 5:
            raise TaskQueueError('invalid polling interval')
        while True:
            with self.queue._connect() as db:
                db.execute('BEGIN IMMEDIATE')
                status = self._require_row(db, task_id)
                if status != 'RUNNING':
                    raise TaskCancelled()
                self._ensure_controls(db, task_id)
                row = db.execute('SELECT request,percent FROM task_controls WHERE task_id=?',
                                 (task_id,)).fetchone()
                command, previous = row
                if command == 'CANCEL':
                    raise TaskCancelled()
                if percent < previous:
                    raise TaskQueueError('progress must be monotonic')
                paused = int(command == 'PAUSE')
                db.execute('UPDATE task_controls SET percent=?,stage=?,paused=? WHERE task_id=?',
                           (percent, stage, paused, task_id))
            if not paused:
                return
            threading.Event().wait(polling_seconds)

    def run_one_controlled(self, handler: Callable[[str, int, Callable[[int, str], None]], bool]):
        """Opt-in stage-67 worker with safe checkpoints, no implicit retries.

        Handler returns literal True only if stage-66 review-gated processing is
        successful. Neither True nor queue COMPLETED approves manuscript/output.
        """
        if not callable(handler):
            raise TaskQueueError('local handler required')
        task = self.queue.claim()
        if task is None:
            return None
        try:
            self.checkpoint(task.task_id, 0, 'PLANNING')
            result = handler(task.project_id, task.episode_number,
                             lambda percent, stage: self.checkpoint(task.task_id, percent, stage))
        except TaskCancelled:
            # finish() atomically turns a cancellation request into INTERRUPTED.
            return self.queue.finish(task.task_id, succeeded=False, error_code='TASK_CANCELLED')
        except Exception:
            return self.queue.finish(task.task_id, succeeded=False, error_code='HANDLER_EXCEPTION')
        return self.queue.finish(task.task_id, succeeded=(result is True),
                                 error_code=None if result is True else 'HANDLER_NOT_SUCCESSFUL')

    def run_one_controlled_async(self, handler):
        if not callable(handler):
            raise TaskQueueError('local handler required')
        thread = threading.Thread(target=self.run_one_controlled, args=(handler,), daemon=True,
                                  name='anf-controlled-queue-worker')
        thread.start()
        return thread
