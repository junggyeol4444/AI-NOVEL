"""Stage 79: optional SQLite receipt with no draft text and strict provenance."""
from dataclasses import replace
from hashlib import sha256
import tempfile
from pathlib import Path
import unittest

from ai_novel_factory.reader_simulation import (
    ReaderSimulationError, SceneReaderAnnotation, simulate_reader_profiles,
)
from ai_novel_factory.reader_simulation_records import ReaderSimulationStore

PID = 'b'*32
TEXT = '바람은 부두를 지나갔다.'
FLAGS = dict(goal_visible=True, tension_present=True, development=True,
             character_choice=True, consequence=True, closing_hook=True)
SCENE = SceneReaderAnnotation(1, 0, len(TEXT), sha256(TEXT.encode()).hexdigest(), **FLAGS)


class ReaderStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = ReaderSimulationStore(':memory:')
        self.report = simulate_reader_profiles(PID, 2, TEXT, scenes=(SCENE,))

    def tearDown(self):
        self.store.close()

    def test_explicit_save_and_current_read(self):
        with self.assertRaises(ReaderSimulationError):
            self.store.read_current(PID, 2, TEXT, scenes=(SCENE,))
        receipt = self.store.record(self.report, draft=TEXT, scenes=(SCENE,))
        self.assertEqual(receipt, self.store.read_current(PID, 2, TEXT, scenes=(SCENE,)))
        self.assertEqual(receipt.status, 'ANNOTATED_PROXY_ONLY')
        self.assertFalse(receipt.manuscript_approved)
        self.assertFalse(receipt.publication_approved)

    def test_duplicate_save_idempotent(self):
        self.store.record(self.report, draft=TEXT, scenes=(SCENE,))
        self.store.record(self.report, draft=TEXT, scenes=(SCENE,))
        self.assertEqual(self.store._db.execute('SELECT COUNT(*) FROM reader_proxy').fetchone()[0], 1)

    def test_changed_annotation_invalidates_read(self):
        self.store.record(self.report, draft=TEXT, scenes=(SCENE,))
        altered = replace(SCENE, goal_visible=False)
        with self.assertRaises(ReaderSimulationError):
            self.store.read_current(PID, 2, TEXT, scenes=(altered,))

    def test_changed_draft_invalidates_read(self):
        self.store.record(self.report, draft=TEXT, scenes=(SCENE,))
        changed = TEXT + '다른 이야기'
        other = replace(SCENE, end=len(changed), evidence_sha256=sha256(changed.encode()).hexdigest())
        with self.assertRaises(ReaderSimulationError):
            self.store.read_current(PID, 2, changed, scenes=(other,))

    def test_other_project_and_episode_isolation(self):
        self.store.record(self.report, draft=TEXT, scenes=(SCENE,))
        for pid, ep in [('c'*32, 2), (PID, 3)]:
            with self.assertRaises(ReaderSimulationError):
                self.store.read_current(pid, ep, TEXT, scenes=(SCENE,))

    def test_forged_score_rejected(self):
        altered = replace(self.report, metrics=(replace(self.report.metrics[0], score=0), *self.report.metrics[1:]))
        with self.assertRaises(ReaderSimulationError):
            self.store.record(altered, draft=TEXT, scenes=(SCENE,))

    def test_forged_approval_rejected(self):
        with self.assertRaises(ReaderSimulationError):
            self.store.record(replace(self.report, publication_approved=True), draft=TEXT, scenes=(SCENE,))

    def test_forged_status_rejected(self):
        with self.assertRaises(ReaderSimulationError):
            self.store.record(replace(self.report, status='QUALITY_APPROVED'), draft=TEXT, scenes=(SCENE,))

    def test_forged_hash_rejected(self):
        with self.assertRaises(ReaderSimulationError):
            self.store.record(replace(self.report, draft_sha256='0'*64), draft=TEXT, scenes=(SCENE,))

    def test_incomplete_annotation_saved_as_incomplete(self):
        missing = replace(SCENE, closing_hook=None)
        report = simulate_reader_profiles(PID, 2, TEXT, scenes=(missing,))
        receipt = self.store.record(report, draft=TEXT, scenes=(missing,))
        self.assertEqual(receipt.status, 'INCOMPLETE_ANNOTATIONS')
        self.assertIsNone(report.metrics[-1].score)
        self.assertIsNone(report.profiles[0].score)

    def test_no_draft_text_in_database(self):
        self.store.record(self.report, draft=TEXT, scenes=(SCENE,))
        dumped = '\n'.join(self.store._db.iterdump())
        self.assertNotIn(TEXT, dumped)
        self.assertIn('momentum', dumped)

    def test_database_tamper_detected(self):
        self.store.record(self.report, draft=TEXT, scenes=(SCENE,))
        self.store._db.execute("UPDATE reader_proxy SET indicators_json='{}'")
        with self.assertRaises(ReaderSimulationError):
            self.store.read_current(PID, 2, TEXT, scenes=(SCENE,))

    def test_bad_path(self):
        with self.assertRaises(ReaderSimulationError):
            ReaderSimulationStore('/path/that/does/not/exist/reader.sqlite')

    def test_context_manager_persistent_local(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'reader.sqlite'
            with ReaderSimulationStore(path) as s:
                s.record(self.report, draft=TEXT, scenes=(SCENE,))
            with ReaderSimulationStore(path) as s:
                self.assertEqual(s.read_current(PID, 2, TEXT, scenes=(SCENE,)).status,
                                 'ANNOTATED_PROXY_ONLY')

    def test_report_wrong_type(self):
        with self.assertRaises(ReaderSimulationError):
            self.store.record(None, draft=TEXT, scenes=(SCENE,))


if __name__ == '__main__':
    unittest.main()
