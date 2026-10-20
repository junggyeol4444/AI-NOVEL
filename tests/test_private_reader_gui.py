"""Actual Qt private reader over temporary SQLite; no mock AI or publishing.

Qt is optional for non-GUI Python installations. Windows Qt test runners
exercise real controls; only an actual Windows EXE run can certify the EXE.
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from ai_novel_factory.database.episodes import EpisodeStore

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6.QtWidgets import QApplication
    from ai_novel_factory.desktop.private_reader import PrivateNovelReader
except ImportError:
    QApplication = None
    PrivateNovelReader = None


@unittest.skipUnless(QApplication is not None, 'PySide6 GUI is not installed')
class PrivateReaderSqliteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'fiction-only.sqlite'
        self.store = EpisodeStore(self.path)
        self.addCleanup(self.store.close)
        self.pid = self.store.create_project('가상 독서 프로젝트').project_id
        self.store.create_episode(self.pid, 1, plot='첫 사건')
        self.store.update_episode(self.pid, 1, expected_revision=1,
                                  draft='가상의 서고에서 사서가 오래된 문서를 찾는다.')
        self.store.create_episode(self.pid, 2, plot='두 번째 사건')
        self.store.update_episode(self.pid, 2, expected_revision=1,
                                  draft='임시 두 번째 원고',
                                  final_text='검토 후 보관한 두 번째 원고')
        self.session = SimpleNamespace(
            store=self.store, path=self.path, project_id=self.pid,
            episode_number=1, pending_draft='저장하지 않은 새 원고')
        self.reader = PrivateNovelReader(lambda: self.session)
        self.addCleanup(self.reader.close)

    def test_only_persisted_text_is_visible_and_not_mutable(self):
        before = self.store.get_episode(self.pid, 1)
        self.reader.refresh()
        self.assertTrue(self.reader.body.isReadOnly())
        self.assertEqual(self.reader.body.toPlainText(), before.draft)
        self.assertNotIn('저장하지 않은 새 원고', self.reader.body.toPlainText())
        self.reader.find_input.setText('오래된')
        self.reader._find()
        self.reader.font_size.setValue(20)
        self.assertEqual(self.reader.body.font().pointSize(), 20)
        after = self.store.get_episode(self.pid, 1)
        self.assertEqual((before.draft, before.revision),
                         (after.draft, after.revision))

    def test_chapter_next_previous_and_final_draft_selection(self):
        self.reader.refresh()
        self.assertFalse(self.reader.previous.isEnabled())
        self.assertTrue(self.reader.next.isEnabled())
        self.reader.next.click()
        self.assertIn('검토 후 보관한', self.reader.body.toPlainText())
        self.assertIn('사용자 검수 최종본', self.reader.status.text())
        self.reader.version.setCurrentIndex(
            self.reader.version.findData('draft'))
        self.assertEqual(self.reader.body.toPlainText(), '임시 두 번째 원고')
        self.reader.previous.click()
        self.assertEqual(self.reader.episodes.currentData(), 1)
        self.assertIn('가상의 서고', self.reader.body.toPlainText())

    def test_new_project_selection_never_shows_previous_novel(self):
        self.reader.refresh()
        other = self.store.create_project('완전히 다른 가상 작품').project_id
        self.session.project_id = other
        self.session.episode_number = None
        self.reader.refresh()
        self.assertEqual(self.reader.body.toPlainText(), '')
        self.assertEqual(self.reader.episodes.count(), 0)
        self.assertIn('저장 원고가 없습니다', self.reader.status.text())

    def test_independent_sqlite_reopen_still_displays_original_text(self):
        expected = self.reader.body.toPlainText()
        self.reader.refresh()
        expected = self.reader.body.toPlainText()
        self.store.close()
        reopened = EpisodeStore(self.path)
        self.addCleanup(reopened.close)
        self.session.store = reopened
        self.reader.refresh()
        self.assertEqual(self.reader.body.toPlainText(), expected)
        self.assertTrue(self.reader.body.isReadOnly())


if __name__ == '__main__':
    unittest.main()
