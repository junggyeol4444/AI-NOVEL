"""Stage 61: strictly local provider contract and executable IPC."""
from dataclasses import replace
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory.local_models import (PROTOCOL_VERSION, SceneDraftRequest,
    SceneDraftResult, MockSceneProvider, LocalExecutableProvider, LocalModelError,
    draft_scene, validate_request, _message)


class OfflineModelTests(unittest.TestCase):
    def setUp(self):
        self.request = SceneDraftRequest('work-1', 3, 2, '작품 고유 설정', '열쇠 찾기',
                                         '문이 잠김', '서재', ('주인공',), '3인칭')

    def test_mock_scene_draft_is_unapproved_and_not_saved(self):
        result = draft_scene(self.request, MockSceneProvider())
        self.assertEqual((result.episode_number, result.scene_number), (3, 2))
        self.assertIn('실제 AI 생성 아님', result.draft)
        self.assertFalse(result.persisted)
        self.assertEqual(result.status, 'DRAFT_REQUIRES_USER_APPROVAL')

    def test_deterministic_and_does_not_copy_canon(self):
        a = draft_scene(self.request, MockSceneProvider())
        self.assertEqual(a, draft_scene(self.request, MockSceneProvider()))
        self.assertNotIn('작품 고유 설정', a.draft)

    def test_novel_bible_is_first_in_json_request(self):
        req = _message(self.request)['request']
        self.assertEqual(next(iter(req)), 'novel_bible')
        self.assertEqual(req['novel_bible'], '작품 고유 설정')
        self.assertNotIn('reference_novel', req)
        self.assertNotIn('api_key', req)

    def test_project_id_validation(self):
        for val in ('', '   ', 'x'*129, 42, None):
            with self.subTest(val=val), self.assertRaises(LocalModelError):
                validate_request(replace(self.request, project_id=val))

    def test_episode_scene_validation(self):
        for key in ('episode_number', 'scene_number'):
            for val in (0, -1, True, 1.0, '1'):
                with self.subTest(key=key, val=val), self.assertRaises(LocalModelError):
                    validate_request(replace(self.request, **{key: val}))

    def test_canon_and_required_fields_rejected_when_empty_or_huge(self):
        for key in ('novel_bible', 'scene_goal', 'scene_conflict', 'scene_location'):
            for val in ('', '  ', 'x'*30001, 'a\x00b'):
                with self.subTest(key=key, val=val[:10]), self.assertRaises(LocalModelError):
                    validate_request(replace(self.request, **{key: val}))

    def test_characters_rejected(self):
        for val in ([], (), ('',), ('a\x00b',), ('x'*201,), ('x',)*101):
            with self.subTest(), self.assertRaises(LocalModelError):
                validate_request(replace(self.request, characters=val))

    def test_cumulative_context_limit(self):
        with self.assertRaises(LocalModelError):
            validate_request(replace(self.request, novel_bible='가'*20000, style_bible='나'*15000))

    def test_invalid_provider_rejected(self):
        for val in (None, object(), type('Fake', (), {'provider_id':'https-api', 'generate':lambda *a: 'text'})()):
            with self.subTest(), self.assertRaises(LocalModelError):
                draft_scene(self.request, val)

    def test_mock_makes_no_network_calls(self):
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
            self.assertIn('모의 초고', draft_scene(self.request, MockSceneProvider()).draft)

    def test_executable_requires_explicit_opt_in(self):
        with self.assertRaises(LocalModelError):
            LocalExecutableProvider(sys.executable)

    def test_executable_requires_absolute_local_file(self):
        with self.assertRaises(LocalModelError):
            LocalExecutableProvider('https://example.com/api', explicitly_allowed=True)
        with self.assertRaises(LocalModelError):
            LocalExecutableProvider('/does/not/exist', explicitly_allowed=True)

    def test_argument_validation(self):
        with self.assertRaises(LocalModelError):
            LocalExecutableProvider(sys.executable, explicitly_allowed=True, arguments=['-V'])
        with self.assertRaises(LocalModelError):
            LocalExecutableProvider(sys.executable, explicitly_allowed=True, arguments=('x\x00y',))

    def test_native_validation_rejection_has_safe_category(self):
        provider = self._worker('''import sys
sys.stderr.write("LOCAL_MODEL_GENERATION_FAILED;STAGE=text_validation;TYPE=ValueError\\n")
sys.exit(1)
''')
        with self.assertRaisesRegex(LocalModelError, 'native_output_rejected'):
            provider.generate(self.request)

    def test_native_reject_reasons_are_specific_and_keep_author_text_private(self):
        cases = (
            ('NO_HANGUL', 'native_no_hangul'),
            ('NON_KOREAN_SCRIPT', 'native_non_korean_script'),
            ('CONSOLE_OR_PROMPT_ECHO', 'native_prompt_echo'),
            ('INVALID_TYPE', 'native_output_rejected'),
        )
        for reason, expected in cases:
            with self.subTest(reason=reason):
                worker = self._worker(
                    'import sys\n'
                    'sys.stderr.write("private manuscript should never be echoed\\n")\n'
                    'sys.stderr.write("LOCAL_MODEL_GENERATION_FAILED;'
                    'STAGE=text_validation;TYPE=ValueError;REASON='
                    + reason + '\\n")\n'
                    'sys.exit(1)\n')
                with self.assertRaises(LocalModelError) as ctx:
                    worker.generate(self.request)
                self.assertEqual(str(ctx.exception), expected)
                self.assertNotIn('private manuscript', str(ctx.exception))

    def test_real_windows_native_heap_corruption_has_safe_category(self):
        worker = self._worker('''import sys
sys.stderr.write("LLAMA_NATIVE_EXIT=3221226356\\n")
sys.stderr.write("LOCAL_MODEL_GENERATION_FAILED;STAGE=native_inference;TYPE=ValueError\\n")
sys.exit(1)
''')
        with self.assertRaisesRegex(LocalModelError, 'native_process_crash'):
            worker.generate(self.request)

    def test_signed_heap_corruption_is_reported_without_private_stderr(self):
        worker = self._worker('''import sys
sys.stderr.write("private draft must not be printed\\n")
sys.stderr.write("LLAMA_NATIVE_EXIT=-1073740940\\n")
sys.stderr.write("LOCAL_MODEL_GENERATION_FAILED;STAGE=native_inference;TYPE=ValueError\\n")
sys.exit(1)
''')
        with self.assertRaises(LocalModelError) as ctx:
            worker.generate(self.request)
        self.assertEqual(str(ctx.exception), 'native_process_crash')
        self.assertNotIn('private draft', str(ctx.exception))

    def test_windows_access_violation_exit_is_a_native_crash(self):
        worker = self._worker('''import sys
sys.stderr.write("LLAMA_NATIVE_EXIT=-1073741819\\n")
sys.stderr.write("LOCAL_MODEL_GENERATION_FAILED;STAGE=native_inference;TYPE=ValueError\\n")
sys.exit(1)
''')
        with self.assertRaisesRegex(LocalModelError, 'native_process_crash'):
            worker.generate(self.request)

    def test_incomplete_native_draft_is_safe_error_not_fake_success(self):
        provider = self._worker('''import sys
sys.stderr.write("LOCAL_MODEL_GENERATION_FAILED;STAGE=text_validation;TYPE=ValueError;REASON=SHORT_DRAFT\\n")
sys.exit(1)
''')
        with self.assertRaisesRegex(LocalModelError, 'native_short_draft'):
            provider.generate(self.request)

    def test_unsupported_native_scene_target_is_a_safe_error(self):
        provider = self._worker('''import sys
sys.stderr.write("LOCAL_MODEL_GENERATION_FAILED;STAGE=text_validation;TYPE=ValueError;REASON=UNSUPPORTED_TARGET\\n")
sys.exit(1)
''')
        with self.assertRaisesRegex(LocalModelError, 'native_unsupported_target'):
            provider.generate(self.request)

    def test_explicit_scene_length_matches_windows_bridge(self):
        from ai_novel_factory.local_models import effective_scene_target
        self.assertEqual(effective_scene_target('이 장면 6000자 작성', 2500), 6000)
        for target in (50, 500, 999):
            with self.subTest(allocated_scene_chars=target):
                self.assertEqual(effective_scene_target(
                    f'목표 분량 {target}자 내외. 플롯: 5000자 기록을 읽는다',
                    target), target)
        self.assertEqual(effective_scene_target('서가에서 단서를 찾는다', 2500), 2500)
        self.assertIsNone(effective_scene_target('단서를 찾는다', None))
        for bad in (True, '2500', -1, 0):
            with self.subTest(bad=bad), self.assertRaises(LocalModelError):
                effective_scene_target('단서', bad)


    def test_native_exit_has_separate_safe_category(self):
        provider = self._worker('''import sys
sys.stderr.write("LOCAL_MODEL_GENERATION_FAILED;STAGE=native_inference;TYPE=ValueError\\n")
sys.exit(1)
''')
        with self.assertRaisesRegex(LocalModelError, 'native_inference_failure'):
            provider.generate(self.request)

    def test_timeout_bounds(self):
        for seconds in (0, -1, 481, True):
            with self.subTest(seconds=seconds), self.assertRaises(LocalModelError):
                LocalExecutableProvider(sys.executable, explicitly_allowed=True, timeout_seconds=seconds)

    def _worker(self, body: str) -> LocalExecutableProvider:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name)/'worker.py'
        path.write_text(body, encoding='utf-8')
        return LocalExecutableProvider(sys.executable, explicitly_allowed=True,
                                       arguments=(str(path),), timeout_seconds=5)

    def test_process_round_trip_local_json_and_no_api_key_leak(self):
        worker = self._worker('''import json,sys,os
p=json.load(sys.stdin)
assert p["protocol"] == "anf-local-scene-v1"
assert list(p["request"])[0] == "novel_bible"
assert p["request"]["project_id"] == "work-1"
assert "ANF_SECRET_TOKEN" not in os.environ
print(json.dumps({"protocol":p["protocol"],"draft":"로컬 작업자 테스트 초고"},ensure_ascii=False))
''')
        with patch.dict(os.environ, {'ANF_SECRET_TOKEN':'sensitive'}):
            result = draft_scene(self.request, worker)
        self.assertEqual(result.draft, '로컬 작업자 테스트 초고')
        self.assertFalse(result.persisted)
        self.assertEqual(result.provider, 'local-executable-v1')

    def test_process_rejects_wrong_version(self):
        worker = self._worker('print("{\\"protocol\\":\\"wrong\\",\\"draft\\":\\"text\\"}")')
        with self.assertRaises(LocalModelError):
            draft_scene(self.request, worker)

    def test_process_rejects_bad_json(self):
        worker = self._worker('print("not json")')
        with self.assertRaises(LocalModelError):
            draft_scene(self.request, worker)

    def test_process_rejects_empty_draft(self):
        worker = self._worker('import json; print(json.dumps({"protocol":"anf-local-scene-v1","draft":"  "}))')
        with self.assertRaises(LocalModelError):
            draft_scene(self.request, worker)

    def test_process_rejects_nonzero_exit_without_leaking_stderr(self):
        worker = self._worker('import sys;sys.stderr.write("private secret");sys.exit(2)')
        with self.assertRaises(LocalModelError) as context:
            draft_scene(self.request, worker)
        self.assertNotIn('private secret', str(context.exception))

    def test_process_rejects_timeout(self):
        worker = self._worker('import time; time.sleep(1)')
        worker._timeout = 0.1
        with self.assertRaisesRegex(LocalModelError, 'native_timeout'):
            draft_scene(self.request, worker)

    def test_process_rejects_huge_response(self):
        worker = self._worker('import json;print(json.dumps({"protocol":"anf-local-scene-v1","draft":"x"*101000}))')
        with self.assertRaises(LocalModelError):
            draft_scene(self.request, worker)

    def test_invalid_response_from_broken_provider(self):
        fake = MockSceneProvider()
        fake.generate = lambda request: None
        with self.assertRaises(LocalModelError):
            draft_scene(self.request, fake)

    def test_unexpected_provider_error_is_sanitized(self):
        fake = MockSceneProvider()
        def boom(request): raise RuntimeError('a private secret')
        fake.generate = boom
        with self.assertRaises(LocalModelError) as context:
            draft_scene(self.request, fake)
        self.assertNotIn('private secret', str(context.exception))


if __name__ == '__main__':
    unittest.main()
