from contextlib import closing
"""Stage 84 / ANF-REQ-049: bounded, idempotent next-episode queue handoff."""
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from ai_novel_factory.episode_continuation import EpisodeContinuationStore, ContinuationError, continue_episode
from ai_novel_factory.local_task_queue import LocalTaskQueue
from ai_novel_factory.local_models import MockSceneProvider
from ai_novel_factory.episode_context import ContextFact, select_episode_context
from ai_novel_factory.scene_planner import ScenePlan
from ai_novel_factory.orchestrator import OfflineLiteralChecker
from ai_novel_factory.episode_planner import plan_episodes
from ai_novel_factory.story_arcs import StoryArcPlan, StoryArc, validate_arc_coverage


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / 'bible.sqlite'
        self.store = EpisodeContinuationStore(self.path)
        self.queue = LocalTaskQueue(self.root / 'jobs.sqlite')
        self.pid = self.store.create_project('연재 테스트').project_id
        self.store.create_episode(self.pid, 1)
        self.version = self.store.save_version(self.pid, 1, '확정 후보',
            kind='FINAL', expected_revision=1)
        self.arc = StoryArcPlan(3, (StoryArc(1, 1, 3, 'ARC 1', '검토 필요'),))
        self.plans = plan_episodes(self.arc)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def advance(self, **overrides):
        kwargs = dict(end_episode=3, expected_revision=2,
            expected_version_id=self.version.version_id,
            confirmation_asserted=True, arc_plan=self.arc,
            next_plan=self.plans[1] if len(self.plans) > 1 else None, queue=self.queue)
        kwargs.update(overrides)
        return self.store.advance_after_confirmation(self.pid, 1, **kwargs)

    def test_creates_next_episode(self):
        result = self.advance()
        self.assertEqual(result.next_episode, 2)
        self.assertEqual(self.store.get_episode(self.pid, 2).plot, '')

    def test_queues_next_episode(self):
        result = self.advance()
        task = self.queue.get(result.task_id)
        self.assertEqual((task.project_id, task.episode_number, task.status),
                         (self.pid, 2, 'QUEUED'))

    def test_handoff_is_not_generation(self):
        result = self.advance()
        self.assertFalse(result.draft_generated)
        self.assertEqual(self.store.get_episode(self.pid, 2).draft, '')

    def test_no_publication_approval(self):
        result = self.advance()
        self.assertFalse(result.publication_approved)
        self.assertFalse(result.approval_authenticated)

    def test_idempotent_retry(self):
        first = self.advance()
        second = self.advance()
        self.assertEqual(first, second)
        self.assertEqual(len(self.store.list_episodes(self.pid)), 2)

    def test_retry_keeps_task_id(self):
        first = self.advance()
        self.assertEqual(self.advance().task_id, first.task_id)
        self.assertEqual(self.queue.get(first.task_id).attempts, 0)

    def test_reopen_retry(self):
        first = self.advance()
        self.store.close()
        self.store = EpisodeContinuationStore(self.path)
        self.assertEqual(self.advance(), first)

    def test_source_final_unchanged(self):
        self.advance()
        self.assertEqual(self.store.get_episode(self.pid, 1).final_text, '확정 후보')
        self.assertEqual(len(self.store.list_versions(self.pid, 1)), 1)

    def test_stop_at_end(self):
        self.arc = StoryArcPlan(1, (StoryArc(1, 1, 1, 'ARC 1', '목표'),))
        self.plans = plan_episodes(self.arc)
        result = self.advance(end_episode=1, next_plan=None)
        self.assertEqual(result.status, 'STOPPED_AT_END')
        self.assertIsNone(result.task_id)
        self.assertEqual(len(self.store.list_episodes(self.pid)), 1)

    def test_stop_idempotent(self):
        self.arc = StoryArcPlan(1, (StoryArc(1, 1, 1, 'ARC 1', '목표'),))
        self.plans = plan_episodes(self.arc)
        first = self.advance(end_episode=1, next_plan=None)
        self.assertEqual(self.advance(end_episode=1, next_plan=None), first)

    def test_stop_rejects_next_plan(self):
        arc = StoryArcPlan(1, (StoryArc(1, 1, 1, 'ARC 1', '목표'),))
        with self.assertRaises(ContinuationError):
            self.advance(end_episode=1, arc_plan=arc)

    def test_no_confirmation_rejected(self):
        with self.assertRaises(ContinuationError):
            self.advance(confirmation_asserted=False)
        self.assertIsNone(self.store.get_continuation(self.pid, 1))

    def test_non_bool_confirmation_rejected(self):
        with self.assertRaises(ContinuationError):
            self.advance(confirmation_asserted=1)

    def test_stale_revision_rejected(self):
        with self.assertRaises(ContinuationError):
            self.advance(expected_revision=1)

    def test_wrong_version_rejected(self):
        with self.assertRaises(ContinuationError):
            self.advance(expected_version_id='a'*32)

    def test_invalid_version_type_rejected(self):
        with self.assertRaises(ContinuationError):
            self.advance(expected_version_id=None)

    def test_wrong_project_rejected(self):
        with self.assertRaises(ContinuationError):
            self.store.advance_after_confirmation('f'*32, 1, end_episode=3,
                expected_revision=2, expected_version_id=self.version.version_id,
                confirmation_asserted=True, arc_plan=self.arc,
                next_plan=self.plans[1], queue=self.queue)

    def test_changed_final_rejected(self):
        self.store.save_version(self.pid, 1, '수정본', kind='REVISION', expected_revision=2)
        with self.assertRaises(ContinuationError):
            self.advance()

    def test_unversioned_final_rejected(self):
        p = self.store.create_project('다른 작품').project_id
        self.store.create_episode(p, 1)
        self.store.update_episode(p, 1, expected_revision=1, final_text='직접 저장')
        with self.assertRaises(ContinuationError):
            self.store.advance_after_confirmation(p, 1, end_episode=3,
                expected_revision=2, expected_version_id=self.version.version_id,
                confirmation_asserted=True, arc_plan=self.arc,
                next_plan=self.plans[1], queue=self.queue)

    def test_external_mutation_rejected(self):
        self.store.update_episode(self.pid, 1, expected_revision=2, summary='변경')
        with self.assertRaises(ContinuationError):
            self.advance(expected_revision=3)

    def test_invalid_next_plan_rejected(self):
        with self.assertRaises(ContinuationError):
            self.advance(next_plan=None)

    def test_next_plan_number_mismatch(self):
        with self.assertRaises(ContinuationError):
            self.advance(next_plan=replace(self.plans[1], episode_number=3))

    def test_next_plan_arc_mismatch(self):
        with self.assertRaises(ContinuationError):
            self.advance(next_plan=replace(self.plans[1], arc_number=2))

    def test_next_plan_status_mismatch(self):
        with self.assertRaises(ContinuationError):
            self.advance(next_plan=replace(self.plans[1], status='APPROVED'))

    def test_arc_count_mismatch(self):
        arc = StoryArcPlan(2, (StoryArc(1, 1, 2, 'ARC 1', '목표'),))
        with self.assertRaises(ContinuationError):
            self.advance(arc_plan=arc)

    def test_arc_boundary(self):
        arc = StoryArcPlan(3, (StoryArc(1, 1, 1, 'A', '목표'), StoryArc(2, 2, 3, 'B', '목표')))
        plans = plan_episodes(arc)
        result = self.advance(arc_plan=arc, next_plan=plans[1])
        self.assertEqual(result.next_episode, 2)

    def test_bad_arc_boundary(self):
        arc = StoryArcPlan(3, (StoryArc(1, 1, 1, 'A', '목표'), StoryArc(2, 3, 3, 'B', '목표')))
        with self.assertRaises(ContinuationError):
            self.advance(arc_plan=arc)

    def test_existing_next_episode_rejected(self):
        self.store.create_episode(self.pid, 2)
        with self.assertRaises(ContinuationError):
            self.advance()
        self.assertIsNone(self.store.get_continuation(self.pid, 1))

    def test_existing_next_episode_untouched(self):
        self.store.create_episode(self.pid, 2, plot='기존 사용자 설정')
        with self.assertRaises(ContinuationError):
            self.advance()
        self.assertEqual(self.store.get_episode(self.pid, 2).plot, '기존 사용자 설정')

    def test_end_setting_immutable(self):
        self.advance()
        arc = StoryArcPlan(2, (StoryArc(1, 1, 2, 'A', '목표'),))
        with self.assertRaises(ContinuationError):
            self.advance(end_episode=2, arc_plan=arc, next_plan=plan_episodes(arc)[1])

    def test_queue_failure_is_retryable(self):
        with patch.object(self.queue, 'enqueue', side_effect=RuntimeError('private exception')):
            with self.assertRaisesRegex(ContinuationError, '재시도'):
                self.advance()
        self.assertEqual(self.store.get_continuation(self.pid, 1).status, 'PENDING_QUEUE')
        result = self.advance()
        self.assertEqual(result.status, 'QUEUED_DRAFT')
        self.assertEqual(len(self.store.list_episodes(self.pid)), 2)

    def test_queue_failure_no_private_leak(self):
        with patch.object(self.queue, 'enqueue', side_effect=RuntimeError('SECRET PRIVATE')):
            try:
                self.advance()
            except ContinuationError as exc:
                self.assertNotIn('SECRET', str(exc))

    def test_crash_after_enqueue_retry(self):
        original = self.queue.enqueue
        def enqueue_then_fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('after queue commit')
        with patch.object(self.queue, 'enqueue', side_effect=enqueue_then_fail):
            with self.assertRaises(ContinuationError):
                self.advance()
        pending = self.store.get_continuation(self.pid, 1)
        self.assertEqual(self.queue.get(pending.task_id).status, 'QUEUED')
        result = self.advance()
        self.assertEqual(result.task_id, pending.task_id)

    def test_no_task_on_invalid_plan(self):
        with self.assertRaises(ContinuationError):
            self.advance(next_plan=replace(self.plans[1], arc_number=77))
        self.assertEqual(len(self.store.list_episodes(self.pid)), 1)

    def test_no_task_on_no_confirmation(self):
        with self.assertRaises(ContinuationError):
            self.advance(confirmation_asserted=False)
        with closing(sqlite3.connect(self.queue.path)) as db, db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM local_tasks').fetchone()[0], 0)

    def test_different_project_queue_isolation(self):
        result = self.advance()
        self.assertEqual(self.queue.get(result.task_id).project_id, self.pid)

    def test_get_unknown(self):
        self.assertIsNone(self.store.get_continuation(self.pid, 1))

    def test_bad_end_episode(self):
        with self.assertRaises(ContinuationError):
            self.advance(end_episode=1001)

    def test_bad_end_episode_bool(self):
        with self.assertRaises(ContinuationError):
            self.advance(end_episode=True)

    def test_invalid_queue_type(self):
        with self.assertRaises(ContinuationError):
            self.advance(queue=None)

    def test_no_auto_worker_claim(self):
        result = self.advance()
        self.assertEqual(self.queue.get(result.task_id).status, 'QUEUED')
        self.assertEqual(self.queue.get(result.task_id).attempts, 0)

    def test_next_episode_still_requires_review(self):
        result = self.advance()
        self.assertEqual(result.status, 'QUEUED_DRAFT')
        self.assertEqual(self.plans[1].status, 'DRAFT_REQUIRES_USER_APPROVAL')

    def run_next(self, **changes):
        scene = ScenePlan(2, 1, '서고', ('주인공',), '새 단서 찾기', '문이 잠김', '긴장')
        facts = (ContextFact(self.pid, 'novel_bible', 'canon', '사용자 고유 설정'),)
        kwargs = dict(end_episode=3, expected_revision=2,
            expected_version_id=self.version.version_id,
            confirmation_asserted=True, arc_plan=self.arc,
            next_plan=self.plans[1], queue=self.queue,
            next_scenes=(scene,),
            next_context=select_episode_context(self.pid, self.plans[1], facts),
            provider=MockSceneProvider(), checker=OfflineLiteralChecker())
        kwargs.update(changes)
        return continue_episode(self.store, self.pid, 1, **kwargs)

    def test_continue_runs_offline_mock(self):
        result = self.run_next()
        self.assertEqual(result.status, 'AWAITING_HUMAN_REVIEW')
        self.assertEqual(result.run.task.status, 'COMPLETED')
        self.assertEqual(result.run.workflow.preview.provider, 'offline-mock-v1')
        self.assertFalse(result.publication_approved)

    def test_continue_does_not_save_generated_draft(self):
        result = self.run_next()
        self.assertIn('모의 초고', result.run.workflow.preview.draft)
        self.assertEqual(self.store.get_episode(self.pid, 2).draft, '')

    def test_continue_does_not_run_twice(self):
        self.run_next()
        result = self.run_next()
        self.assertEqual(result.status, 'ALREADY_DISPATCHED')
        self.assertIsNone(result.run)

    def test_continue_invalid_scenes_do_not_enqueue(self):
        with self.assertRaises(ContinuationError):
            self.run_next(next_scenes=())
        self.assertIsNone(self.store.get_continuation(self.pid, 1))

    def test_continue_missing_context_does_not_enqueue(self):
        with self.assertRaises(ContinuationError):
            self.run_next(next_context=None)
        self.assertIsNone(self.store.get_continuation(self.pid, 1))

    def test_continue_missing_provider_does_not_enqueue(self):
        with self.assertRaises(ContinuationError):
            self.run_next(provider=None)
        self.assertIsNone(self.store.get_continuation(self.pid, 1))

    def test_continue_stop_does_not_run_provider(self):
        arc = StoryArcPlan(1, (StoryArc(1, 1, 1, 'A', '목표'),))
        result = self.run_next(end_episode=1, arc_plan=arc, next_plan=None,
                               next_scenes=None, next_context=None,
                               provider=None, checker=None)
        self.assertEqual(result.status, 'STOPPED_AT_END')
        self.assertIsNone(result.run)

    def test_continue_checker_blocks_without_publication(self):
        result = self.run_next(checker=OfflineLiteralChecker(('모의 초고',)))
        self.assertEqual(result.status, 'REWRITE_REQUIRED_NOT_IMPLEMENTED')
        self.assertFalse(result.publication_approved)

    def test_continue_requires_confirmation(self):
        with self.assertRaises(ContinuationError):
            self.run_next(confirmation_asserted=False)
        self.assertIsNone(self.store.get_continuation(self.pid, 1))


if __name__ == '__main__':
    unittest.main()
