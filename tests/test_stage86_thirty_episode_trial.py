"""Stage 86 / ANF-REQ-059: 30 sequential offline mock drafts with error report."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_novel_factory.local_models import MockSceneProvider
from ai_novel_factory.thirty_episode_trial import (
    ThirtyEpisodeTrialError, run_30_episode_trial)

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / 'scripts' / 'stage86_run_30_episode_trial.py'


class ThirtyEpisodeTrialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_30_episode_trial()

    def test_exactly_30_contiguous_episodes(self):
        r = self.report
        self.assertEqual((r['expected_episodes'], r['attempted_episodes']), (30, 30))
        self.assertTrue(r['episode_numbers_contiguous'])
        self.assertEqual([x['episode'] for x in r['episodes']], list(range(1, 31)))

    def test_all_mock_drafts_created(self):
        r = self.report
        self.assertTrue(r['passed'])
        self.assertEqual((r['successful_drafts'], r['saved_draft_count'],
                          r['version_count'], r['queued_task_count']), (30, 30, 30, 30))
        self.assertEqual(r['scenes_in_successful_drafts'], 60)
        self.assertEqual(r['error_count'], 0)

    def test_all_episode_hashes_are_valid_distinct(self):
        hashes = [x['draft_sha256'] for x in self.report['episodes']]
        self.assertEqual(len(set(hashes)), 30)
        self.assertTrue(all(isinstance(h, str) and len(h) == 64
                            and all(c in '0123456789abcdef' for c in h) for h in hashes))

    def test_statuses_remain_unapproved(self):
        r = self.report
        self.assertEqual(r['final_version_count'], 0)
        self.assertFalse(r['publication_approved'])
        self.assertFalse(r['human_approval_authenticated'])
        self.assertFalse(r['memory_delta_applied'])
        self.assertFalse(r['reference_text_used'])
        for entry in r['episodes']:
            self.assertEqual(entry['status'], 'DRAFT_REQUIRES_USER_APPROVAL')
            self.assertEqual(entry['task_status'], 'COMPLETED')
            self.assertFalse(entry['approval_authenticated'])
            self.assertFalse(entry['published'])
            self.assertEqual(entry['scene_count'], 2)

    def test_no_manuscript_or_secret_in_report(self):
        data = json.dumps(self.report, ensure_ascii=False)
        self.assertNotIn('[모의 초고', data)
        self.assertNotIn('테스트 장소', data)
        self.assertNotIn('canon-1', data)
        self.assertNotIn('fixture-hero', data)
        self.assertNotIn('API_KEY=', data)

    def test_injected_block_is_reported_and_draft_not_saved(self):
        r = run_30_episode_trial(blocked_episode=17)
        self.assertFalse(r['passed'])
        self.assertEqual(r['attempted_episodes'], 30)
        self.assertEqual((r['successful_drafts'], r['saved_draft_count'],
                          r['version_count'], r['error_count'],
                          r['preliminary_blocked_count']), (29, 29, 29, 1, 1))
        blocked = r['episodes'][16]
        self.assertEqual(blocked['status'], 'BLOCKED_PRELIMINARY')
        self.assertEqual(blocked['error_code'], 'PRELIMINARY_REVIEW_REQUIRED')
        self.assertFalse(blocked['saved'])
        self.assertIsNone(blocked['draft_sha256'])
        self.assertEqual(r['final_version_count'], 0)

    def test_failure_of_mock_provider_is_reported_safely(self):
        original = MockSceneProvider.generate
        def fail_at_11(provider, request):
            if request.episode_number == 11:
                raise RuntimeError('PRIVATE DRAFT SECRET')
            return original(provider, request)
        with patch.object(MockSceneProvider, 'generate', fail_at_11):
            r = run_30_episode_trial()
        self.assertFalse(r['passed'])
        self.assertEqual(r['error_count'], 1)
        self.assertEqual(r['successful_drafts'], 29)
        self.assertEqual(r['attempted_episodes'], 30)
        self.assertEqual(r['episodes'][10]['status'], 'FAILED')
        self.assertNotIn('PRIVATE', json.dumps(r))
        self.assertEqual(r['final_version_count'], 0)

    def test_reject_invalid_injection(self):
        for value in (-1, 0, 31, True, 3.5, '1', object()):
            with self.subTest(value=value), self.assertRaises(ThirtyEpisodeTrialError):
                run_30_episode_trial(blocked_episode=value)

    def test_cli_writes_json_and_exit_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'result.json'
            p = subprocess.run([sys.executable, str(SCRIPT), '--output', str(output)],
                               cwd=ROOT, capture_output=True, text=True, timeout=45)
            self.assertEqual(p.returncode, 0, p.stderr)
            r = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual((r['attempted_episodes'], r['error_count']), (30, 0))

    def test_cli_rejection_nonzero_and_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'result.json'
            p = subprocess.run([sys.executable, str(SCRIPT), '--output', str(output),
                                '--blocked-episode', '7'], cwd=ROOT,
                               capture_output=True, text=True, timeout=45)
            self.assertEqual(p.returncode, 1)
            r = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual((r['error_count'], r['successful_drafts']), (1, 29))

    def test_cli_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'target.json'
            target.write_text('do not change', encoding='utf-8')
            alias = Path(directory) / 'alias.json'
            alias.symlink_to(target)
            p = subprocess.run([sys.executable, str(SCRIPT), '--output', str(alias)],
                               cwd=ROOT, capture_output=True, text=True, timeout=45)
            self.assertNotEqual(p.returncode, 0)
            self.assertEqual(target.read_text(encoding='utf-8'), 'do not change')


if __name__ == '__main__':
    unittest.main()
