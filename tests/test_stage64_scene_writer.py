"""Stage 64: offline end-to-end single-scene draft integration."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory.episode_context import ContextFact, select_episode_context
from ai_novel_factory.episode_planner import EpisodePlan
from ai_novel_factory.local_models import LocalExecutableProvider, LocalModelError, MockSceneProvider
from ai_novel_factory.scene_planner import ScenePlan
from ai_novel_factory.scene_writer import SceneWriterError, generate_scene_draft


class Stage64SceneDraftTests(unittest.TestCase):
    def setUp(self):
        self.episode = EpisodePlan(4, 1, '증거 발견', ('비밀 문서 확인',), ('C1',), '', (), '')
        self.scene = ScenePlan(4, 1, '보관실', ('C1',), '문서 확보', '경비원 경계', '긴장')
        self.facts = (
            ContextFact('new-book', 'novel_bible', 'rule', '시간 이동 불가'),
            ContextFact('new-book', 'character', 'hero', '주인공은 탐정', character_ids=('C1',)),
            ContextFact('new-book', 'style_bible', 'voice', '짧은 문단'),
            ContextFact('new-book', 'timeline', 'later', '미래 사건', episode_start=5),
        )
        self.context = select_episode_context('new-book', self.episode, self.facts)
        self.provider = MockSceneProvider()

    def generate(self, **kwargs):
        return generate_scene_draft(kwargs.get('project', 'new-book'),
                                    kwargs.get('episode', self.episode),
                                    kwargs.get('scene', self.scene),
                                    kwargs.get('context', self.context),
                                    kwargs.get('provider', self.provider),
                                    local_execution_approved=kwargs.get('approved', False))

    def test_complete_mock_draft_contract(self):
        out = self.generate()
        self.assertEqual((out.result.project_id, out.result.episode_number,
                          out.result.scene_number), ('new-book', 4, 1))
        self.assertIn('실제 AI 생성 아님', out.result.draft)
        self.assertEqual(out.result.provider, 'offline-mock-v1')
        self.assertEqual(out.origin, 'DETERMINISTIC_MOCK_NOT_AI')
        self.assertEqual(out.status, 'DRAFT_REQUIRES_USER_APPROVAL')
        self.assertFalse(out.persisted)
        self.assertFalse(out.result.persisted)
        self.assertFalse(out.publication_approved)

    def test_canon_provenance(self):
        out = self.generate()
        self.assertEqual(out.canon_fact_ids, ('rule',))
        self.assertEqual(set(out.supporting_fact_ids), {'hero', 'voice'})
        self.assertNotIn('later', out.supporting_fact_ids)
        self.assertNotIn('시간 이동 불가', out.result.draft)
        self.assertNotIn('미래 사건', out.result.draft)

    def test_sha256_and_determinism(self):
        a = self.generate()
        self.assertEqual(a, self.generate())
        self.assertEqual(len(a.prompt_sha256), 64)
        self.assertEqual(a.draft_sha256, hashlib.sha256(a.result.draft.encode()).hexdigest())
        self.assertNotEqual(a.prompt_sha256, a.draft_sha256)

    def test_different_scene_changes_request_hash(self):
        other = replace(self.scene, scene_number=2)
        self.assertNotEqual(self.generate().prompt_sha256, self.generate(scene=other).prompt_sha256)

    def test_reject_other_project_and_future_facts(self):
        with self.assertRaises(SceneWriterError): self.generate(project='another-book')
        altered = replace(self.context, facts=self.context.facts + (self.facts[-1],))
        with self.assertRaises(SceneWriterError): self.generate(context=altered)

    def test_reject_wrong_episode(self):
        with self.assertRaises(SceneWriterError): self.generate(scene=replace(self.scene, episode_number=5))

    def test_reject_incomplete_scene(self):
        with self.assertRaises(SceneWriterError): self.generate(scene=replace(self.scene, goal=''))

    def test_reject_reference_novel_source(self):
        altered = replace(self.context, facts=self.context.facts +
                          (ContextFact('new-book', 'reference_novel', 'raw', 'original novel text'),))
        with self.assertRaises(SceneWriterError): self.generate(context=altered)

    def test_reject_missing_novel_bible(self):
        altered = replace(self.context, facts=tuple(f for f in self.context.facts if f.source != 'novel_bible'))
        with self.assertRaises(SceneWriterError): self.generate(context=altered)

    def test_reject_unapproved_plan(self):
        with self.assertRaises(SceneWriterError): self.generate(scene=replace(self.scene, status='PUBLISHED'))

    def test_provider_none_not_invoked(self):
        with self.assertRaises(SceneWriterError): self.generate(provider=None)

    def test_forged_provider_id_rejected_before_execution(self):
        class Forged:
            provider_id = 'offline-mock-v1'
            def generate(self, request):
                raise AssertionError('must not be invoked')
        with self.assertRaises(SceneWriterError): self.generate(provider=Forged())

    def test_subclass_provider_rejected(self):
        class UnknownMock(MockSceneProvider):
            pass
        with self.assertRaises(SceneWriterError): self.generate(provider=UnknownMock())

    def test_mock_no_network(self):
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
            self.assertTrue(self.generate().result.draft)

    def test_provider_error_sanitized(self):
        with patch.object(MockSceneProvider, 'generate', side_effect=RuntimeError('sensitive source content')):
            with self.assertRaises(SceneWriterError) as ctx: self.generate()
        self.assertNotIn('sensitive source content', str(ctx.exception))

    def test_invalid_mock_draft_rejected(self):
        with patch.object(MockSceneProvider, 'generate', return_value=''):
            with self.assertRaises(SceneWriterError): self.generate()

    def test_no_file_writes(self):
        with patch('builtins.open', side_effect=AssertionError('unexpected file read/write')):
            self.generate()

    def _local_worker(self, content: str):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        path = Path(d.name) / 'worker.py'
        path.write_text(content, encoding='utf-8')
        return LocalExecutableProvider(sys.executable, arguments=(str(path),),
                                       explicitly_allowed=True, timeout_seconds=5)

    def test_real_local_process_with_explicit_approval(self):
        p = self._local_worker('''import json,sys
payload = json.load(sys.stdin)
assert payload['request']['novel_bible'].startswith('[최우선:')
assert payload['request']['episode_number'] == 4
assert '시간 이동 불가' in payload['request']['novel_bible']
assert '미래 사건' not in payload['request']['novel_bible']
print(json.dumps({'protocol':'anf-local-scene-v1','draft':'장면 초고 테스트 문장'}))
''')
        out = self.generate(provider=p, approved=True)
        self.assertEqual(out.result.draft, '장면 초고 테스트 문장')
        self.assertEqual(out.origin, 'LOCAL_EXECUTABLE_OUTPUT_NOT_VERIFIED_AS_AI')
        self.assertFalse(out.publication_approved)

    def test_local_process_requires_second_approval(self):
        p = self._local_worker('raise AssertionError("must not launch")')
        with self.assertRaisesRegex(SceneWriterError, 'approval'):
            self.generate(provider=p)

    def test_local_process_invalid_response_fails_closed(self):
        p = self._local_worker("print('not json')")
        with self.assertRaises(SceneWriterError): self.generate(provider=p, approved=True)

    def test_invalid_approval_values_rejected(self):
        p = self._local_worker("raise AssertionError('must not launch')")
        for value in (1, 'yes', None, False):
            with self.subTest(value=value), self.assertRaises(SceneWriterError):
                self.generate(provider=p, approved=value)


if __name__ == '__main__':
    unittest.main()
