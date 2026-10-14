"""Stage 66 controller state transitions, failure gates and offline-only checks."""
from dataclasses import replace
from hashlib import sha256
import socket
import unittest
from unittest.mock import patch

from ai_novel_factory.episode_context import ContextFact, select_episode_context
from ai_novel_factory.episode_planner import EpisodePlan
from ai_novel_factory.local_models import MockSceneProvider
from ai_novel_factory.orchestrator import (
    OfflineLiteralChecker, OrchestrationError, orchestrate_episode,
)
from ai_novel_factory.scene_planner import ScenePlan


class OrchestratorStage66Tests(unittest.TestCase):
    def setUp(self):
        self.project = 'novel-1'
        self.episode = EpisodePlan(5, 1, '단서', ('발견',), ('hero',), '', (), '후킹')
        self.scenes = (
            ScenePlan(5, 1, '서재', ('hero',), '단서 수집', '문 잠김', '긴장'),
            ScenePlan(5, 2, '복도', ('hero',), '탈출', '경비원', '불안'),
        )
        self.facts = (ContextFact(self.project, 'novel_bible', 'rule', '초능력 불가'),)
        self.context = select_episode_context(self.project, self.episode, self.facts)
        self.provider = MockSceneProvider()
        self.checker = OfflineLiteralChecker()

    def run_workflow(self, **kw):
        return orchestrate_episode(kw.get('project', self.project), kw.get('episode', self.episode),
                                   kw.get('scenes', self.scenes), kw.get('context', self.context),
                                   kw.get('provider', self.provider), kw.get('checker', self.checker),
                                   local_execution_approved=kw.get('approved', False))

    def test_happy_path_transitions(self):
        result = self.run_workflow()
        self.assertEqual(result.status, 'AWAITING_HUMAN_REVIEW')
        self.assertEqual([(e.step, e.status) for e in result.events], [
            ('PLANNER', 'VALIDATED'), ('WRITER', 'DRAFTED'), ('WRITER', 'DRAFTED'),
            ('ASSEMBLER', 'ASSEMBLED'), ('CHECKER', 'PRELIMINARY_PASS'),
            ('HUMAN_GATE', 'PENDING')])
        self.assertEqual([e.sequence for e in result.events], list(range(1, 7)))
        self.assertEqual([e.scene_number for e in result.events if e.step == 'WRITER'], [1, 2])

    def test_combined_text_is_unmodified_and_provenance_valid(self):
        result = self.run_workflow()
        self.assertEqual(result.preview.draft_sha256, sha256(result.preview.draft.encode()).hexdigest())
        self.assertEqual(len(result.preview.scenes), 2)
        self.assertEqual(result.preview.canon_fact_ids, ('rule',))
        self.assertEqual(result.preview.provider, 'offline-mock-v1')

    def test_no_approval_no_persistence_no_memory_update(self):
        result = self.run_workflow()
        self.assertFalse(result.persisted)
        self.assertFalse(result.publication_approved)
        self.assertFalse(result.memory_updated)
        self.assertFalse(result.rewritten)
        self.assertFalse(result.preview.persisted)
        self.assertFalse(result.preview.publication_approved)
        self.assertEqual(result.preliminary_check.scope, 'LITERAL_TERMS_ONLY_NOT_FULL_QC')

    def test_rule_issue_blocks_progress_and_never_rewrites(self):
        result = self.run_workflow(checker=OfflineLiteralChecker(('단서 수집',)))
        self.assertEqual(result.status, 'REWRITE_REQUIRED_NOT_IMPLEMENTED')
        self.assertFalse(result.preliminary_check.passed)
        self.assertEqual(result.preliminary_check.finding_count, 1)
        self.assertEqual(result.preliminary_check.finding_term_hashes,
                         (sha256('단서 수집'.encode()).hexdigest(),))
        self.assertEqual(result.events[-1].status, 'BLOCKED')
        self.assertFalse(result.rewritten)

    def test_nonmatching_rules_allow_preliminary_review_only(self):
        result = self.run_workflow(checker=OfflineLiteralChecker(('완전히 없는 구절',)))
        self.assertEqual(result.status, 'AWAITING_HUMAN_REVIEW')
        self.assertTrue(result.preliminary_check.passed)
        self.assertNotEqual(result.status, 'PUBLISHED')

    def test_provider_failure_discards_partial_drafts_and_reports_state(self):
        count = 0
        original = MockSceneProvider.generate
        def fail_second(provider, request):
            nonlocal count
            count += 1
            if count == 2:
                raise RuntimeError('SECRET_PRIVATE_MANUSCRIPT')
            return original(provider, request)
        with patch.object(MockSceneProvider, 'generate', fail_second):
            result = self.run_workflow()
        self.assertEqual(result.status, 'FAILED')
        self.assertEqual(result.error_code, 'SCENE_DRAFT_FAILED')
        self.assertIsNone(result.preview)
        self.assertIsNone(result.preliminary_check)
        self.assertEqual([e.step for e in result.events], ['PLANNER', 'WRITER', 'WORKFLOW'])
        self.assertEqual(result.events[-1].status, 'FAILED')
        self.assertNotIn('SECRET_PRIVATE_MANUSCRIPT', str(result))

    def test_assembly_failure_does_not_call_checker(self):
        with patch('ai_novel_factory.orchestrator.assemble_episode_draft', side_effect=__import__(
                'ai_novel_factory.episode_assembler', fromlist=['EpisodeAssemblyError']).EpisodeAssemblyError('SECRET')):
            with patch.object(OfflineLiteralChecker, 'check', side_effect=AssertionError('not reached')):
                result = self.run_workflow()
        self.assertEqual(result.error_code, 'ASSEMBLY_FAILED')
        self.assertIsNone(result.preview)
        self.assertEqual(result.events[-1].step, 'WORKFLOW')

    def test_checker_error_fails_closed_and_hides_input(self):
        with patch.object(OfflineLiteralChecker, 'check', side_effect=OrchestrationError('SECRET')):
            result = self.run_workflow()
        self.assertEqual(result.error_code, 'CHECK_FAILED')
        self.assertEqual(result.status, 'FAILED')
        self.assertNotIn('SECRET', str(result))

    def test_unexpected_checker_exception_is_sanitized(self):
        with patch.object(OfflineLiteralChecker, 'check', side_effect=RuntimeError('SECRET_MANUSCRIPT')):
            result = self.run_workflow()
        self.assertEqual(result.error_code, 'UNEXPECTED_FAILURE')
        self.assertIsNone(result.preview)
        self.assertNotIn('SECRET_MANUSCRIPT', str(result))

    def test_local_process_requires_separate_consent(self):
        from ai_novel_factory.local_models import LocalExecutableProvider
        from pathlib import Path
        import sys
        # Only construct a known Python executable here; never launch it.
        adapter = LocalExecutableProvider(sys.executable, explicitly_allowed=True)
        with patch.object(LocalExecutableProvider, 'generate', side_effect=AssertionError('must not launch')):
            with self.assertRaises(OrchestrationError):
                self.run_workflow(provider=adapter, approved=False)

    def test_invalid_plan_stops_before_writer(self):
        with patch.object(MockSceneProvider, 'generate', side_effect=AssertionError('must not be invoked')):
            with self.assertRaises(OrchestrationError):
                self.run_workflow(scenes=(replace(self.scenes[0], goal=''), self.scenes[1]))

    def test_duplicate_scene_rejected_before_writer(self):
        with self.assertRaises(OrchestrationError):
            self.run_workflow(scenes=(self.scenes[0], self.scenes[0]))

    def test_wrong_project_rejected(self):
        with self.assertRaises(OrchestrationError): self.run_workflow(project='other')

    def test_wrong_episode_context_rejected(self):
        with self.assertRaises(OrchestrationError):
            self.run_workflow(context=replace(self.context, episode_number=6))

    def test_wrong_context_status_rejected(self):
        with self.assertRaises(OrchestrationError):
            self.run_workflow(context=replace(self.context, status='PUBLISHED'))

    def test_unapproved_episode_rejected(self):
        with self.assertRaises(OrchestrationError):
            self.run_workflow(episode=replace(self.episode, status='PUBLISHED'))

    def test_unsupported_checker_rejected(self):
        class Evil:
            def check(self, preview): raise AssertionError('must not be called')
        with self.assertRaises(OrchestrationError): self.run_workflow(checker=Evil())

    def test_unsupported_provider_rejected(self):
        class Evil:
            provider_id = 'offline-mock-v1'
            def generate(self, request): raise AssertionError('must not be called')
        with self.assertRaises(OrchestrationError): self.run_workflow(provider=Evil())

    def test_subclass_checker_rejected(self):
        class EvilChecker(OfflineLiteralChecker):
            def check(self, preview): raise AssertionError('must not be called')
        with self.assertRaises(OrchestrationError): self.run_workflow(checker=EvilChecker())

    def test_invalid_explicit_approval_rejected(self):
        with self.assertRaises(OrchestrationError): self.run_workflow(approved=1)

    def test_checker_rules_validation(self):
        for invalid in ([1], ('',), ('x\x00y',), ('a', 'a'), ('x' * 121,), ('x',) * 51):
            with self.subTest(invalid=str(invalid)[:20]), self.assertRaises(OrchestrationError):
                OfflineLiteralChecker(invalid)

    def test_deterministic_repetition(self):
        self.assertEqual(self.run_workflow(), self.run_workflow())

    def test_no_network_and_no_file_access_by_mock(self):
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('unexpected network')):
            with patch('builtins.open', side_effect=AssertionError('unexpected file I/O')):
                self.assertEqual(self.run_workflow().status, 'AWAITING_HUMAN_REVIEW')

    def test_empty_rules_are_preliminary_only(self):
        self.assertTrue(self.run_workflow().preliminary_check.passed)
        self.assertIn('NOT_FULL_QC', self.run_workflow().preliminary_check.scope)

    def test_three_scenes_event_count(self):
        scene = replace(self.scenes[1], scene_number=3)
        middle = replace(self.scenes[1], scene_number=2)
        result = self.run_workflow(scenes=(self.scenes[0], middle, scene))
        self.assertEqual(len([e for e in result.events if e.step == 'WRITER']), 3)
        self.assertEqual(len(result.preview.scenes), 3)

    def test_rule_term_not_in_event_log(self):
        result = self.run_workflow(checker=OfflineLiteralChecker(('단서 수집',)))
        self.assertNotIn('단서 수집', str(result.events))


if __name__ == '__main__':
    unittest.main()
