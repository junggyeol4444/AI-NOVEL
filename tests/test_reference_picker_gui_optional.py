"""Stage 11 GUI tests; skip if PySide6 is not installed."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'PySide6 not installed')
class ReferencePickerGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_reference_page_integrated_with_sidebar(self):
        from ai_novel_factory.desktop.app import MainWindow
        window = MainWindow()
        window.sidebar.setCurrentRow(7)
        self.assertEqual(window.pages.currentIndex(), 7)
        self.assertIsNotNone(window.reference_picker)
        self.assertEqual(window.reference_picker.file_list.count(), 0)
        window.close()

    def test_choose_cancel_clear_no_network_or_file_reads(self):
        from ai_novel_factory.desktop.reference_picker import ReferencePickerWidget
        picker = ReferencePickerWidget()
        with patch('ai_novel_factory.desktop.reference_picker.QFileDialog.getOpenFileNames',
                   side_effect=[(['/private/one.txt', '/private/two.pdf'], ''), ([], '')]):
            picker.choose_button.click()
            self.assertEqual(picker.file_list.count(), 2)
            self.assertEqual(picker.file_list.item(0).text(), 'one.txt')
            picker.choose_button.click()
            self.assertEqual(picker.file_list.count(), 2)
        picker.clear_button.click()
        self.assertEqual(picker.file_list.count(), 0)
        self.assertIn('0개', picker.selection_status.text())
        picker.close()


if __name__ == '__main__':
    unittest.main()
