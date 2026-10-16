"""Non-acceptance regression for Windows compiled GUI SQLite evidence integrity."""
import hashlib
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from scripts.ci_verify_gui_draft_sqlite import verify_sqlite_saved_draft, export_synthetic_review_sample


class SavedDraftEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.work = self.root / 'anf-korean-gui-test'
        self.work.mkdir()
        self.db = self.work / 'only-synthetic.sqlite'
        self.data = '합성 검수 원고\n가상의 장면만 포함한다.'
        with sqlite3.connect(self.db) as con:
            con.execute('CREATE TABLE bible_episodes (draft TEXT)')
            con.execute('INSERT INTO bible_episodes VALUES (?)', (self.data,))
        self.digest = hashlib.sha256(self.data.encode('utf-8')).hexdigest()

    def test_matching_saved_draft_is_verified_read_only(self):
        self.assertTrue(verify_sqlite_saved_draft(self.db, self.digest, self.root))

    def test_changed_or_empty_hash_is_not_success(self):
        self.assertFalse(verify_sqlite_saved_draft(self.db, '0'*64, self.root))
        self.assertFalse(verify_sqlite_saved_draft(self.db, '', self.root))

    def test_outside_isolated_runner_path_is_rejected(self):
        self.assertFalse(verify_sqlite_saved_draft(self.db, self.digest, self.work))

    def test_multiple_nonempty_manuscripts_do_not_report_success(self):
        with sqlite3.connect(self.db) as con:
            con.execute('INSERT INTO bible_episodes VALUES (?)', (self.data,))
        self.assertFalse(verify_sqlite_saved_draft(self.db, self.digest, self.root))

    def test_real_synthetic_prose_can_be_read_after_hash_verified(self):
        self.assertTrue(export_synthetic_review_sample(
            self.db, self.digest, self.root, self.root))
        text = (self.root / 'build/ci/korean-real-gui/qa_original_scene.txt').read_text(
            encoding='utf-8')
        self.assertEqual(text, self.data)

    def test_wrong_hash_or_db_never_exports_prose(self):
        self.assertFalse(export_synthetic_review_sample(
            self.db, 'f'*64, self.root, self.root))
        self.assertFalse(export_synthetic_review_sample(
            self.db, self.digest, self.work, self.root))
        self.assertFalse(
            (self.root / 'build/ci/korean-real-gui/qa_original_scene.txt').exists())

    def test_export_normalizes_windows_crlf_in_synthetic_draft(self):
        with sqlite3.connect(self.db) as con:
            con.execute('UPDATE bible_episodes SET draft=?', ('첫째\r\n둘째',))
        digest = hashlib.sha256('첫째\n둘째'.encode('utf-8')).hexdigest()
        self.assertTrue(export_synthetic_review_sample(
            self.db, digest, self.root, self.root))
        content = (self.root / 'build/ci/korean-real-gui/qa_original_scene.txt').read_text(
            encoding='utf-8')
        self.assertEqual(content, '첫째\n둘째')

    def test_newlines_normalized_for_windows_qt(self):
        with sqlite3.connect(self.db) as con:
            con.execute('UPDATE bible_episodes SET draft=?', ('첫째\r\n둘째',))
        digest = hashlib.sha256('첫째\n둘째'.encode('utf-8')).hexdigest()
        self.assertTrue(verify_sqlite_saved_draft(self.db, digest, self.root))


if __name__ == '__main__':
    unittest.main()
