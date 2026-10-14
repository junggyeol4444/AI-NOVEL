"""Stage 69: opt-in offline retry and verifiable metadata-only checkpoints.

Only SHA-256 fingerprints, names and task status are persisted; manuscript and
prompts stay in memory or in caller-owned storage. Restarts require the caller
to restore *every* prior artifact and pass a hash check before any new work.
This is not final manuscript persistence, publisher integration, or an API client.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import sqlite3
from typing import Callable

from .local_task_queue import LocalTaskQueue, TaskQueueError, TaskRecord, _identifier


class CheckpointError(TaskQueueError):
    """Sanitized state, integrity, or unsafe retry operation."""


class RetryableStepError(Exception):
    """Explicitly signalled transient LOCAL operation failure (no raw text)."""


@dataclass(frozen=True)
class CheckpointRecord:
    task_id: str
    index: int
    name: str
    context_sha256: str
    artifact_sha256: str


@dataclass(frozen=True)
class RetryRun:
    task: TaskRecord
    artifacts: tuple[bytes, ...]
    reused_steps: int
    approved: bool = False
    final_saved: bool = False
    published: bool = False


MAX_STEPS = 100
MAX_ARTIFACT_BYTES = 2_000_000
MAX_ATTEMPTS = 5
RETRYABLE_CODES = frozenset({'LOCAL_PROVIDER_TRANSIENT', 'LOCAL_PROVIDER_TIMEOUT'})
_RESERVED = frozenset({'FINAL_SAVE', 'PUBLISH', 'APPROVE', 'MEMORY_UPDATE'})


def _digest(value: object) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in '0123456789abcdef' for char in value))


def _artifact(value: object) -> bytes:
    if type(value) is not bytes or not 1 <= len(value) <= MAX_ARTIFACT_BYTES:
        raise CheckpointError('invalid checkpoint artifact')
    return value


class RetryCheckpointCoordinator:
    """Explicit queue retry and ordered step resume with fail-closed validation.

    Application code must provide `execute(name, index, prior_artifacts)` and
    `restore(name, index)`. A checkpoint NEVER means a manuscript is approved,
    published or saved. A stage callback must not finalize irreversible work.
    The queue must live in a trusted, local user-owned directory.
    """
    def __init__(self, queue: LocalTaskQueue):
        if not isinstance(queue, LocalTaskQueue):
            raise CheckpointError('local task queue required')
        self.queue = queue
        with self.queue._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS retry_checkpoints ('
                       'task_id TEXT NOT NULL REFERENCES local_tasks(task_id), '
                       'step_index INTEGER NOT NULL CHECK (step_index >= 0), '
                       'step_name TEXT NOT NULL, context_sha256 TEXT NOT NULL, '
                       'artifact_sha256 TEXT NOT NULL, '
                       'PRIMARY KEY(task_id,step_index))')

    def checkpoints(self, task_id: str) -> tuple[CheckpointRecord, ...]:
        if not _identifier(task_id):
            raise CheckpointError('invalid task id')
        with self.queue._connect() as db:
            rows = db.execute('SELECT task_id,step_index,step_name,context_sha256,'
                              'artifact_sha256 FROM retry_checkpoints WHERE task_id=? '
                              'ORDER BY step_index', (task_id,)).fetchall()
        return tuple(CheckpointRecord(*row) for row in rows)

    def retry_failed(self, task_id: str, *, max_attempts: int = 3) -> TaskRecord:
        """User-initiated requeue only for explicitly classified transient errors.

        Attempts count actual claims, not requests. Cancellation, unknown
        exceptions, exhausted budgets and already-completed tasks fail closed.
        """
        if (not _identifier(task_id) or type(max_attempts) is not int
                or not 1 <= max_attempts <= MAX_ATTEMPTS):
            raise CheckpointError('invalid retry parameters')
        with self.queue._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT status,attempts,error_code FROM local_tasks '
                             'WHERE task_id=?', (task_id,)).fetchone()
            if row is None or row[0] != 'FAILED':
                raise CheckpointError('only failed tasks can be retried')
            if row[2] not in RETRYABLE_CODES:
                raise CheckpointError('error is not explicitly retryable')
            if row[1] >= max_attempts:
                raise CheckpointError('retry attempts exhausted')
            control = db.execute('SELECT request FROM task_controls WHERE task_id=?',
                                 (task_id,)).fetchone()
            if control and control[0] != 'NONE':
                raise CheckpointError('pending task control blocks retry')
            db.execute("UPDATE local_tasks SET status='QUEUED',error_code=NULL "
                       "WHERE task_id=? AND status='FAILED'", (task_id,))
            db.execute("UPDATE task_controls SET percent=0,stage='PENDING',paused=0 "
                       "WHERE task_id=?", (task_id,))
        return self.queue.get(task_id)

    @staticmethod
    def _validate_plan(steps: tuple[str, ...], context_sha256: str) -> None:
        if (type(steps) is not tuple or not 1 <= len(steps) <= MAX_STEPS
                or len(set(steps)) != len(steps)
                or any(not _identifier(s) or s.upper() in _RESERVED for s in steps)
                or not _digest(context_sha256)):
            raise CheckpointError('invalid step plan or context digest')

    def _mark_success(self, task: TaskRecord, index: int, name: str,
                      context_hash: str, artifact_hash: str) -> None:
        """Atomically persist a step once; never overwrite a different artifact."""
        with self.queue._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            status = db.execute('SELECT status FROM local_tasks WHERE task_id=?',
                                (task.task_id,)).fetchone()
            control = db.execute('SELECT request FROM task_controls WHERE task_id=?',
                                 (task.task_id,)).fetchone()
            if status is None or status[0] != 'RUNNING' or (control and control[0] == 'CANCEL'):
                raise CheckpointError('task stopped or cancelled')
            existing = db.execute('SELECT step_name,context_sha256,artifact_sha256 '
                                  'FROM retry_checkpoints WHERE task_id=? AND step_index=?',
                                  (task.task_id, index)).fetchone()
            desired = (name, context_hash, artifact_hash)
            if existing is not None:
                if existing != desired:
                    raise CheckpointError('checkpoint conflict')
                return
            count = db.execute('SELECT COUNT(*) FROM retry_checkpoints WHERE task_id=?',
                               (task.task_id,)).fetchone()[0]
            if count != index:
                raise CheckpointError('out-of-order checkpoint')
            db.execute('INSERT INTO retry_checkpoints VALUES (?,?,?,?,?)',
                       (task.task_id, index, name, context_hash, artifact_hash))

    def run_task(self, task_id: str, project_id: str, episode_number: int,
                 steps: tuple[str, ...], *, context_sha256: str,
                    execute: Callable[[str, int, tuple[bytes, ...]], bytes],
                    restore: Callable[[str, int], bytes]) -> RetryRun | None:
        """Claim one task; verify prior artifacts, then execute only missing steps.

        Returns no artifacts on failure and writes non-sensitive failure codes.
        Each invocation is explicit. No automatic dispatch, network, final save,
        or retry is performed. Caller provides its *own* persisted artifacts for
        restart restoration; if absent/changed, resumption is rejected.
        """
        self._validate_plan(steps, context_sha256)
        if not callable(execute) or not callable(restore):
            raise CheckpointError('execute and restore callbacks required')
        task = self.queue.claim_identified(task_id, project_id, episode_number)
        if task is None:
            return None
        outputs: list[bytes] = []
        reused = 0
        try:
            previous = self.checkpoints(task.task_id)
            if len(previous) > len(steps):
                raise CheckpointError('checkpoint exceeds current plan')
            # Never execute another step before verifying all earlier artifacts.
            for i, cp in enumerate(previous):
                if cp.index != i or cp.name != steps[i] or cp.context_sha256 != context_sha256:
                    raise CheckpointError('checkpoint plan/context mismatch')
                try:
                    material = _artifact(restore(cp.name, i))
                except Exception:
                    raise CheckpointError('checkpoint artifact unavailable') from None
                if sha256(material).hexdigest() != cp.artifact_sha256:
                    raise CheckpointError('checkpoint artifact changed')
                outputs.append(material)
                reused += 1
            from .task_monitor import TaskMonitor
            monitor = TaskMonitor(self.queue)
            for i in range(reused, len(steps)):
                name = steps[i]
                stage = ('PLANNING' if name.startswith('PLAN') else
                         'ASSEMBLING' if name.startswith('ASSEMB') else
                         'CHECKING' if name.startswith('CHECK') else 'WRITING')
                monitor.checkpoint(task.task_id, i * 99 // len(steps), stage)
                # No mutation by the caller is possible because previous bytes
                # are immutable, and our checkpoint record is metadata-only.
                material = _artifact(execute(steps[i], i, tuple(outputs)))
                self._mark_success(task, i, steps[i], context_sha256,
                                   sha256(material).hexdigest())
                outputs.append(material)
        except RetryableStepError:
            result = self.queue.finish(task.task_id, succeeded=False,
                                       error_code='LOCAL_PROVIDER_TRANSIENT')
            return RetryRun(result, (), reused)
        except Exception:
            result = self.queue.finish(task.task_id, succeeded=False,
                                       error_code='CHECKPOINT_EXECUTION_FAILED')
            return RetryRun(result, (), reused)
        result = self.queue.finish(task.task_id, succeeded=True)
        if result.status != 'COMPLETED':
            return RetryRun(result, (), reused)
        return RetryRun(result, tuple(outputs), reused)
