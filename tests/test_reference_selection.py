"""Stage 11 file selection model tests; do not require Qt or actual files."""
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from ai_novel_factory.desktop.reference_selection import (
    REFERENCE_FILE_FILTER,
    SUPPORTED_REFERENCE_SUFFIXES,
    ReferenceFileSelection,
    display_filename,
)


class ReferenceSelectionTests(TestCase):
    def test_supported_types_in_filter(self):
        for suffix in SUPPORTED_REFERENCE_SUFFIXES:
            self.assertIn('*' + suffix, REFERENCE_FILE_FILTER)

    def test_add_multiple_preserves_order_and_deduplicates(self):
        selected = ReferenceFileSelection()
        selected.add_paths(['/private/a.txt', '/private/b.epub', '/private/a.txt'])
        selected.add_paths(['/private/c.docx', '/private/b.epub'])
        self.assertEqual(selected.selected_paths, (
            '/private/a.txt', '/private/b.epub', '/private/c.docx'))

    def test_displays_filename_only_for_posix_and_windows_paths(self):
        selected = ReferenceFileSelection()
        selected.add_paths(['/home/user/private/story.txt', r'C:\Users\Name\novel.pdf'])
        self.assertEqual(selected.display_names, ('story.txt', 'novel.pdf'))
        self.assertEqual(display_filename(r'D:\Archive\book.markdown'), 'book.markdown')

    def test_empty_or_invalid_values_ignored(self):
        selected = ReferenceFileSelection()
        selected.add_paths(['', '  ', None, 42, '/a.md'])
        self.assertEqual(selected.selected_paths, ('/a.md',))

    def test_clear_selection(self):
        selected = ReferenceFileSelection()
        selected.add_paths(['/a.txt'])
        selected.clear()
        self.assertEqual(selected.selected_paths, ())
        self.assertEqual(selected.display_names, ())

    def test_selection_never_opens_files(self):
        selected = ReferenceFileSelection()
        with patch('builtins.open', side_effect=AssertionError('unexpected read')):
            selected.add_paths(['/nonexistent/a.txt', '/nonexistent/b.pdf'])
            self.assertEqual(selected.display_names, ('a.txt', 'b.pdf'))
            selected.clear()

    def test_selected_paths_are_immutable_snapshot(self):
        selected = ReferenceFileSelection()
        selected.add_paths(['/a.txt'])
        before = selected.selected_paths
        selected.add_paths(['/b.pdf'])
        self.assertEqual(before, ('/a.txt',))
        self.assertEqual(selected.selected_paths, ('/a.txt', '/b.pdf'))
