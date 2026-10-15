"""Exclusive TXT safety copies protect a live authoring draft."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory.desktop.draft_backup import DraftBackupError, write_draft_copy


class DraftBackupSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_exact_unicode_copy_with_private_mode(self):
        path = self.root / '가상 원고.txt'
        text = '합성 제1화\n\n   이별과 만남.  '
        self.assertEqual(write_draft_copy(path, text), path)
        self.assertEqual(path.read_bytes(), text.encode('utf-8'))
        if os.name == 'posix':
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_preexisting_file_is_never_overwritten(self):
        path = self.root / 'original.txt'
        path.write_text('기존 원고', encoding='utf-8')
        with self.assertRaises(DraftBackupError):
            write_draft_copy(path, '새 글')
        self.assertEqual(path.read_text(encoding='utf-8'), '기존 원고')

    def test_racing_new_file_is_never_deleted(self):
        path = self.root / 'race.txt'
        original = os.open
        def race(target, flags, mode=0o777):
            path.write_text('경쟁 사용자 파일', encoding='utf-8')
            return original(target, flags, mode)
        with patch('ai_novel_factory.desktop.draft_backup.os.open', side_effect=race):
            with self.assertRaises(DraftBackupError):
                write_draft_copy(path, '다른 원고')
        self.assertEqual(path.read_text(encoding='utf-8'), '경쟁 사용자 파일')

    def test_empty_and_relative_path_rejected(self):
        with self.assertRaises(DraftBackupError):
            write_draft_copy(self.root / 'blank.txt', ' \n ')
        with self.assertRaises(DraftBackupError):
            write_draft_copy('relative.txt', '내용')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_only_new_txt_paths(self):
        with self.assertRaises(DraftBackupError):
            write_draft_copy(self.root / 'database.sqlite', '보관')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_symbolic_link_cannot_overwrite_target(self):
        path = self.root / 'user.txt'
        path.write_text('원본', encoding='utf-8')
        link = self.root / 'alias.txt'
        try:
            link.symlink_to(path)
        except (OSError, NotImplementedError):
            self.skipTest('OS symbolic-link privilege unavailable')
        with self.assertRaises(DraftBackupError):
            write_draft_copy(link, '변경')
        self.assertEqual(path.read_text(encoding='utf-8'), '원본')

    def test_failed_disk_sync_removes_only_partial_copy(self):
        path = self.root / 'partial.txt'
        with patch('ai_novel_factory.desktop.draft_backup.os.fsync',
                   side_effect=OSError('synthetic full disk')):
            with self.assertRaises(OSError):
                write_draft_copy(path, '미완성 백업')
        self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
