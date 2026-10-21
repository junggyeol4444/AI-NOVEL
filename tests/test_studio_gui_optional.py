"""Fast GUI regression: real Qt widget clicks, never a human UX acceptance.

Only synthetic content and explicit local operations. Headless CI is NOT a
substitute for a physical Windows 10/11 user's native EXE interaction.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'PySide6 not installed')
class UserFirstStudioTests(unittest.TestCase):
    def test_studio_creation_blocks_live_ai_and_revokes_model_consent(self):
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        from unittest.mock import patch
        from PySide6.QtCore import QStandardPaths
        from PySide6.QtWidgets import QApplication
        from ai_novel_factory.desktop.app import MainWindow

        QStandardPaths.setTestModeEnabled(True)
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        studio = window.studio
        try:
            studio.new_title.setText('합성 프로젝트 전환 보호')
            studio.new_premise.setPlainText('테스트용 가상 설정')
            with (
                patch.object(window.authoring.auto_panel, 'is_running',
                             return_value=True),
                patch.object(studio, 'confirm_discard',
                             side_effect=AssertionError('실행 중 확인 창 금지')),
                patch.object(window.authoring.session, 'create_project',
                             side_effect=AssertionError('실행 중 DB 생성 금지')),
            ):
                studio._create_project()
            self.assertIn('다회차 집필 중', studio.create_status.text())
            with (
                patch.object(window.authoring, 'is_generating',
                             return_value=True),
                patch.object(studio, 'confirm_discard',
                             side_effect=AssertionError('집필 중 확인 창 금지')),
                patch.object(window.authoring.session, 'create_project',
                             side_effect=AssertionError('집필 중 DB 생성 금지')),
            ):
                studio._create_project()
            self.assertIn('장면 집필 중', studio.create_status.text())

            # Simulate an SQLite create failure after user consent was given:
            # the failed switch must not carry old approvals into a retry.
            window.authoring.approved.setChecked(True)
            window.authoring.auto_panel.consent.setChecked(True)
            with patch.object(window.authoring.session, 'create_project',
                              side_effect=ValueError('합성 생성 실패')):
                studio._create_project()
            self.assertFalse(window.authoring.approved.isChecked())
            self.assertFalse(window.authoring.auto_panel.consent.isChecked())
            self.assertIn('합성 생성 실패', studio.create_status.text())
        finally:
            window.close()
            app.processEvents()

    def test_gui_smoke_launches_current_main_window(self):
        # Execute the same launcher --gui-smoke path as the packaged Windows
        # EXE, against disposable CI settings and without a remote API call.
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            environment = os.environ.copy()
            environment['QT_QPA_PLATFORM'] = 'offscreen'
            environment['PYTHONPATH'] = str(ROOT / 'src')
            environment['XDG_CONFIG_HOME'] = str(Path(temp) / 'config')
            environment['XDG_DATA_HOME'] = str(Path(temp) / 'data')
            process = subprocess.run(
                [sys.executable, str(ROOT / 'packaging/windows/launcher.py'),
                 '--gui-smoke'],
                cwd=ROOT, env=environment, capture_output=True,
                text=True, errors='replace', timeout=25)
            self.assertEqual(process.returncode, 0, process.stderr[-1000:])
            self.assertIn('ANF GUI smoke OK: 12 sections', process.stdout)

    def test_create_write_version_reopen_with_visible_buttons(self):
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        from unittest.mock import patch
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

            # Explicit backup of the LIVE unsaved editor text, not the
            # potentially stale SQLite draft; no version or overwrite.
            from tempfile import TemporaryDirectory
            with TemporaryDirectory() as backup_tmp:
                safety_path = Path(backup_tmp) / '현재 원고.txt'
                visible_copy = revised + ' 현재 집필 중인 내용'
                studio.editor.setPlainText(visible_copy)
                with patch('ai_novel_factory.desktop.project_studio.QFileDialog.getSaveFileName',
                           return_value=(str(safety_path), '텍스트 파일 (*.txt)')):
                    QTest.mouseClick(studio.findChild(
                        QPushButton, 'studioBackupCurrentDraft'), Qt.MouseButton.LeftButton)
                self.assertEqual(safety_path.read_text(encoding='utf-8'), visible_copy)
                self.assertIn('미저장', studio.manuscript_stats.text())
                with ManuscriptVersionStore(path) as versions:
                    self.assertEqual(len(versions.list_versions(pid, 1)), 2)
                with (
                    patch('ai_novel_factory.desktop.project_studio.QFileDialog.getSaveFileName',
                          return_value=(str(safety_path), '텍스트 파일 (*.txt)')),
                    patch('ai_novel_factory.desktop.project_studio.QMessageBox.warning'),
                ):
                    QTest.mouseClick(studio.findChild(
                        QPushButton, 'studioBackupCurrentDraft'), Qt.MouseButton.LeftButton)
                self.assertEqual(safety_path.read_text(encoding='utf-8'), visible_copy)
                self.assertEqual(studio.editor.toPlainText(), visible_copy)
                studio.editor.setPlainText(revised)

            # Real Qt search/replace works on a single selected occurrence
            # without silently persisting any unsaved prose to SQLite.
            studio.manuscript_find.setText('창작한')
            QTest.mouseClick(studio.findChild(
                QPushButton, 'studioFindNext'), Qt.MouseButton.LeftButton)
            self.assertEqual(studio.editor.textCursor().selectedText(), '창작한')
            studio.manuscript_replace.setText('만든')
            QTest.mouseClick(studio.findChild(
                QPushButton, 'studioReplaceOne'), Qt.MouseButton.LeftButton)
            self.assertIn('만든', studio.editor.toPlainText())
            self.assertIn('미저장', studio.manuscript_stats.text())
            with EpisodeStore(path) as store:
                self.assertEqual(store.get_episode(pid, 1).draft, revised)
            studio.editor.setPlainText(revised)
            # Focus mode gives a narrow-screen writer more manuscript space
            # without switching chapter, losing text or persisting edits.
            QTest.mouseClick(studio.findChild(
                QPushButton, 'studioFocusModeButton'), Qt.MouseButton.LeftButton)
            self.assertTrue(studio.focus_toggle.isChecked())
            self.assertFalse(studio.episodes_side.isVisible())
            self.assertFalse(studio.context_side.isVisible())
            self.assertEqual(studio.editor.toPlainText(), revised)
            QTest.mouseClick(studio.findChild(
                QPushButton, 'studioFocusModeButton'), Qt.MouseButton.LeftButton)
            self.assertFalse(studio.focus_toggle.isChecked())
            self.assertTrue(studio.episodes_side.isVisible())
            self.assertEqual(session.episode_number, 1)

            studio.manuscript_find.setText('실제로 존재하지 않는 문자열')
            QTest.mouseClick(studio.findChild(
                QPushButton, 'studioFindNext'), Qt.MouseButton.LeftButton)
            self.assertIn('일치하는 글이 없습니다', studio.find_feedback.text())
            self.assertEqual(studio.editor.toPlainText(), revised)

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

            # Failed opening of a nonexistent SQLite must retain both the
            # active session and its correct file path in the advanced form.
            prior_path = window.authoring._text('db')
            live_edit = revised + ' DB 선택 실패 중 미저장 문장'
            studio.editor.setPlainText(live_edit)
            missing = path.with_name('missing_synthetic_project.sqlite')
            with (patch('ai_novel_factory.desktop.project_studio.QMessageBox.question',
                        return_value=QMessageBox.StandardButton.Yes),
                  patch('ai_novel_factory.desktop.project_studio.QMessageBox.warning')):
                studio._open_path(missing)
            self.assertEqual(session.path, path)
            self.assertEqual(window.authoring._text('db'), prior_path)
            self.assertEqual(studio.editor.toPlainText(), live_edit)
            studio.editor.setPlainText(revised)
            self.assertIn('저장본과 일치', studio.manuscript_stats.text())

            # Reuse the second chapter from the navigation test above:
            # attempting to insert it again is correctly rejected by SQLite.
            # A failed chapter read must leave the current unsaved manuscript.
            self.assertEqual(len(session.store.list_episodes(pid)), 2)
            session.select_episode(1)
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

            # Clicking New Chapter then cancelling the modal must never
            # prompt to throw away the chapter being edited.
            modal_cancellation = {}
            def dismiss_chapter_dialog():
                dialogs = [w for w in QApplication.topLevelWidgets()
                           if isinstance(w, QDialog)
                           and w.windowTitle() == '새 회차 기획']
                modal_cancellation['visible'] = bool(dialogs)
                if dialogs:
                    dialogs[0].reject()
            QTimer.singleShot(0, dismiss_chapter_dialog)
            with patch('ai_novel_factory.desktop.project_studio.QMessageBox.question',
                       side_effect=AssertionError('Cancelled new chapter must not discard')):
                QTest.mouseClick(studio.findChild(
                    QPushButton, 'studioAddEpisode'), Qt.MouseButton.LeftButton)
            self.assertTrue(modal_cancellation.get('visible'))
            self.assertEqual(studio.editor.toPlainText(), unsaved_switch)
            self.assertEqual(session.episode_number, 1)
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


    def test_legacy_sqlite_without_optional_rules_is_readable(self):
        # Legacy/synthetic SQLite can have an episode but no author or
        # premise rules. Reading it must not write fabricated metadata.
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        from tempfile import TemporaryDirectory
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QCoreApplication, QEvent
        from ai_novel_factory.database.episodes import EpisodeStore
        from ai_novel_factory.desktop.authoring_workflow import AuthoringWorkflowWidget
        app = QApplication.instance() or QApplication([])
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'synthetic_legacy.sqlite'
            with EpisodeStore(path) as db:
                pid = db.create_project('옛날 합성 작품').project_id
                db.create_episode(pid, 1, plot='합성 장면 설계')
                self.assertEqual(tuple(db.list_rules(pid)), ())
            widget = AuthoringWorkflowWidget()
            try:
                widget._set('db', str(path))
                widget._open()
                widget._sync()
                self.assertEqual(widget.session.project_id, pid)
                self.assertEqual(widget._text('title'), '옛날 합성 작품')
                self.assertEqual(widget._text('author'), '')
                self.assertEqual(widget._text('premise'), '')
                self.assertEqual(widget._text('bible'), '')
                self.assertEqual(widget.session.episode_number, 1)
                with EpisodeStore(path) as db:
                    self.assertEqual(tuple(db.list_rules(pid)), ())
            finally:
                widget.session.close()
                widget.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                app.processEvents()


if __name__ == '__main__':
    unittest.main()
