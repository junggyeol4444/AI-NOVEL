"""Optional GUI smoke test; runs only if PySide6 is available."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'PySide6 not installed')
class DesktopGuiTests(unittest.TestCase):
    def test_sidebar_switches_pages(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        from ai_novel_factory.desktop.app import MainWindow
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        window.resize(820, 560)  # supported minimum window size
        window.show()
        app.processEvents()
        self.assertEqual(window.sidebar.count(), 12)
        window.sidebar.setCurrentRow(7)
        self.assertEqual(window.pages.currentIndex(), 7)
        self.assertIn('내 컴퓨터에 안전하게 보관', window.statusBar().currentMessage())
        self.assertIsNotNone(window.studio)
        self.assertEqual(window.studio.pages.currentIndex(), 0)
        self.assertFalse(window.sidebar.isVisible())
        self.assertIsNotNone(window.advanced_nav_button)
        # Simulate Windows UIAutomation TogglePattern: it may change the Qt
        # check state directly without emitting QPushButton.clicked().
        self.assertFalse(window.advanced_nav_button.isChecked())
        window.advanced_nav_button.setChecked(True)
        app.processEvents()
        self.assertTrue(window.sidebar.isVisible())
        self.assertIn('닫기', window.advanced_nav_button.text())
        self.assertTrue(all(not button.isVisible() for button in window.primary_nav_buttons))
        # The Windows 11 Qt UIA provider exposes only visible list rows and
        # provides neither usable ScrollPattern nor RangeValuePattern. The
        # specialist rail must therefore fit all 12 at minimum window size.
        viewport = window.sidebar.viewport().rect()
        self.assertEqual(window.sidebar.verticalScrollBar().maximum(), 0)
        for index in range(window.sidebar.count()):
            rect = window.sidebar.visualItemRect(window.sidebar.item(index))
            self.assertTrue(viewport.contains(rect), (index, rect, viewport))
        window.advanced_nav_button.setChecked(False)
        app.processEvents()
        self.assertFalse(window.sidebar.isVisible())
        self.assertIn('보기', window.advanced_nav_button.text())
        self.assertTrue(all(button.isVisible() for button in window.primary_nav_buttons))
        # Primary writing navigation leads new users to the creation wizard.
        from PySide6.QtWidgets import QPushButton
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        QTest.mouseClick(window.findChild(QPushButton, 'primaryWritingButton'),
                         Qt.MouseButton.LeftButton)
        self.assertEqual(window.studio.pages.currentIndex(), 1)
        self.assertTrue(window.studio.create_scroll.widgetResizable())
        self.assertIsNotNone(window.studio.create_scroll.widget())
        # The studio's secondary writing shortcut must behave identically.
        window.studio._show(0)
        QTest.mouseClick(window.studio.findChild(QPushButton, 'studioWritingButton'),
                         Qt.MouseButton.LeftButton)
        self.assertEqual(window.studio.pages.currentIndex(), 1)
        window.close()
        self.assertIsNotNone(app)

class ModelApprovalGuiTests(unittest.TestCase):
    """Real Qt widget behavior in disposable offscreen UI, not literary QA."""

    @unittest.skipUnless(importlib.util.find_spec('PySide6'), 'PySide6 not installed')
    def test_approval_invalidated_on_model_edit_and_choosing_other_executable(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from unittest.mock import patch
        from PySide6.QtWidgets import QApplication, QFileDialog
        from ai_novel_factory.desktop.authoring_workflow import AuthoringWorkflowWidget
        app = QApplication.instance() or QApplication([])
        ui = AuthoringWorkflowWidget()
        try:
            ui._set('executable', '/temporary/first-runtime.exe')
            ui._set('arguments', "--gguf '/temporary/first-model.gguf'")
            ui.approved.setChecked(True)
            ui._set('arguments', "--gguf '/temporary/second-model.gguf'")
            self.assertFalse(ui.approved.isChecked())
            ui.approved.setChecked(True)
            ui._set('executable', '/temporary/modified-runtime.exe')
            self.assertFalse(ui.approved.isChecked())
            ui.approved.setChecked(True)
            with patch.object(QFileDialog, 'getOpenFileName',
                              return_value=('/temporary/new-runtime.exe', '')):
                ui._choose_model_executable()
            self.assertEqual(ui._text('executable'), '/temporary/new-runtime.exe')
            self.assertEqual(ui._text('arguments'), '')
            self.assertFalse(ui.approved.isChecked())
            self.assertIn('이전 모델 인수를 초기화', ui.status.text())
        finally:
            ui.close()
            app.processEvents()

    @unittest.skipUnless(importlib.util.find_spec('PySide6'), 'PySide6 not installed')
    def test_approved_gguf_path_with_spaces_roundtrips_as_one_argument(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        import shlex
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from PySide6.QtWidgets import QApplication, QFileDialog
        from ai_novel_factory.desktop.authoring_workflow import AuthoringWorkflowWidget
        app = QApplication.instance() or QApplication([])
        ui = AuthoringWorkflowWidget()
        try:
            with TemporaryDirectory() as folder:
                root = Path(folder)
                (root / 'runtime').mkdir()
                (root / 'ANF_Local_Model.exe').touch()
                (root / 'runtime' / 'llama-cli.exe').touch()
                gguf = root / '작가 승인 모델 with spaces.gguf'
                with gguf.open('wb') as stream:
                    stream.write(b'GGUF' + (3).to_bytes(4, 'little')
                                 + (200).to_bytes(8, 'little')
                                 + (40).to_bytes(8, 'little'))
                    stream.truncate(8_000_001)
                with patch.object(sys, 'frozen', True, create=True), patch.object(
                        sys, 'executable', str(root / 'AI_Novel_Factory.exe')), patch.object(
                        QFileDialog, 'getOpenFileName', return_value=(str(gguf), '')):
                    ui.approved.setChecked(True)
                    ui._choose_gguf_model()
                self.assertEqual(shlex.split(ui._text('arguments')),
                                 ['--gguf', str(gguf)])
                self.assertFalse(ui.approved.isChecked())
                # Windows can return a resolved long-name path for the same
                # temp folder passed as RUNNER~1. Compare filesystem targets,
                # never textual 8.3 aliases, without weakening model checks.
                self.assertEqual(
                    Path(ui._text('executable')).resolve(),
                    (root / 'ANF_Local_Model.exe').resolve())
        finally:
            ui.close()
            app.processEvents()


    @unittest.skipUnless(importlib.util.find_spec('PySide6'), 'PySide6 not installed')
    def test_gui_rejects_renamed_non_gguf_before_model_approval(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from PySide6.QtWidgets import QApplication, QFileDialog
        from ai_novel_factory.desktop.authoring_workflow import AuthoringWorkflowWidget
        app = QApplication.instance() or QApplication([])
        ui = AuthoringWorkflowWidget()
        try:
            with TemporaryDirectory() as folder:
                root = Path(folder)
                (root / 'runtime').mkdir()
                (root / 'ANF_Local_Model.exe').touch()
                (root / 'runtime' / 'llama-cli.exe').touch()
                fake = root / 'broken-custom-model.gguf'
                with fake.open('wb') as stream:
                    stream.write(b'NOT!' + (3).to_bytes(4, 'little'))
                    stream.truncate(8_000_001)
                with patch.object(sys, 'frozen', True, create=True), patch.object(
                        sys, 'executable', str(root / 'AI_Novel_Factory.exe')), patch.object(
                        QFileDialog, 'getOpenFileName', return_value=(str(fake), '')):
                    ui._choose_gguf_model()
                self.assertNotIn(str(fake), ui._text('arguments'))
                self.assertFalse(ui.approved.isChecked())
                self.assertIn('헤더가 올바르지', ui.status.text())
        finally:
            ui.close()
            app.processEvents()

    @unittest.skipUnless(importlib.util.find_spec('PySide6'), 'PySide6 not installed')
    def test_gui_rejects_gguf_header_without_actual_model_tensors(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from PySide6.QtWidgets import QApplication, QFileDialog
        from ai_novel_factory.desktop.authoring_workflow import AuthoringWorkflowWidget
        app = QApplication.instance() or QApplication([])
        ui = AuthoringWorkflowWidget()
        try:
            with TemporaryDirectory() as folder:
                root = Path(folder)
                (root / 'runtime').mkdir()
                (root / 'ANF_Local_Model.exe').touch()
                (root / 'runtime' / 'llama-cli.exe').touch()
                corrupted = root / 'empty-tensor-model.gguf'
                with corrupted.open('wb') as stream:
                    stream.write(b'GGUF' + (3).to_bytes(4, 'little')
                                 + (0).to_bytes(8, 'little')
                                 + (50).to_bytes(8, 'little'))
                    stream.truncate(8_000_001)
                with patch.object(sys, 'frozen', True, create=True), patch.object(
                        sys, 'executable', str(root / 'AI_Novel_Factory.exe')), patch.object(
                        QFileDialog, 'getOpenFileName', return_value=(str(corrupted), '')):
                    ui._choose_gguf_model()
                self.assertEqual(ui._text('arguments'), '')
                self.assertFalse(ui.approved.isChecked())
                self.assertIn('헤더가 올바르지', ui.status.text())
        finally:
            ui.close()
            app.processEvents()

    @unittest.skipUnless(importlib.util.find_spec('PySide6'), 'PySide6 not installed')
    def test_batch_approval_revoked_after_model_and_scope_changes(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        from ai_novel_factory.desktop.authoring_workflow import AuthoringWorkflowWidget
        app = QApplication.instance() or QApplication([])
        ui = AuthoringWorkflowWidget()
        try:
            batch = ui.auto_panel
            batch.consent.setChecked(True)
            ui._set('arguments', '--gguf selected_model_one.gguf')
            self.assertFalse(batch.consent.isChecked())
            batch.consent.setChecked(True)
            ui._set('executable', '/temporary/another-approved-runtime.exe')
            self.assertFalse(batch.consent.isChecked())
            batch.consent.setChecked(True)
            batch.scenes.setValue(batch.scenes.value() + 1)
            self.assertFalse(batch.consent.isChecked())
            batch.consent.setChecked(True)
            batch.target_chars.setValue(batch.target_chars.value() + 1)
            self.assertFalse(batch.consent.isChecked())
            batch.consent.setChecked(True)
            batch.through.setValue(batch.through.value() + 1)
            self.assertFalse(batch.consent.isChecked())
        finally:
            ui.close()
            app.processEvents()

if __name__ == '__main__':
    unittest.main()
