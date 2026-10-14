"""Stage 67: offline durable metadata queue, concurrency, crash and broker safety."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest
from unittest.mock import patch

from ai_novel_factory.local_task_queue import LocalTaskQueue, TaskQueueError
from ai_novel_factory.celery_local_adapter import (
    LocalBrokerError, validate_loopback_redis, configure_local_celery,
)


class LocalQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'work.sqlite3'
        self.queue = LocalTaskQueue(self.path)

    def test_enqueue_claim_complete(self):
        row = self.queue.enqueue('novel-1', 5, task_id='job-a')
        self.assertEqual((row.status, row.attempts), ('QUEUED', 0))
        claimed = self.queue.claim()
        self.assertEqual((claimed.task_id, claimed.status, claimed.attempts), ('job-a', 'RUNNING', 1))
        self.assertEqual(self.queue.finish('job-a', succeeded=True).status, 'COMPLETED')
        self.assertIsNone(self.queue.claim())

    def test_idempotency_reuses_same_identity(self):
        first = self.queue.enqueue('p', 1, task_id='stable')
        self.assertEqual(first, self.queue.enqueue('p', 1, task_id='stable'))
        with self.assertRaises(TaskQueueError): self.queue.enqueue('other', 1, task_id='stable')
        with self.assertRaises(TaskQueueError): self.queue.enqueue('p', 2, task_id='stable')

    def test_multiple_jobs_fifo(self):
        for number in range(1, 4): self.queue.enqueue('p', number, task_id=f'job-{number}')
        self.assertEqual([self.queue.claim().episode_number for _ in range(3)], [1, 2, 3])

    def test_concurrent_claim_single_owner(self):
        self.queue.enqueue('p', 1, task_id='single')
        with ThreadPoolExecutor(max_workers=8) as pool:
            claimed = list(pool.map(lambda _: LocalTaskQueueNoReset(self.path).claim(), range(8)))
        self.assertEqual(len([x for x in claimed if x is not None]), 1)

    def test_restart_quarantines_running(self):
        self.queue.enqueue('p', 1, task_id='crash')
        self.queue.claim()
        reopened = LocalTaskQueue(self.path)
        self.assertEqual(reopened.get('crash').status, 'INTERRUPTED')
        self.assertEqual(reopened.get('crash').error_code, 'WORKER_INTERRUPTED')
        self.assertIsNone(reopened.claim())

    def test_reopen_keeps_completed(self):
        self.queue.enqueue('p', 1, task_id='done')
        self.queue.claim()
        self.queue.finish('done', succeeded=True)
        self.assertEqual(LocalTaskQueue(self.path).get('done').status, 'COMPLETED')

    def test_failed_handler_hides_text(self):
        self.queue.enqueue('p', 1, task_id='failure')
        def fail(project, episode): raise RuntimeError('PRIVATE STORY TEXT')
        result = self.queue.run_one(fail)
        self.assertEqual((result.status, result.error_code), ('FAILED', 'HANDLER_EXCEPTION'))
        self.assertNotIn('PRIVATE STORY TEXT', str(result))
        self.assertNotIn('PRIVATE STORY TEXT', self.path.read_bytes().decode('utf-8', 'ignore'))

    def test_non_true_handler_is_failure(self):
        self.queue.enqueue('p', 1)
        self.assertEqual(self.queue.run_one(lambda *_: 'True').status, 'FAILED')

    def test_async_worker_opt_in(self):
        self.queue.enqueue('p', 3, task_id='async')
        called = []
        th = self.queue.run_one_async(lambda project, episode: called.append((project, episode)) or True)
        th.join(5)
        self.assertFalse(th.is_alive())
        self.assertEqual(called, [('p', 3)])
        self.assertEqual(self.queue.get('async').status, 'COMPLETED')

    def test_no_automatic_worker(self):
        self.queue.enqueue('p', 1, task_id='pending')
        self.assertEqual(self.queue.get('pending').status, 'QUEUED')

    def test_finish_invalid_transition(self):
        self.queue.enqueue('p', 1, task_id='not-running')
        with self.assertRaises(TaskQueueError): self.queue.finish('not-running', succeeded=True)
        self.queue.claim()
        self.queue.finish('not-running', succeeded=True)
        with self.assertRaises(TaskQueueError): self.queue.finish('not-running', succeeded=True)

    def test_error_code_must_not_be_freeform_story(self):
        self.queue.enqueue('p', 1, task_id='codes')
        self.queue.claim()
        for code in ('SECRET STORY', 'KOREAN문장', 'x\ntext', None):
            with self.assertRaises(TaskQueueError):
                self.queue.finish('codes', succeeded=False, error_code=code)

    def test_invalid_enqueue_inputs(self):
        for project, episode in [('', 1), ('other work', 1), ('p', 0), ('p', True), ('p', '1'), ('p', -1)]:
            with self.subTest(project=project, episode=episode), self.assertRaises(TaskQueueError):
                self.queue.enqueue(project, episode)

    def test_no_plans_or_manuscript_columns(self):
        with sqlite3.connect(self.path) as db:
            columns = [row[1] for row in db.execute('PRAGMA table_info(local_tasks)')]
        self.assertEqual(columns, ['task_id', 'project_id', 'episode_number', 'status', 'attempts', 'error_code'])

    def test_path_protection(self):
        with self.assertRaises(TaskQueueError): LocalTaskQueue(self.path.parent / 'missing' / 'db')
        with self.assertRaises(TaskQueueError): LocalTaskQueue(':memory:')
        link = self.path.parent / 'link.db'
        try: link.symlink_to(self.path)
        except OSError: self.skipTest('symlinks unavailable')
        with self.assertRaises(TaskQueueError): LocalTaskQueue(link)

    def test_run_one_without_queue(self):
        self.assertIsNone(self.queue.run_one(lambda *_: True))

    def test_completed_does_not_imply_publication(self):
        self.queue.enqueue('p', 1)
        self.queue.run_one(lambda *_: True)
        self.assertFalse(hasattr(self.queue.claim(), 'publication_approved'))


class LocalTaskQueueNoReset(LocalTaskQueue):
    """Secondary connection avoiding crash recovery during live-worker simulation."""
    def _initialize(self):
        pass


class CeleryConfigTests(unittest.TestCase):
    def test_loopback_accepted(self):
        for url in ('redis://127.0.0.1:6379/0', 'redis://[::1]:6380/1'):
            self.assertEqual(validate_loopback_redis(url), url)

    def test_remote_and_redirect_rejected(self):
        for url in ('redis://localhost:6379/0', 'redis://evil.org:6379/0',
                    'rediss://127.0.0.1:6379/0', 'redis://127.0.0.1:6379/2',
                    'redis://user:pass@127.0.0.1:6379/0',
                    'redis://127.0.0.1:6379/0?foo=bar', 'redis://127.0.0.1/0',
                    'redis://127.0.0.1:0/0', 'redis://127.0.0.1:99999/0'):
            with self.subTest(url=url), self.assertRaises(LocalBrokerError):
                validate_loopback_redis(url)

    def test_explicit_consent_required(self):
        with self.assertRaises(LocalBrokerError): configure_local_celery()
        with self.assertRaises(LocalBrokerError): configure_local_celery(explicitly_approved=1)

    def test_missing_celery_dependency_never_contacts_network(self):
        with patch.dict('sys.modules', {'celery': None}):
            with self.assertRaises(LocalBrokerError):
                configure_local_celery(explicitly_approved=True)

    def test_no_socket_needed_for_configuration_validation(self):
        with patch('socket.socket', side_effect=AssertionError('network')):
            self.assertTrue(validate_loopback_redis('redis://127.0.0.1:6379/0'))


if __name__ == '__main__': unittest.main()

class OrchestratorQueueIntegrationTests(unittest.TestCase):
    def test_explicit_queue_handler_executes_stage66_without_publication(self):
        from ai_novel_factory.episode_context import ContextFact, select_episode_context
        from ai_novel_factory.episode_planner import EpisodePlan
        from ai_novel_factory.scene_planner import ScenePlan
        from ai_novel_factory.local_models import MockSceneProvider
        from ai_novel_factory.orchestrator import OfflineLiteralChecker, orchestrate_episode
        from ai_novel_factory.local_task_queue import LocalTaskQueue
        with TemporaryDirectory() as tmp:
            queue = LocalTaskQueue(Path(tmp) / 'queue.sqlite3')
            ep = EpisodePlan(5, 1, '목표', ('사건',), ('hero',), '', (), 'Hook')
            scenes = (ScenePlan(5, 1, '도서관', ('hero',), '탐색', '장애물', '긴장'),)
            ctx = select_episode_context('novel-1', ep, (
                ContextFact('novel-1', 'novel_bible', 'rule', '기본 원칙'),))
            results = []
            def handler(project, episode):
                self.assertEqual((project, episode), ('novel-1', 5))
                result = orchestrate_episode(project, ep, scenes, ctx,
                                             MockSceneProvider(), OfflineLiteralChecker())
                results.append(result)
                return result.status == 'AWAITING_HUMAN_REVIEW'
            queue.enqueue('novel-1', 5, task_id='episode5')
            self.assertEqual(queue.run_one(handler).status, 'COMPLETED')
            self.assertEqual(len(results), 1)
            self.assertFalse(results[0].persisted)
            self.assertFalse(results[0].publication_approved)
            self.assertFalse(results[0].memory_updated)
            self.assertNotIn(results[0].preview.draft, queue.path.read_bytes().decode('utf8', 'ignore'))

    def test_checker_blocked_is_not_successful_queue_job(self):
        from ai_novel_factory.episode_context import ContextFact, select_episode_context
        from ai_novel_factory.episode_planner import EpisodePlan
        from ai_novel_factory.scene_planner import ScenePlan
        from ai_novel_factory.local_models import MockSceneProvider
        from ai_novel_factory.orchestrator import OfflineLiteralChecker, orchestrate_episode
        with TemporaryDirectory() as tmp:
            queue = LocalTaskQueue(Path(tmp) / 'queue.sqlite3')
            ep = EpisodePlan(5, 1, '목표', ('사건',), ('hero',), '', (), 'Hook')
            scenes = (ScenePlan(5, 1, '도서관', ('hero',), '탐색', '장애물', '긴장'),)
            ctx = select_episode_context('p', ep, (ContextFact('p', 'novel_bible', 'r', '원칙'),))
            def handler(p, n):
                return orchestrate_episode(p, ep, scenes, ctx, MockSceneProvider(),
                                           OfflineLiteralChecker(('탐색',))).status == 'AWAITING_HUMAN_REVIEW'
            queue.enqueue('p', 5, task_id='blocked')
            self.assertEqual(queue.run_one(handler).status, 'FAILED')
