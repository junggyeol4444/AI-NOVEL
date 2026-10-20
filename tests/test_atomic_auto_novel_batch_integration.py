"""Cross-feature database + GUI batch contracts; not real AI acceptance.

Uses only temporary SQLite, no model, external account, user files or publish.
Actual Windows native Qwen and GGUF tests remain separate release gates.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from ai_novel_factory.database.episodes import EpisodeError, EpisodeStore

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'src/ai_novel_factory/database/episodes.py'
BATCH = ROOT / 'src/ai_novel_factory/auto_novel_run.py'
GUI = ROOT / 'src/ai_novel_factory/desktop/auto_batch_panel.py'
WORKFLOW = ROOT / 'src/ai_novel_factory/desktop/authoring_workflow.py'


class AtomicBatchEpisodeRegression(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'only-temporary.sqlite'
        self.db = EpisodeStore(self.path)
        self.addCleanup(self.db.close)
        self.pid = self.db.create_project('임시 원고 안전 검사').project_id

    @staticmethod
    def kwargs(number=1):
        # Data is a synthetic transport fixture and not presented as AI prose.
        return dict(plot='플롯 전송 검사',
                    draft='검사용 임시 텍스트\n저장과 복구를 확인한다.',
                    summary='미승인 요약',
                    scenes=((1, '장면 슬롯 A'), (2, '장면 슬롯 B')),
                    checks=(('length', 'WARN', '분량 미달'),
                            ('korean_format', 'WARN', '형식 검사 미달'),
                            ('continuity', 'NOT_RUN', '전수 검사 미실시')))

    def test_insert_is_atomic_and_survives_independent_sqlite_reopen(self):
        project_before = self.db.get_project(self.pid).revision
        saved = self.db.create_unapproved_batch_episode(
            self.pid, 1, **self.kwargs())
        self.assertEqual(saved.revision, 4)
        self.assertEqual(self.db.get_project(self.pid).revision, project_before + 1)
        with EpisodeStore(self.path) as independent:
            loaded = independent.snapshot(self.pid, 1)
            self.assertEqual(loaded.episode.draft, self.kwargs()['draft'])
            self.assertEqual(loaded.episode.summary, '미승인 요약')
            self.assertEqual(loaded.episode.final_text, '')
            self.assertEqual([s.position for s in loaded.scenes], [1, 2])
            self.assertEqual(len(loaded.checks), 3)
            self.assertTrue(all(c.content_revision == loaded.episode.revision
                                for c in loaded.checks))

    def test_duplicate_existing_episode_cannot_overwrite_user_content(self):
        first = self.db.create_unapproved_batch_episode(
            self.pid, 1, **self.kwargs())
        before = self.db.get_project(self.pid).revision
        with self.assertRaises(EpisodeError):
            self.db.create_unapproved_batch_episode(
                self.pid, 1, **{**self.kwargs(), 'draft': '다른 데이터'})
        self.assertEqual(self.db.get_episode(self.pid, 1).draft, first.draft)
        self.assertEqual(self.db.get_project(self.pid).revision, before)
        self.assertEqual(len(self.db.list_checks(self.pid, 1)), 3)

    def test_failure_during_qc_insert_rolls_back_episode_and_all_scenes(self):
        before = self.db.get_project(self.pid).revision
        self.db._db.execute("""CREATE TRIGGER reject_test_check
            BEFORE INSERT ON bible_episode_checks
            BEGIN SELECT RAISE(ABORT, 'ephemeral rollback probe'); END""")
        self.db._db.commit()
        with self.assertRaises(EpisodeError):
            self.db.create_unapproved_batch_episode(
                self.pid, 2, **self.kwargs())
        self.assertEqual(self.db.list_episodes(self.pid), ())
        self.assertEqual(self.db.get_project(self.pid).revision, before)
        with EpisodeStore(self.path) as independent:
            self.assertEqual(independent.list_episodes(self.pid), ())

    def test_invalid_scenes_and_unapproved_status_are_rejected_before_writes(self):
        for kwargs in ({'scenes': ((1, 'A'), (1, 'B'))},
                       {'checks': (('literary', 'CERTIFIED', '허위 결과'),)},
                       {'draft': ''}):
            with self.subTest(kwargs=kwargs), self.assertRaises(EpisodeError):
                self.db.create_unapproved_batch_episode(
                    self.pid, 3, **{**self.kwargs(), **kwargs})
        self.assertEqual(self.db.list_episodes(self.pid), ())

    def test_250_episode_storage_contract_does_not_certify_ai(self):
        # Real SQLite transactions only; these are NOT model-written novels.
        for number in range(1, 251):
            self.db.create_unapproved_batch_episode(
                self.pid, number, **self.kwargs())
        with EpisodeStore(self.path) as independent:
            self.assertEqual(len(independent.list_episodes(self.pid)), 250)
            self.assertTrue(all(not e.final_text
                                for e in independent.list_episodes(self.pid)))
            self.assertEqual(len(independent.list_checks(self.pid, 250)), 3)


class BatchWiringSourceContract(unittest.TestCase):
    def test_run_uses_atomic_insert_and_explicit_real_korean_screening(self):
        batch = BATCH.read_text(encoding='utf-8')
        self.assertIn('safe.create_unapproved_batch_episode(', batch)
        self.assertIn("('korean_format', 'PASS' if screen.format_gate_pass", batch)
        self.assertIn("('reference_similarity', 'continuity',", batch)
        self.assertNotIn('safe.create_episode(project_id, n, plot=outline)', batch)

    def test_gui_uses_explicit_qwen_timeout_and_cannot_switch_project(self):
        gui = GUI.read_text(encoding='utf-8')
        workflow = WORKFLOW.read_text(encoding='utf-8')
        self.assertIn("Path(executable).name.casefold() == 'anf_local_model.exe'", gui)
        self.assertIn("timeout_seconds=(", gui)
        self.assertIn('self.auto_panel.request_stop()', workflow)
        self.assertIn("if self.auto_panel.is_running():", workflow)
        self.assertIn('str(session.project_id) == self.worker.project_id', gui)


if __name__ == '__main__':
    unittest.main()
