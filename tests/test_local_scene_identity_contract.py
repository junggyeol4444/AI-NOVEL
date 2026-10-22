"""Offline scene identity regression. No model inference, DB, or approval."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from ai_novel_factory.local_models import (
    LocalExecutableProvider, LocalModelError, SceneDraftRequest, draft_scene,
)

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'anf_scene_identity_bridge', ROOT / 'packaging/windows/local_model_bridge.py')
BRIDGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BRIDGE)


class OfflineSceneIdentityContractTests(unittest.TestCase):
    def setUp(self):
        self.request = SceneDraftRequest(
            'novel-one', 3, 2, '작품의 설정', '이번 사건',
            '갈등', '도서관', ('작가가 저장한 인물',))
        self.provider = LocalExecutableProvider(
            sys.executable, explicitly_allowed=True)

    def _generate(self, response):
        proc = subprocess.CompletedProcess(
            args=[sys.executable], returncode=0,
            stdout=json.dumps(response, ensure_ascii=False), stderr='')
        with patch('ai_novel_factory.local_models.subprocess.run',
                   return_value=proc):
            return draft_scene(self.request, self.provider)

    def test_bridge_identity_and_unapproved_draft(self):
        expected = {'project_id': 'novel-one',
                    'episode_number': 3, 'scene_number': 2}
        self.assertEqual(BRIDGE.request_scene_identity(expected), expected)
        result = self._generate({
            'protocol': 'anf-local-scene-v1', 'draft': '그는 문을 열었다.',
            **expected})
        self.assertEqual(result.draft, '그는 문을 열었다.')
        self.assertFalse(result.persisted)
        self.assertEqual(result.status, 'DRAFT_REQUIRES_USER_APPROVAL')

    def test_wrong_chapter_scene_or_project_is_rejected(self):
        for changed in ({'episode_number': 4}, {'scene_number': 3},
                        {'project_id': 'someone-else'},
                        {'scene_number': True}):
            response = {
                'protocol': 'anf-local-scene-v1',
                'draft': '유출 금지 비밀 원고',
                'project_id': 'novel-one', 'episode_number': 3,
                'scene_number': 2}
            response.update(changed)
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(
                        LocalModelError, 'scene identity mismatch') as caught:
                    self._generate(response)
                self.assertNotIn('비밀 원고', str(caught.exception))

    def test_partial_identity_rejected_legacy_v1_remains_compatible(self):
        response = {'protocol': 'anf-local-scene-v1', 'draft': '기존 작업자 초고'}
        self.assertEqual(self._generate(response).draft, '기존 작업자 초고')
        response['episode_number'] = 3
        with self.assertRaisesRegex(LocalModelError, 'scene identity mismatch'):
            self._generate(response)

    def test_bridge_rejects_invalid_identity_before_inference(self):
        good = {'project_id': 'novel-one',
                'episode_number': 3, 'scene_number': 2}
        for invalid in ({'scene_number': True}, {'episode_number': 0},
                        {'project_id': ''}, {'project_id': chr(0)},
                        {'episode_number': '3'}, {'scene_number': None}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                BRIDGE.request_scene_identity({**good, **invalid})


if __name__ == '__main__':
    unittest.main()
