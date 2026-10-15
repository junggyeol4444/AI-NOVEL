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
        from PySide6.QtCore import Qt, QStandardPaths, QTimer, QCoreApplication, QEvent
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import (
            QApplication, QPushButton, QListWidget, QPlainTextEdit, QDialog)
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

            # Chapter filters and neighboring buttons operate on synthetic
            # real SQLite episodes; they do not search private draft text.
            session.create_episode(2, '합성 2화 기획')
            session.select_episode(1)
            window.authoring._sync()
            studio._loaded_episode = None
            studio.refresh()
            self.assertEqual(studio.episode_list.count(), 2)
            studio.episode_search.setText('2화')
            self.assertTrue(studio.episode_list.item(0).isHidden())
            self.assertFalse(studio.episode_list.item(1).isHidden())
            self.assertIn('1 / 전체 2', studio.episode_matches.text())
            studio.episode_search.setText('없는 회차')
            self.assertTrue(studio.episode_list.item(0).isHidden())
            self.assertTrue(studio.episode_list.item(1).isHidden())
            QTest.mouseClick(studio.findChild(QPushButton, 'studioNextEpisode'),
                             Qt.MouseButton.LeftButton)
            self.assertEqual(session.episode_number, 1)  # no matching item
            studio.episode_search.clear()
            QTest.mouseClick(studio.findChild(QPushButton, 'studioNextEpisode'),
                             Qt.MouseButton.LeftButton)
            self.assertEqual(session.episode_number, 2)
            QTest.mouseClick(studio.findChild(QPushButton, 'studioPreviousEpisode'),
                             Qt.MouseButton.LeftButton)
            self.assertEqual(session.episode_number, 1)
            self.assertEqual(studio.editor.toPlainText(), revised)
            from unittest.mock import patch
            from PySide6.QtWidgets import QMessageBox
            temporary = revised + ' 회차 이동 중 임시 메모'
            studio.editor.setPlainText(temporary)
            with patch('ai_novel_factory.desktop.project_studio.QMessageBox.question',
                       return_value=QMessageBox.StandardButton.No):
                QTest.mouseClick(studio.findChild(QPushButton, 'studioNextEpisode'),
                                 Qt.MouseButton.LeftButton)
            self.assertEqual(session.episode_number, 1)
            self.assertEqual(studio.editor.toPlainText(), temporary)
            with EpisodeStore(path) as store:
                self.assertEqual(store.get_episode(pid, 1).draft, revised)
            studio.editor.setPlainText(revised)

            # A running AI worker blocks closing BEFORE asking to discard.
            # A declined/blocked shutdown must leave the user's draft intact.
            from unittest.mock import patch
            uncommitted = revised + ' 저장하지 않은 테스트 문장'
            studio.editor.setPlainText(uncommitted)
            self.assertIn('미저장', studio.manuscript_stats.text())
            with (patch.object(window.authoring.auto_panel, 'is_running',
                               return_value=True),
                  patch.object(window.authoring.auto_panel, 'request_stop') as stop,
                  patch('ai_novel_factory.desktop.project_studio.QMessageBox.question',
                        side_effect=AssertionError('Shutdown must not prompt to discard'))):
                self.assertFalse(window.close())
                stop.assert_called_once()
            self.assertEqual(studio.editor.toPlainText(), uncommitted)
            self.assertIn('미저장', studio.manuscript_stats.text())
            studio.editor.setPlainText(revised)
            self.assertIn('저장본과 일치', studio.manuscript_stats.text())

            # Even if the person agrees to switch away, a failed chapter
            # read must leave both the unsaved editor and active chapter.
            session.create_episode(2, '')
            studio.refresh()
            unsaved_switch = '실패한 회차 이동 중 절대로 버리지 말 것'
            studio.editor.setPlainText(unsaved_switch)
            with (patch.object(session, 'select_episode',
                               side_effect=ValueError('synthetic unreadable chapter')),
                  patch('ai_novel_factory.desktop.project_studio.QMessageBox.question',
                        return_value=QMessageBox.StandardButton.Yes),
                  patch('ai_novel_factory.desktop.project_studio.QMessageBox.warning')):
                studio.episode_list.setCurrentRow(1)
            self.assertEqual(session.episode_number, 1)
            self.assertEqual(studio.episode_list.currentItem().data(
                Qt.ItemDataRole.UserRole), 1)
            self.assertEqual(studio.editor.toPlainText(), unsaved_switch)
            studio.editor.setPlainText(revised)
            self.assertIn('저장본과 일치', studio.manuscript_stats.text())

            self.assertTrue(window.close())
            # QWidget.close() only hides a window. Explicitly dispose it
            # before opening another QApplication top-level window; otherwise
            # Qt can crash during interpreter teardown after tests print OK.
            window.deleteLater()
            studio = None
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
            window = None
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
            self.assertIn('공백 제외', restarted.studio.manuscript_stats.text())
            self.assertIn('목표 5,000글자', restarted.studio.manuscript_stats.text())
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

            # Actual Qt button/accessible dialog shows two persisted drafts
            # without editing either record.
            restarted.studio._show(2)
            modal_check = {}
            def inspect_version_dialog():
                dialogs = [w for w in QApplication.topLevelWidgets()
                           if isinstance(w, QDialog)
                           and w.objectName() == 'studioVersionHistoryDialog']
                if dialogs:
                    dlg = dialogs[0]
                    entries = dlg.findChild(QListWidget, 'studioVersionHistoryEntries')
                    preview = dlg.findChild(QPlainTextEdit, 'studioVersionHistoryPreview')
                    modal_check['count'] = entries.count()
                    modal_check['readonly'] = preview.isReadOnly()
                    entries.setCurrentRow(0)
                    modal_check['old_text'] = preview.toPlainText()
                    dlg.reject()
                else:
                    modal_check['error'] = 'Version history dialog was not found'
            QTimer.singleShot(0, inspect_version_dialog)
            QTest.mouseClick(restarted.studio.findChild(
                QPushButton, 'studioVersionHistoryButton'), Qt.MouseButton.LeftButton)
            self.assertEqual(modal_check.get('count'), 2, modal_check)
            self.assertTrue(modal_check.get('readonly'), modal_check)
            self.assertEqual(modal_check.get('old_text'), original)

            # Cancellation or failed restoration must never silently delete
            # unsaved prose; the data remains in the editor until successful.
            with ManuscriptVersionStore(path) as versions:
                baseline_id = versions.list_versions(pid, 1)[0].version_id
            uncommitted_restore = '복원 중에도 잃어버리면 안 되는 편집 텍스트'
            restarted.studio.editor.setPlainText(uncommitted_restore)
            with patch('ai_novel_factory.desktop.project_studio.QMessageBox.question',
                       return_value=QMessageBox.StandardButton.No):
                self.assertFalse(restarted.studio._restore_version(baseline_id))
            self.assertEqual(restarted.studio.editor.toPlainText(), uncommitted_restore)
            with ManuscriptVersionStore(path) as versions:
                self.assertEqual(len(versions.list_versions(pid, 1)), 2)
            with (patch('ai_novel_factory.desktop.project_studio.QMessageBox.question',
                        return_value=QMessageBox.StandardButton.Yes),
                  patch('ai_novel_factory.manuscript_versions.ManuscriptVersionStore.restore_as_revision',
                        side_effect=ValueError('synthetic concurrent revision')),
                  patch('ai_novel_factory.desktop.project_studio.QMessageBox.warning')):
                self.assertFalse(restarted.studio._restore_version(baseline_id))
            self.assertEqual(restarted.studio.editor.toPlainText(), uncommitted_restore)
            with ManuscriptVersionStore(path) as versions:
                self.assertEqual(len(versions.list_versions(pid, 1)), 2)

            # A deliberately accepted restore is append-only.
            with patch('ai_novel_factory.desktop.project_studio.QMessageBox.question',
                       return_value=QMessageBox.StandardButton.Yes):
                self.assertTrue(restarted.studio._restore_version(baseline_id))
            with ManuscriptVersionStore(path) as versions:
                history = versions.list_versions(pid, 1)
                self.assertEqual(len(history), 3)
                self.assertEqual(history[0].draft, original)
                self.assertEqual(history[1].draft, revised)
                self.assertEqual(history[2].draft, original)
            with EpisodeStore(path) as store:
                self.assertEqual(store.get_episode(pid, 1).draft, original)
                self.assertFalse(store.get_episode(pid, 1).final_text)

            # Concurrent app edits must never be overwritten just because
            # the GUI reads a newer revision at the moment of saving.
            restarted.studio._show(2)
            app.processEvents()
            conflict_user_text = '창에 남은 원고, 사용자가 따로 작성함'
            restarted.studio.editor.setPlainText(conflict_user_text)
            with EpisodeStore(path) as external:
                latest = external.get_episode(pid, 1)
                external.update_episode(pid, 1, expected_revision=latest.revision,
                                        draft='동시 작업자가 저장한 원고')
            with patch('ai_novel_factory.desktop.project_studio.QMessageBox.warning'):
                QTest.mouseClick(restarted.studio.findChild(
                    QPushButton, 'studioSaveManuscript'), Qt.MouseButton.LeftButton)
            with EpisodeStore(path) as external:
                self.assertEqual(external.get_episode(pid, 1).draft,
                                 '동시 작업자가 저장한 원고')
            self.assertEqual(restarted.studio.editor.toPlainText(), conflict_user_text)
            self.assertIn('다른 작업', restarted.studio.editor_status.text())


            # Do not block teardown on an unsaved-conflict warning dialog.
            with patch('ai_novel_factory.desktop.project_studio.QMessageBox.question',
                       return_value=QMessageBox.StandardButton.Yes):
                self.assertTrue(window.close())
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
            window = None
        finally:
            if window is not None:
                with patch('ai_novel_factory.desktop.project_studio.QMessageBox.question',
                           return_value=QMessageBox.StandardButton.Yes):
                    window.close()
                window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()


if __name__ == '__main__':
    unittest.main()
