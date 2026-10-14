"""Stage 70: real one-episode, queue, controls and retry integration (offline mock only)."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import socket
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory.episode_context import ContextFact, select_episode_context
from ai_novel_factory.episode_integration import EpisodeIntegrationError, run_one_episode
from ai_novel_factory.episode_planner import EpisodePlan
from ai_novel_factory.local_models import MockSceneProvider
from ai_novel_factory.local_task_queue import LocalTaskQueue
from ai_novel_factory.orchestrator import OfflineLiteralChecker, orchestrate_episode
from ai_novel_factory.retry_checkpoint import RetryCheckpointCoordinator, RetryableStepError
from ai_novel_factory.scene_planner import ScenePlan
from ai_novel_factory.task_monitor import TaskMonitor


class SingleEpisodeIntegrationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'tasks.sqlite3'
        self.queue = LocalTaskQueue(self.path)
        self.project = 'test-novel'
        self.episode = EpisodePlan(7, 2, '잃어버린 지도 찾기', ('지도 발견',),
                                   ('hero',), '불안에서 희망', (), '누가 왔는가')
        self.scenes = (
            ScenePlan(7, 1, '도서관', ('hero',), '지도 단서 수집', '문이 잠김', '긴장'),
            ScenePlan(7, 2, '광장', ('hero',), '지도를 확보', '추적자 등장', '불안'),
        )
        facts = (
            ContextFact(self.project, 'novel_bible', 'canon1', '장면은 오리지널 세계의 규칙을 따른다'),
            ContextFact(self.project, 'style_bible', 'style1', '짧은 문장을 우선 사용한다'),
        )
        self.context = select_episode_context(self.project, self.episode, facts)
        self.provider = MockSceneProvider()
        self.checker = OfflineLiteralChecker()
        self.queue.enqueue(self.project, 7, task_id='one-ep')

    def run_episode(self, **changes):
        return run_one_episode(self.queue, changes.get('task_id','one-ep'),
                               changes.get('project',self.project),
                               changes.get('episode',self.episode),
                               changes.get('scenes',self.scenes),
                               changes.get('context',self.context),
                               changes.get('provider',self.provider),
                               changes.get('checker',self.checker),
                               local_execution_approved=changes.get('approval',False))

    def test_end_to_end_complete_episode_awaits_human_review(self):
        result = self.run_episode()
        self.assertEqual(result.task.status, 'COMPLETED')
        self.assertEqual(result.status, 'AWAITING_HUMAN_REVIEW')
        self.assertEqual([ev.step for ev in result.workflow.events],
                         ['PLANNER','WRITER','WRITER','ASSEMBLER','CHECKER','HUMAN_GATE'])
        self.assertEqual(result.workflow.preliminary_check.scope,
                         'LITERAL_TERMS_ONLY_NOT_FULL_QC')
        self.assertEqual(result.workflow.preview.canon_fact_ids, ('canon1',))
        self.assertEqual(result.workflow.preview.provider, 'offline-mock-v1')
        self.assertEqual(result.workflow.preview.draft_sha256,
                         sha256(result.workflow.preview.draft.encode()).hexdigest())
        self.assertEqual(len(result.workflow.preview.scenes), 2)
        self.assertTrue(all(not getattr(result,key) for key in
                            ('approved','manuscript_saved','published','memory_updated')))

    def test_scene_spans_preserve_exact_concatenation(self):
        result = self.run_episode()
        draft = result.workflow.preview.draft
        spans = result.workflow.preview.scenes
        self.assertLess(spans[0].end, spans[1].start)
        self.assertTrue(draft[spans[0].start:spans[0].end].startswith('[모의 초고'))
        self.assertTrue(draft[spans[1].start:spans[1].end].startswith('[모의 초고'))
        self.assertEqual(draft[spans[0].end:spans[1].start], '\n\n')

    def test_status_is_task_only_not_quality_or_publication(self):
        result = self.run_episode()
        self.assertFalse(result.workflow.persisted)
        self.assertFalse(result.workflow.preview.persisted)
        self.assertFalse(result.workflow.publication_approved)
        self.assertFalse(result.workflow.memory_updated)
        self.assertFalse(result.workflow.rewritten)

    def test_queue_contains_no_generated_text_or_canon(self):
        preview = self.run_episode().workflow.preview
        raw = self.path.read_bytes()
        self.assertNotIn(preview.draft.encode(), raw)
        self.assertNotIn('장면은 오리지널 세계'.encode(), raw)
        self.assertNotIn('지도 단서 수집'.encode(), raw)

    def test_task_progress_is_terminal_and_scoped(self):
        self.run_episode()
        snapshot = TaskMonitor(self.queue).get('one-ep')
        self.assertEqual((snapshot.status,snapshot.progress,snapshot.stage),
                         ('COMPLETED',100,'FINISHED'))
        self.assertEqual((snapshot.project_id,snapshot.episode_number),(self.project,7))

    def test_cannot_execute_same_job_twice(self):
        first = self.run_episode()
        with patch.object(MockSceneProvider,'generate',side_effect=AssertionError('duplicate')):
            second = self.run_episode()
        self.assertIsNone(second)
        self.assertEqual(first.task.attempts,1)
        self.assertEqual(self.queue.get('one-ep').attempts,1)

    def test_unrelated_queued_task_is_not_claimed(self):
        self.queue.enqueue('other-project',7,task_id='other')
        self.assertIsNone(self.run_episode(task_id='other'))
        self.assertEqual(self.queue.get('other').status,'QUEUED')
        self.assertEqual(self.queue.get('one-ep').status,'QUEUED')

    def test_wrong_project_rejected_without_claim(self):
        with self.assertRaises(EpisodeIntegrationError): self.run_episode(project='other-project')
        self.assertEqual(self.queue.get('one-ep').status,'QUEUED')

    def test_wrong_episode_rejected_without_claim(self):
        with self.assertRaises(EpisodeIntegrationError):
            self.run_episode(episode=replace(self.episode,episode_number=8))
        self.assertEqual(self.queue.get('one-ep').status,'QUEUED')

    def test_incomplete_scene_rejected_before_provider(self):
        broken = (replace(self.scenes[0],location=''),self.scenes[1])
        with patch.object(MockSceneProvider,'generate',side_effect=AssertionError('do not run')):
            with self.assertRaises(EpisodeIntegrationError):self.run_episode(scenes=broken)
        self.assertEqual(self.queue.get('one-ep').status,'QUEUED')

    def test_duplicate_scene_rejected(self):
        with self.assertRaises(EpisodeIntegrationError):
            self.run_episode(scenes=(self.scenes[0],self.scenes[0]))

    def test_bad_provider_subclass_rejected(self):
        class RemoteMock(MockSceneProvider):
            def generate(self,request):raise AssertionError('should not be called')
        with self.assertRaises(EpisodeIntegrationError):self.run_episode(provider=RemoteMock())
        self.assertEqual(self.queue.get('one-ep').status,'QUEUED')

    def test_wrong_checker_rejected(self):
        with self.assertRaises(EpisodeIntegrationError):self.run_episode(checker=None)
        self.assertEqual(self.queue.get('one-ep').status,'QUEUED')

    def test_invalid_approval_rejected(self):
        with self.assertRaises(EpisodeIntegrationError):self.run_episode(approval=1)

    def test_literal_issue_not_treated_as_quality_success(self):
        result = self.run_episode(checker=OfflineLiteralChecker(('지도 단서 수집',)))
        self.assertEqual(result.status,'REWRITE_REQUIRED_NOT_IMPLEMENTED')
        self.assertFalse(result.workflow.preliminary_check.passed)
        self.assertEqual(result.task.status,'COMPLETED')  # task only, NOT accepted manuscript
        self.assertFalse(result.approved)

    def test_provider_failure_redacts_and_does_not_return_partial_draft(self):
        original = MockSceneProvider.generate
        count = 0
        def fail_second(provider,request):
            nonlocal count
            count += 1
            if count == 2:raise RuntimeError('PRIVATE_SECRET_TOKEN')
            return original(provider,request)
        with patch.object(MockSceneProvider,'generate',fail_second):
            result = self.run_episode()
        self.assertEqual(result.status,'FAILED')
        self.assertEqual(result.task.status,'FAILED')
        self.assertEqual(result.task.error_code,'SCENE_DRAFT_FAILED')
        self.assertIsNone(result.workflow)
        self.assertNotIn(b'PRIVATE_SECRET_TOKEN',self.path.read_bytes())

    def test_cancel_before_claim_returns_none(self):
        TaskMonitor(self.queue).request_cancel('one-ep')
        self.assertIsNone(self.run_episode())
        self.assertEqual(self.queue.get('one-ep').status,'INTERRUPTED')

    def test_paused_queued_task_does_not_claim(self):
        TaskMonitor(self.queue).request_pause('one-ep')
        self.assertIsNone(self.run_episode())
        self.assertEqual(self.queue.get('one-ep').status,'QUEUED')
        TaskMonitor(self.queue).request_resume('one-ep')
        self.assertEqual(self.run_episode().task.status,'COMPLETED')

    def test_cancel_during_model_step_prevents_exposure(self):
        original = MockSceneProvider.generate
        def cancel_during(provider,request):
            TaskMonitor(self.queue).request_cancel('one-ep')
            return original(provider,request)
        with patch.object(MockSceneProvider,'generate',cancel_during):
            result = self.run_episode()
        self.assertEqual(result.status,'INTERRUPTED')
        self.assertIsNone(result.workflow)
        self.assertEqual(result.task.error_code,'TASK_CANCELLED')

    def test_failure_does_not_retry_automatically(self):
        with patch.object(MockSceneProvider,'generate',side_effect=RuntimeError('failure')):
            failed = self.run_episode()
        self.assertEqual(failed.task.attempts,1)
        self.assertIsNone(self.run_episode())
        self.assertEqual(self.queue.get('one-ep').attempts,1)

    def test_offline_no_socket_connection(self):
        with patch.object(socket.socket,'connect',side_effect=AssertionError('unexpected socket')):
            self.assertEqual(self.run_episode().status,'AWAITING_HUMAN_REVIEW')

    def test_database_persists_task_after_restart(self):
        self.run_episode()
        fresh = LocalTaskQueue(self.path)
        self.assertEqual(fresh.get('one-ep').status,'COMPLETED')
        self.assertIsNone(run_one_episode(fresh,'one-ep',self.project,self.episode,
                                          self.scenes,self.context,self.provider,self.checker))

    def test_stage69_checkpoint_retry_uses_real_orchestrator_and_no_final_save(self):
        """Use real orchestration output as caller-owned checkpoint artifacts."""
        coordinator = RetryCheckpointCoordinator(self.queue)
        artifacts = {}
        calls = []
        context_digest = sha256(repr((self.episode,self.scenes,self.context)).encode()).hexdigest()
        steps = ('PLAN','DRAFT','CHECK')
        def execute(name,index,prior):
            calls.append(name)
            if name == 'PLAN':
                material = context_digest.encode()
            elif name == 'DRAFT':
                run = orchestrate_episode(self.project,self.episode,self.scenes,self.context,
                                           self.provider,self.checker)
                self.assertEqual(run.status,'AWAITING_HUMAN_REVIEW')
                material = run.preview.draft.encode('utf-8')
            elif name == 'CHECK':
                self.assertEqual(prior[0],context_digest.encode())
                self.assertEqual(sha256(prior[1]).hexdigest(),sha256(artifacts['DRAFT']).hexdigest())
                material = b'PRELIMINARY_ONLY_HUMAN_REVIEW_PENDING'
            artifacts[name] = material
            return material
        def fail_check(name,index,prior):
            if name == 'CHECK':raise RetryableStepError('private failure detail')
            return execute(name,index,prior)
        first = coordinator.run_task('one-ep',self.project,7,steps,
                 context_sha256=context_digest,execute=fail_check,
                 restore=lambda name,index:artifacts[name])
        self.assertEqual(first.task.status,'FAILED')
        self.assertEqual(first.task.error_code,'LOCAL_PROVIDER_TRANSIENT')
        self.assertEqual(len(coordinator.checkpoints('one-ep')),2)
        self.assertEqual(coordinator.retry_failed('one-ep').status,'QUEUED')
        second = coordinator.run_task('one-ep',self.project,7,steps,
                 context_sha256=context_digest,execute=execute,
                 restore=lambda name,index:artifacts[name])
        self.assertEqual(second.task.status,'COMPLETED')
        self.assertEqual(second.reused_steps,2)
        self.assertEqual(calls,['PLAN','DRAFT','CHECK'])
        self.assertEqual(second.artifacts[1],artifacts['DRAFT'])
        self.assertFalse(second.final_saved)
        self.assertFalse(second.approved)
        self.assertFalse(second.published)
        self.assertNotIn(artifacts['DRAFT'],self.path.read_bytes())
        self.assertNotIn(b'private failure detail',self.path.read_bytes())

    def test_stage69_corrupt_draft_blocks_resume_with_real_orchestration(self):
        coordinator = RetryCheckpointCoordinator(self.queue)
        artifacts = {}
        digest = sha256(b'validated-canon').hexdigest()
        def execute(name,index,prior):
            if name == 'PLAN':val=b'plan-v1'
            elif name == 'DRAFT':
                val=orchestrate_episode(self.project,self.episode,self.scenes,self.context,
                                       self.provider,self.checker).preview.draft.encode()
            else:raise RetryableStepError()
            artifacts[name]=val
            return val
        coordinator.run_task('one-ep',self.project,7,('PLAN','DRAFT','CHECK'),
                             context_sha256=digest,execute=execute,
                             restore=lambda name,i:artifacts[name])
        coordinator.retry_failed('one-ep')
        artifacts['DRAFT']=b'manipulated-draft'
        with patch.object(MockSceneProvider,'generate',side_effect=AssertionError('must not regenerate')):
            result=coordinator.run_task('one-ep',self.project,7,('PLAN','DRAFT','CHECK'),
                         context_sha256=digest,execute=execute,
                         restore=lambda name,i:artifacts[name])
        self.assertEqual(result.task.status,'FAILED')
        self.assertEqual(result.task.error_code,'CHECKPOINT_EXECUTION_FAILED')
        self.assertEqual(result.artifacts,())

    def test_checkpoint_context_change_cannot_resume_real_draft(self):
        coordinator=RetryCheckpointCoordinator(self.queue)
        material={}
        digest=sha256(b'original').hexdigest()
        def execute(name,index,prior):
            if name == 'CHECK':raise RetryableStepError()
            val=(b'plan' if name=='PLAN' else orchestrate_episode(
                 self.project,self.episode,self.scenes,self.context,self.provider,self.checker).preview.draft.encode())
            material[name]=val
            return val
        coordinator.run_task('one-ep',self.project,7,('PLAN','DRAFT','CHECK'),
                             context_sha256=digest,execute=execute,
                             restore=lambda n,i:material[n])
        coordinator.retry_failed('one-ep')
        with patch.object(MockSceneProvider,'generate',side_effect=AssertionError('do not regenerate')):
            result=coordinator.run_task('one-ep',self.project,7,('PLAN','DRAFT','CHECK'),
                         context_sha256=sha256(b'changed').hexdigest(),execute=execute,
                         restore=lambda n,i:material[n])
        self.assertEqual(result.task.error_code,'CHECKPOINT_EXECUTION_FAILED')
        self.assertEqual(result.artifacts,())


if __name__ == '__main__':
    unittest.main()
