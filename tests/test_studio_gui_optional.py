"""Fast GUI regression: real Qt widget clicks, never a human UX acceptance.

Only synthetic content and explicit local operations. Headless CI is NOT a
substitute for a physical Windows 10/11 user's native EXE interaction.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'PySide6 not installed')
class UserFirstStudioTests(unittest.TestCase):
    def test_create_write_version_reopen_with_visible_buttons(self):
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        from PySide6.QtCore import Qt, QStandardPaths
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QPushButton
        from ai_novel_factory.database.episodes import EpisodeStore
        from ai_novel_factory.manuscript_versions import ManuscriptVersionStore
        from ai_novel_factory.desktop.app import MainWindow

        QStandardPaths.setTestModeEnabled(True)
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        window.show()
        app.processEvents()
        try:
            studio = window.studio
            self.assertEqual(studio.pages.currentIndex(), 0)
            self.assertEqual(window.novel_tabs.currentIndex(), 0)
            QTest.mouseClick(studio.findChild(QPushButton, 'studioNewButton'),
                             Qt.MouseButton.LeftButton)
            title = '합성 테스트 작품 ' + uuid4().hex[:8]
            studio.new_title.setText(title)
            studio.new_genre.setText('가상 판타지')
            studio.new_subject.setPlainText('새로 지어낸 도시와 여행자')
            studio.new_premise.setPlainText('완전 창작 설정만 사용')
            QTest.mouseClick(studio.findChild(QPushButton, 'studioCreateProjectButton'),
                             Qt.MouseButton.LeftButton)
            app.processEvents()
            session = window.authoring.session
            self.assertEqual(studio.pages.currentIndex(), 2)
            self.assertIsNotNone(session.project_id)
            path, pid = Path(session.path), session.project_id
            self.assertTrue(path.is_file())

            QTest.mouseClick(studio.findChild(QPushButton, 'studioFirstEpisodeButton'),
                             Qt.MouseButton.LeftButton)
            app.processEvents()
            self.assertEqual(session.episode_number, 1)
            self.assertEqual(studio.episode_list.count(), 1)
            original = '완전히 창작한 1화 본문.'
            studio.editor.setPlainText(original)
            QTest.mouseClick(studio.findChild(QPushButton, 'studioSaveManuscript'),
                             Qt.MouseButton.LeftButton)
            app.processEvents()
            with EpisodeStore(path) as store:
                self.assertEqual(store.get_episode(pid, 1).draft, original)
            with ManuscriptVersionStore(path) as versions:
                history = versions.list_versions(pid, 1)
                self.assertEqual(len(history), 1)
                self.assertEqual(history[0].draft, original)

            revised = original + ' 다시 고친 문장.'
            studio.editor.setPlainText(revised)
            QTest.mouseClick(studio.findChild(QPushButton, 'studioSaveManuscript'),
                             Qt.MouseButton.LeftButton)
            app.processEvents()
            with ManuscriptVersionStore(path) as versions:
                history = versions.list_versions(pid, 1)
                self.assertEqual(len(history), 2)
                self.assertEqual(history[0].draft, original)
                self.assertEqual(history[1].draft, revised)
            with EpisodeStore(path) as store:
                self.assertEqual(store.get_episode(pid, 1).draft, revised)

            self.assertTrue(window.close())
            window = None
            app.processEvents()
            restarted = MainWindow()
            window = restarted
            window.show()
            app.processEvents()
            recent = restarted.studio.recents
            matches = [i for i in range(recent.count()) if recent.item(i).text() == title]
            self.assertTrue(matches, 'Restarted app must show human-readable recent title')
            recent.setCurrentRow(matches[0])
            QTest.mouseClick(restarted.studio.findChild(
                QPushButton, 'studioOpenRecentButton'), Qt.MouseButton.LeftButton)
            app.processEvents()
            self.assertEqual(restarted.authoring.session.project_id, pid)
            restarted.studio._show(2)
            app.processEvents()
            self.assertEqual(restarted.studio.editor.toPlainText(), revised)
            self.assertEqual(restarted.studio.quality.text().count('NOT_RUN') >= 1, True)

            # Regression: declining to discard must keep the current editor;
            # confirming discard must restore only the last persisted version.
            from unittest.mock import patch
            from PySide6.QtWidgets import QMessageBox
            unsaved = revised + ' 저장하지 않은 임시 메모'
            restarted.studio.editor.setPlainText(unsaved)
            with patch('ai_novel_factory.desktop.project_studio.QMessageBox.question',
                       return_value=QMessageBox.StandardButton.No):
                QTest.mouseClick(restarted.studio.findChild(
                    QPushButton, 'studioHomeButton'), Qt.MouseButton.LeftButton)
            self.assertEqual(restarted.studio.pages.currentIndex(), 2)
            self.assertEqual(restarted.studio.editor.toPlainText(), unsaved)
            with patch('ai_novel_factory.desktop.project_studio.QMessageBox.question',
                       return_value=QMessageBox.StandardButton.Yes):
                QTest.mouseClick(restarted.studio.findChild(
                    QPushButton, 'studioHomeButton'), Qt.MouseButton.LeftButton)
            self.assertEqual(restarted.studio.pages.currentIndex(), 0)
            self.assertEqual(restarted.studio.editor.toPlainText(), revised)
            with EpisodeStore(path) as store:
                self.assertEqual(store.get_episode(pid, 1).draft, revised)
        finally:
            if window is not None:
                window.close()


if __name__ == '__main__':
    unittest.main()
