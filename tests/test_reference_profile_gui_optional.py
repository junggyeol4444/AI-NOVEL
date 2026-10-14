"""Stage 30 optional PySide6/offscreen reference profile UI integration."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory.desktop.reference_selection import ReferenceFileSelection


@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'PySide6 not installed')
class ReferenceProfileGuiTests(unittest.TestCase):
    def test_select_analyze_save_and_browse_offscreen(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        from ai_novel_factory.desktop.reference_profile_browser import ReferenceProfileBrowser
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            document = root / 'novel.txt'
            document.write_text('제1화\n\n희망이 있었다.\n\n제2화\n\n그러나 위험했다.', encoding='utf-8')
            selection = ReferenceFileSelection()
            selection.add_paths([str(document)])
            browser = ReferenceProfileBrowser(selection)
            db = root / 'profiles.db'
            with patch('ai_novel_factory.desktop.reference_profile_browser.default_local_catalog_path', return_value=db):
                browser._analyze_selected()
                self.assertEqual(browser.profiles.count(), 1)
                browser.profiles.setCurrentRow(0)
                self.assertIn('참고작 분석 프로필', browser.report.toPlainText())
                self.assertTrue(db.exists())
            browser.close()
        self.assertIsNotNone(app)


if __name__ == '__main__':
    unittest.main()
