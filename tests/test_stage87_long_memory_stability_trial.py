"""Stage 87: deterministic 120-episode mock long-memory regression tests."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_novel_factory.local_models import MockSceneProvider
from ai_novel_factory.long_memory_stability_trial import (
    LongMemoryTrialError, _conflicting_explicit_assertions,
    run_120_episode_memory_trial)

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / 'scripts' / 'stage87_run_long_memory_trial.py'


class LongMemoryStabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_120_episode_memory_trial()

    def test_120_episodes_are_contiguous(self):
        r = self.report
        self.assertTrue(r['passed'])
        self.assertEqual(r['expected_episodes'], 120)
        self.assertEqual(r['attempted_episodes'], 120)
        self.assertTrue(r['episode_numbers_contiguous'])
        self.assertEqual([x['episode'] for x in r['episodes']], list(range(1, 121)))

    def test_drafts_summaries_and_versions_all_persist(self):
        r = self.report
        self.assertEqual((r['successful_drafts'], r['stored_draft_count'],
                          r['stored_summary_count'], r['version_count']), (120, 120, 120, 120))
        self.assertEqual((r['reopened_episode_count'], r['reopened_version_count']), (120, 120))
        self.assertEqual(len({x['draft_sha256'] for x in r['episodes']}), 120)
        self.assertEqual(len({x['summary_sha256'] for x in r['episodes']}), 120)

    def test_long_range_memory_anchor_and_canon_stability(self):
        r = self.report
        self.assertEqual(r['memory_retrieval_checks'], 119)
        self.assertEqual(r['memory_retrieval_failures'], 0)
        self.assertTrue(r['anchor_retrieved_after_reopen'])
        self.assertEqual(r['canon_consistency_checks'], 120)
        self.assertEqual(r['canon_mismatch_count'], 0)
        self.assertEqual(r['explicit_canon_conflict_count'], 0)
        self.assertTrue(r['bible_rule_unchanged'])

    def test_sqlite_integrity_and_no_final_approval(self):
        r = self.report
        self.assertTrue(r['sqlite_integrity_ok'])
        self.assertEqual(r['sqlite_foreign_key_errors'], 0)
        self.assertEqual(r['final_version_count'], 0)
        self.assertFalse(r['human_approval_authenticated'])
        self.assertFalse(r['publication_approved'])
        self.assertFalse(r['memory_delta_applied'])
        self.assertFalse(r['reference_text_used'])
        self.assertEqual(r['error_count'], 0)
        self.assertTrue(all(x['status'] == 'DRAFT_REQUIRES_USER_APPROVAL'
                            and x['saved'] and not x['approved'] and not x['published']
                            for x in r['episodes']))

    def test_explicit_conflict_detection_is_key_scoped(self):
        self.assertEqual(_conflicting_explicit_assertions(
            {'a': 'one', 'b': 'two'}, {'a': 'bad', 'b': 'two', 'new': 'other'}), ('a',))
        self.assertEqual(_conflicting_explicit_assertions({'a': 'one'}, {'a': 'one'}), ())
        self.assertEqual(_conflicting_explicit_assertions({'a': 'one'}, {'unknown': 'x'}), ())

    def test_injected_canon_conflict_is_blocked_not_applied(self):
        r = run_120_episode_memory_trial(conflict_episode=73)
        self.assertFalse(r['passed'])
        self.assertEqual(r['attempted_episodes'], 120)
        self.assertEqual(r['explicit_canon_conflict_count'], 1)
        self.assertEqual(r['conflict_blocked_episode_count'], 1)
        self.assertEqual(r['successful_drafts'], 119)
        self.assertEqual(r['error_count'], 1)
        self.assertEqual(r['episodes'][72]['status'], 'BLOCKED_EXPLICIT_CANON_CONFLICT')
        self.assertFalse(r['episodes'][72]['saved'])
        self.assertTrue(r['bible_rule_unchanged'])
        self.assertEqual(r['canon_mismatch_count'], 0)
        self.assertEqual(r['final_version_count'], 0)

    def test_mock_provider_error_is_sanitized(self):
        original = MockSceneProvider.generate
        def injected(provider, request):
            if request.episode_number == 40:
                raise RuntimeError('PRIVATE_MANUSCRIPT_SECRET')
            return original(provider, request)
        with patch.object(MockSceneProvider, 'generate', injected):
            r = run_120_episode_memory_trial()
        self.assertFalse(r['passed'])
        self.assertEqual(r['successful_drafts'], 119)
        self.assertEqual(r['error_count'], 1)
        self.assertEqual(r['episodes'][39]['error_code'], 'MOCK_WORKFLOW_FAILED')
        self.assertNotIn('PRIVATE_MANUSCRIPT_SECRET', json.dumps(r))
        self.assertEqual(r['final_version_count'], 0)

    def test_report_redacts_all_fixture_text(self):
        raw = json.dumps(self.report, ensure_ascii=False)
        for sensitive in ('ground_only', 'flight_enabled', 'TEST_HERO', 'TEST_REGION',
                          'ANF_TEST_ANCHOR_001', 'ANF_TEST_SUMMARY_E',
                          'fixture-hero', '모의 시험 장소', 'API_KEY='):
            self.assertNotIn(sensitive, raw)

    def test_invalid_injection_fails_closed(self):
        for value in (0, -1, 121, True, 3.5, '2', object()):
            with self.subTest(value=value), self.assertRaises(LongMemoryTrialError):
                run_120_episode_memory_trial(conflict_episode=value)

    def test_cli_writes_safe_report(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'report.json'
            p = subprocess.run([sys.executable, str(SCRIPT), '--output', str(path)],
                               cwd=ROOT, capture_output=True, text=True, timeout=90)
            self.assertEqual(p.returncode, 0, p.stderr)
            r = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(r['attempted_episodes'], 120)
            self.assertEqual(r['explicit_canon_conflict_count'], 0)
            self.assertTrue(r['passed'])

    def test_cli_conflict_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'report.json'
            p = subprocess.run([sys.executable, str(SCRIPT), '--output', str(path),
                                '--conflict-episode', '73'], cwd=ROOT,
                               capture_output=True, text=True, timeout=90)
            self.assertEqual(p.returncode, 1, p.stderr)
            r = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual((r['explicit_canon_conflict_count'], r['successful_drafts']), (1, 119))

    def test_cli_rejects_output_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / 'target.json'
            target.write_text('original', encoding='utf-8')
            link = Path(d) / 'link.json'
            link.symlink_to(target)
            p = subprocess.run([sys.executable, str(SCRIPT), '--output', str(link)],
                               cwd=ROOT, capture_output=True, text=True, timeout=15)
            self.assertNotEqual(p.returncode, 0)
            self.assertEqual(target.read_text(encoding='utf-8'), 'original')


if __name__ == '__main__':
    unittest.main()
