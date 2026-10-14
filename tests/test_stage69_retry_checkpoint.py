"""Stage 69 verified local retry/checkpoint contract, no cloud or model dependency."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from ai_novel_factory.local_task_queue import LocalTaskQueue
from ai_novel_factory.retry_checkpoint import (
    CheckpointError, RetryCheckpointCoordinator, RetryableStepError,
)


CONTEXT = sha256(b'novel-bible+approved-plans-v1').hexdigest()
OTHER_CONTEXT = sha256(b'changed-novel-bible-v2').hexdigest()
STEPS = ('PLAN', 'SCENE_1', 'SCENE_2', 'CHECK')


class RetryCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'queue.db'
        self.queue = LocalTaskQueue(self.path)
        self.store = RetryCheckpointCoordinator(self.queue)
        self.queue.enqueue('novel-A', 7, task_id='job-7')
        self.artifacts: dict[str, bytes] = {}
        self.calls: list[str] = []

    def execute(self, name, index, previous):
        self.calls.append(name)
        result = f'{index}/{name}/{len(previous)}'.encode()
        self.artifacts[name] = result  # caller-owned, not checkpoint table
        return result

    def restore(self, name, index):
        return self.artifacts[name]

    def run_job(self, steps=STEPS, context=CONTEXT):
        return self.store.run_task('job-7', 'novel-A', 7, steps, context_sha256=context,
                                      execute=self.execute, restore=self.restore)

    def test_run_success_all_steps_in_order(self):
        result = self.run_job()
        self.assertEqual(result.task.status, 'COMPLETED')
        self.assertEqual(result.task.attempts, 1)
        self.assertEqual(self.calls, list(STEPS))
        self.assertEqual(len(result.artifacts), 4)
        self.assertEqual(result.reused_steps, 0)
        self.assertFalse(result.approved)
        self.assertFalse(result.final_saved)
        self.assertFalse(result.published)

    def test_checkpoint_metadata_contains_no_artifacts(self):
        self.run_job()
        with sqlite3.connect(self.path) as db:
            rows = db.execute('SELECT * FROM retry_checkpoints').fetchall()
            cols = [col[1] for col in db.execute('PRAGMA table_info(retry_checkpoints)')]
        self.assertEqual(len(rows), 4)
        self.assertEqual(cols, ['task_id', 'step_index', 'step_name',
                                'context_sha256', 'artifact_sha256'])
        self.assertNotIn(self.artifacts['SCENE_1'], self.path.read_bytes())
        self.assertNotIn(b'novel-bible+approved-plans-v1', self.path.read_bytes())

    def test_failed_middle_step_and_verified_resume(self):
        def failing(name, index, previous):
            if name == 'SCENE_2':
                raise RetryableStepError('secret text must not be persisted')
            return self.execute(name, index, previous)
        first = self.store.run_task('job-7', 'novel-A', 7, STEPS, context_sha256=CONTEXT,
                                       execute=failing, restore=self.restore)
        self.assertEqual(first.task.status, 'FAILED')
        self.assertEqual(first.task.error_code, 'LOCAL_PROVIDER_TRANSIENT')
        self.assertEqual(first.artifacts, ())
        self.assertEqual(len(self.store.checkpoints('job-7')), 2)
        self.assertEqual(self.store.retry_failed('job-7').status, 'QUEUED')
        after = self.run_job()
        self.assertEqual(after.task.status, 'COMPLETED')
        self.assertEqual(after.task.attempts, 2)
        self.assertEqual(after.reused_steps, 2)
        self.assertEqual(self.calls, ['PLAN', 'SCENE_1', 'SCENE_2', 'CHECK'])
        self.assertEqual(len(self.store.checkpoints('job-7')), 4)

    def test_recovery_after_process_restart_with_supplied_artifacts(self):
        def fail_after_plan(name, idx, prev):
            if name == 'SCENE_1':
                raise RetryableStepError()
            return self.execute(name, idx, prev)
        self.store.run_task('job-7', 'novel-A', 7, STEPS, context_sha256=CONTEXT,
                               execute=fail_after_plan, restore=self.restore)
        # fresh queue and coordinator, no background auto-dispatch
        self.queue = LocalTaskQueue(self.path)
        self.store = RetryCheckpointCoordinator(self.queue)
        self.assertEqual(self.queue.get('job-7').status, 'FAILED')
        self.store.retry_failed('job-7')
        after = self.run_job()
        self.assertEqual(after.reused_steps, 1)
        self.assertEqual(after.task.status, 'COMPLETED')
        self.assertEqual(self.calls.count('PLAN'), 1)

    def test_missing_restored_artifact_fails_closed_before_new_work(self):
        self._failed_at_scene_1()
        self.artifacts.clear()
        self.store.retry_failed('job-7')
        calls = len(self.calls)
        result = self.run_job()
        self.assertEqual(result.task.status, 'FAILED')
        self.assertEqual(result.task.error_code, 'CHECKPOINT_EXECUTION_FAILED')
        self.assertEqual(len(self.calls), calls)
        self.assertEqual(len(self.store.checkpoints('job-7')), 1)

    def test_changed_restored_artifact_fails_closed(self):
        self._failed_at_scene_1()
        self.artifacts['PLAN'] = b'changed manuscript'
        self.store.retry_failed('job-7')
        result = self.run_job()
        self.assertEqual(result.task.status, 'FAILED')
        self.assertEqual(self.calls, ['PLAN'])

    def test_changed_novel_bible_context_prevents_resume(self):
        self._failed_at_scene_1()
        self.store.retry_failed('job-7')
        result = self.run_job(context=OTHER_CONTEXT)
        self.assertEqual(result.task.status, 'FAILED')
        self.assertEqual(self.calls, ['PLAN'])

    def test_changed_step_plan_prevents_resume(self):
        self._failed_at_scene_1()
        self.store.retry_failed('job-7')
        result = self.run_job(steps=('DIFFERENT', 'SCENE_1'))
        self.assertEqual(result.task.status, 'FAILED')
        self.assertEqual(self.calls, ['PLAN'])

    def test_shrunk_plan_prevents_resume(self):
        self._failed_at_scene_2()
        self.store.retry_failed('job-7')
        result = self.run_job(steps=('PLAN',))
        self.assertEqual(result.task.status, 'FAILED')

    def test_transient_error_text_not_persisted(self):
        secret = 'SECRET-LOCAL-PROVIDER-ERROR-DO-NOT-LOG'
        def fail(*args):
            raise RetryableStepError(secret)
        result = self.store.run_task('job-7', 'novel-A', 7, STEPS, context_sha256=CONTEXT,
                                       execute=fail, restore=self.restore)
        self.assertEqual(result.task.error_code, 'LOCAL_PROVIDER_TRANSIENT')
        self.assertNotIn(secret.encode(), self.path.read_bytes())

    def test_unexpected_error_is_not_retryable(self):
        def fail(*args):
            raise RuntimeError('secret from model')
        result = self.store.run_task('job-7', 'novel-A', 7, STEPS, context_sha256=CONTEXT,
                                       execute=fail, restore=self.restore)
        self.assertEqual(result.task.error_code, 'CHECKPOINT_EXECUTION_FAILED')
        with self.assertRaises(CheckpointError):
            self.store.retry_failed('job-7')
        self.assertNotIn(b'secret from model', self.path.read_bytes())

    def test_failing_checkpoint_artifact_is_not_persisted(self):
        def fail(*args):
            return b''
        result = self.store.run_task('job-7', 'novel-A', 7, STEPS, context_sha256=CONTEXT,
                                       execute=fail, restore=self.restore)
        self.assertEqual(result.task.status, 'FAILED')
        self.assertEqual(self.store.checkpoints('job-7'), ())

    def test_wrong_callback_output_type_is_rejected(self):
        def fail(*args):
            return 'plaintext not bytes'
        result = self.store.run_task('job-7', 'novel-A', 7, STEPS, context_sha256=CONTEXT,
                                       execute=fail, restore=self.restore)
        self.assertEqual(result.task.status, 'FAILED')

    def test_no_handler_and_no_job_validation(self):
        with self.assertRaises(CheckpointError):
            self.store.run_task('job-7', 'novel-A', 7, STEPS, context_sha256=CONTEXT,
                                   execute=None, restore=self.restore)
        self.assertEqual(self.queue.get('job-7').status, 'QUEUED')
        self.run_job()
        self.assertIsNone(self.run_job())

    def test_no_auto_resume_after_normal_finish(self):
        self.run_job()
        with self.assertRaises(CheckpointError):
            self.store.retry_failed('job-7')
        self.assertIsNone(self.run_job())

    def test_no_retry_after_nontransient_error(self):
        self.queue.claim()
        self.queue.finish('job-7', succeeded=False, error_code='HANDLER_EXCEPTION')
        with self.assertRaises(CheckpointError):
            self.store.retry_failed('job-7')

    def test_max_attempts_enforced(self):
        def fail(*args): raise RetryableStepError()
        for i in range(3):
            result = self.store.run_task('job-7', 'novel-A', 7, STEPS, context_sha256=CONTEXT,
                                            execute=fail, restore=self.restore)
            self.assertEqual(result.task.attempts, i+1)
            if i < 2:
                self.store.retry_failed('job-7', max_attempts=3)
        with self.assertRaises(CheckpointError):
            self.store.retry_failed('job-7', max_attempts=3)

    def test_retry_budget_one_is_never_requeued(self):
        self.queue.claim()
        self.queue.finish('job-7', succeeded=False,
                          error_code='LOCAL_PROVIDER_TRANSIENT')
        with self.assertRaises(CheckpointError):
            self.store.retry_failed('job-7', max_attempts=1)

    def test_requeue_is_explicit_not_automatic(self):
        self._failed_at_scene_1()
        self.assertIsNone(self.queue.claim())
        self.assertEqual(self.queue.get('job-7').status, 'FAILED')

    def test_cancellation_does_not_requeue(self):
        from ai_novel_factory.task_monitor import TaskMonitor
        self.queue.claim()
        TaskMonitor(self.queue).request_cancel('job-7')
        self.queue.finish('job-7', succeeded=False, error_code='LOCAL_PROVIDER_TRANSIENT')
        with self.assertRaises(CheckpointError):
            self.store.retry_failed('job-7')

    def test_paused_queued_does_not_claim(self):
        from ai_novel_factory.task_monitor import TaskMonitor
        TaskMonitor(self.queue).request_pause('job-7')
        self.assertIsNone(self.run_job())
        self.assertEqual(len(self.calls), 0)

    def test_no_finalization_or_publication_stage(self):
        for token in ('FINAL_SAVE','PUBLISH','APPROVE','MEMORY_UPDATE'):
            with self.subTest(token=token), self.assertRaises(CheckpointError):
                self.run_job(steps=('PLAN', token))
        self.assertEqual(self.queue.get('job-7').status, 'QUEUED')

    def test_bad_plans_rejected_before_task_claim(self):
        bad = ((), ('A','A'), ('BAD NAME',), ('PLAN',)*101, ['PLAN'])
        for steps in bad:
            with self.subTest(steps=str(steps)[:30]), self.assertRaises(CheckpointError):
                self.run_job(steps=steps)
        self.assertEqual(self.queue.get('job-7').status, 'QUEUED')

    def test_bad_context_rejected_before_task_claim(self):
        for value in ('', 'ABC', 'z'*64, None):
            with self.subTest(value=value), self.assertRaises(CheckpointError):
                self.run_job(context=value)
        self.assertEqual(self.queue.get('job-7').status, 'QUEUED')

    def test_bad_retry_max_or_id_rejected(self):
        self._failed_at_scene_1()
        for max_attempts in (0, -1, 6, True, '3'):
            with self.subTest(value=max_attempts), self.assertRaises(CheckpointError):
                self.store.retry_failed('job-7', max_attempts=max_attempts)
        with self.assertRaises(CheckpointError):
            self.store.retry_failed('../file')

    def test_retry_respects_pause_request(self):
        from ai_novel_factory.task_monitor import TaskMonitor
        self._failed_at_scene_1()
        # control request can have existed when a job failed, and prevents retry
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT OR REPLACE INTO task_controls(task_id,request) VALUES ('job-7','PAUSE')")
        with self.assertRaises(CheckpointError):
            self.store.retry_failed('job-7')

    def test_checkpoints_isolated_by_task(self):
        self.queue.enqueue('novel-B', 2, task_id='job-B')
        self._failed_at_scene_1()
        self.assertEqual(self.store.checkpoints('job-B'), ())
        self.assertEqual(len(self.store.checkpoints('job-7')), 1)

    def test_restart_does_not_implicitly_retry_interrupted_task(self):
        self.queue.claim()
        reopened = LocalTaskQueue(self.path)
        self.assertEqual(reopened.get('job-7').status, 'INTERRUPTED')
        with self.assertRaises(CheckpointError):
            RetryCheckpointCoordinator(reopened).retry_failed('job-7')

    def test_concurrent_manual_retry_only_one_wins(self):
        self._failed_at_scene_1()
        successes = []
        def attempt():
            try:
                successes.append(self.store.retry_failed('job-7').status)
            except CheckpointError:
                pass
        threads = [threading.Thread(target=attempt) for _ in range(8)]
        for t in threads: t.start()
        for t in threads: t.join(5)
        self.assertEqual(successes, ['QUEUED'])

    def test_claim_never_dispatches_wrong_project_or_episode(self):
        self.queue.enqueue('novel-B', 8, task_id='job-B')
        self.assertIsNone(self.store.run_task('job-B', 'novel-A', 8,
                              STEPS, context_sha256=CONTEXT,
                              execute=self.execute, restore=self.restore))
        self.assertIsNone(self.store.run_task('job-7', 'novel-A', 8,
                              STEPS, context_sha256=CONTEXT,
                              execute=self.execute, restore=self.restore))
        self.assertEqual(self.queue.get('job-B').status, 'QUEUED')
        self.assertEqual(self.queue.get('job-7').status, 'QUEUED')
        self.assertEqual(self.calls, [])

    def test_claim_identified_succeeds_without_fifo_reordering(self):
        self.queue.enqueue('novel-B', 8, task_id='job-B')
        other = self.store.run_task('job-B', 'novel-B', 8,
                                    STEPS, context_sha256=CONTEXT,
                                    execute=self.execute, restore=self.restore)
        self.assertEqual(other.task.project_id, 'novel-B')
        self.assertEqual(self.queue.get('job-7').status, 'QUEUED')

    def test_cancel_during_step_discards_result(self):
        from ai_novel_factory.task_monitor import TaskMonitor
        monitor = TaskMonitor(self.queue)
        def cancel_on_first(name, idx, previous):
            monitor.request_cancel('job-7')
            return b'generated but cancelled'
        result = self.store.run_task('job-7', 'novel-A', 7,
                       STEPS, context_sha256=CONTEXT,
                       execute=cancel_on_first, restore=self.restore)
        self.assertEqual(result.task.status, 'INTERRUPTED')
        self.assertEqual(result.artifacts, ())
        self.assertEqual(self.store.checkpoints('job-7'), ())

    def test_cancel_between_completed_steps_prevents_next_execution(self):
        from ai_novel_factory.task_monitor import TaskMonitor
        monitor = TaskMonitor(self.queue)
        def cancel_on_first(name, idx, previous):
            result = self.execute(name, idx, previous)
            if idx == 0:
                monitor.request_cancel('job-7')
            return result
        result = self.store.run_task('job-7', 'novel-A', 7,
                       STEPS, context_sha256=CONTEXT,
                       execute=cancel_on_first, restore=self.restore)
        self.assertEqual(result.task.status, 'INTERRUPTED')
        self.assertEqual(self.calls, ['PLAN'])

    def test_invalid_identity_prevents_claim(self):
        for identity in [('bad/id', 'novel-A', 7),
                         ('job-7', 'novel-A', True),
                         ('job-7', ' ', 7)]:
            with self.subTest(identity=identity), self.assertRaises(Exception):
                self.store.run_task(*identity, STEPS, context_sha256=CONTEXT,
                                    execute=self.execute, restore=self.restore)
        self.assertEqual(self.queue.get('job-7').status, 'QUEUED')

    def _failed_at_scene_1(self):
        def fail(name, idx, prev):
            if name == 'SCENE_1': raise RetryableStepError()
            return self.execute(name, idx, prev)
        self.store.run_task('job-7', 'novel-A', 7, STEPS, context_sha256=CONTEXT,
                               execute=fail, restore=self.restore)

    def _failed_at_scene_2(self):
        def fail(name, idx, prev):
            if name == 'SCENE_2': raise RetryableStepError()
            return self.execute(name, idx, prev)
        self.store.run_task('job-7', 'novel-A', 7, STEPS, context_sha256=CONTEXT,
                               execute=fail, restore=self.restore)


if __name__ == '__main__':
    unittest.main()
