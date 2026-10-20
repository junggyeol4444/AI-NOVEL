"""Real PySide6 cover button -> actual JPG pair, isolated local temp data.

This verifies GUI/source/file handling only, not human review or artwork rights.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import importlib.util
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HAVE_GUI = bool(importlib.util.find_spec('PySide6'))
HAVE_PIL = bool(importlib.util.find_spec('PIL'))
if HAVE_GUI:
    from PySide6.QtWidgets import QApplication
    from ai_novel_factory.desktop.cover_draft_widget import CoverDraftWidget
else:
    QApplication = None
    CoverDraftWidget = None
from ai_novel_factory.database.episodes import EpisodeStore


@unittest.skipUnless(HAVE_GUI and HAVE_PIL, 'PySide6 and Pillow required')
class NativeCoverDraftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.database = self.root / 'only-synthetic.sqlite'
        self.store = EpisodeStore(self.database)
        self.addCleanup(self.store.close)
        self.pid = self.store.create_project(
            '테스트 소설 별빛의 기록', author='임시 작가').project_id
        self.session = SimpleNamespace(
            store=self.store, project_id=self.pid,
            path=self.database)
        self.widget = CoverDraftWidget(
            lambda: self.session, lambda: str(self.root))
        self.addCleanup(self.widget.close)
        self.widget.refresh()

    def test_explicit_button_creates_real_jpeg_and_never_overwrites(self):
        from PIL import Image
        self.assertEqual(self.widget.title_field.text(), '테스트 소설 별빛의 기록')
        self.assertEqual(self.widget.author_field.text(), '임시 작가')
        self.assertFalse((self.root / 'cover.jpg').exists())
        project_before = self.store.get_project(self.pid)
        self.widget.generate_button.click()
        cover, thumb = self.root / 'cover.jpg', self.root / 'thumbnail.jpg'
        self.assertTrue(cover.is_file() and thumb.is_file())
        with Image.open(cover) as img:
            self.assertEqual(img.size, (1600, 2560))
            self.assertEqual(img.format, 'JPEG')
        with Image.open(thumb) as img:
            self.assertEqual(img.size, (400, 640))
        self.assertIn('로컬 저장 완료', self.widget.status.text())
        self.assertEqual(self.store.get_project(self.pid).revision,
                         project_before.revision)
        old = cover.read_bytes()
        self.widget.generate_button.click()
        self.assertIn('저장 실패', self.widget.status.text())
        self.assertEqual(cover.read_bytes(), old)

    def test_no_creation_without_existing_local_directory_or_author(self):
        self.widget.author_field.clear()
        self.widget.generate_button.click()
        self.assertIn('필명', self.widget.status.text())
        self.assertFalse((self.root / 'cover.jpg').exists())
        with tempfile.TemporaryDirectory() as other:
            widget = CoverDraftWidget(
                lambda: self.session, lambda: str(Path(other) / 'missing'))
            self.addCleanup(widget.close)
            widget.refresh()
            widget.generate_button.click()
            self.assertIn('절대경로', widget.status.text())
            self.assertFalse((Path(other) / 'missing').exists())

    def test_no_project_does_not_reuse_previous_author_details(self):
        self.session.project_id = None
        self.widget.refresh()
        self.assertEqual(self.widget.title_field.text(), '')
        self.assertEqual(self.widget.author_field.text(), '')
        self.widget.generate_button.click()
        self.assertFalse((self.root / 'cover.jpg').exists())

    def test_existing_user_artwork_is_unchanged(self):
        path = self.root / 'cover.jpg'
        path.write_bytes(b'USER ARTWORK KEEP')
        self.widget.generate_button.click()
        self.assertEqual(path.read_bytes(), b'USER ARTWORK KEEP')
        self.assertFalse((self.root / 'thumbnail.jpg').exists())


if __name__ == '__main__':
    unittest.main()
