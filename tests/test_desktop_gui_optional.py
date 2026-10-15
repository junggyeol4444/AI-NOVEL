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
        self.assertEqual(window.sidebar.count(), 12)
        window.sidebar.setCurrentRow(7)
        self.assertEqual(window.pages.currentIndex(), 7)
        self.assertIn('내 컴퓨터에 안전하게 보관', window.statusBar().currentMessage())
        self.assertIsNotNone(window.studio)
        self.assertEqual(window.studio.pages.currentIndex(), 0)
        self.assertFalse(window.sidebar.isVisible())
        self.assertIsNotNone(window.advanced_nav_button)
        # Primary writing navigation leads new users to the creation wizard.
        from PySide6.QtWidgets import QPushButton
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        QTest.mouseClick(window.findChild(QPushButton, 'primaryWritingButton'),
                         Qt.MouseButton.LeftButton)
        self.assertEqual(window.studio.pages.currentIndex(), 1)
        window.close()
        self.assertIsNotNone(app)

if __name__ == '__main__':
    unittest.main()
