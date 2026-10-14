"""Qt offscreen smoke tests; automatically skipped if PySide6 is unavailable."""
import importlib.util
import os
import tempfile
from pathlib import Path
import unittest

from ai_novel_factory.database.episodes import EpisodeStore


@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'PySide6 not installed')
class PlotEditorGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from ai_novel_factory.desktop.plot_editor import PlotEditorWidget
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'local.db'
        with EpisodeStore(self.path) as db:
            self.pid = db.create_project('직접 편집 작품').project_id
            db.create_episode(self.pid, 1, plot='원래 내용')
        self.widget = PlotEditorWidget()
        self.addCleanup(self.widget.session.close)

    def test_load_and_manual_save(self):
        self.widget.open_database(str(self.path))
        self.assertEqual(self.widget.plot_input.toPlainText(), '원래 내용')
        self.widget.plot_input.setPlainText('변경 내용')
        with EpisodeStore(self.path) as db:
            self.assertEqual(db.get_episode(self.pid, 1).plot, '원래 내용')
        self.widget.save_plot_button.click()
        with EpisodeStore(self.path) as db:
            self.assertEqual(db.get_episode(self.pid, 1).plot, '변경 내용')

    def test_add_and_save_scene(self):
        self.widget.open_database(str(self.path))
        self.widget.add_scene_button.click()
        self.assertEqual(self.widget.scene_combo.count(), 1)
        self.widget.scene_input.setPlainText('장소: 숲 / 목표: 탈출')
        self.widget.save_scene_button.click()
        with EpisodeStore(self.path) as db:
            self.assertEqual(db.list_scenes(self.pid, 1)[0].text, '장소: 숲 / 목표: 탈출')

    def test_integrated_episodes_page(self):
        from ai_novel_factory.desktop.app import MainWindow
        window = MainWindow()
        self.assertIsNotNone(window.plot_editor)
        window.sidebar.setCurrentRow(9)
        self.assertEqual(window.pages.currentIndex(), 9)
        window.plot_editor.session.close()
        window.close()

if __name__ == '__main__':
    unittest.main()
