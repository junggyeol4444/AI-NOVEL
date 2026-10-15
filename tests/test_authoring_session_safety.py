"""Data protection regressions for manually created local projects.

No PySide6, no real user documents and no internet. This checks exclusive
creation, pre-existing files and cleanup after failed initialization.
"""
import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from ai_novel_factory.desktop.authoring_session import AuthoringError, AuthoringSession


class AuthoringCreationSafetyTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'synthetic-novel.sqlite'
        self.session = AuthoringSession()
        self.addCleanup(self.session.close)

    def create(self, **kwargs):
        return self.session.create_project(
            str(self.path), kwargs.get('title', '합성 작품'),
            kwargs.get('author', '실험 작가'),
            kwargs.get('premise', '가상의 마을에 존재하는 원본 설정'))

    def test_new_file_is_private_and_can_be_reopened(self):
        pid = self.create()
        self.assertTrue(self.path.is_file())
        self.assertEqual(self.session.project_id, pid)
        self.assertEqual(self.session.rule('author'), '실험 작가')
        self.session.close()
        self.session.open_project(str(self.path))
        self.assertEqual(self.session.project_id, pid)
        self.assertEqual(self.session.rule('premise'), '가상의 마을에 존재하는 원본 설정')

    def test_optional_author_is_marked_undecided(self):
        self.create(author='')
        self.assertEqual(self.session.rule('author'), '미정')

    def test_canon_is_required_before_file_creation(self):
        with self.assertRaises(AuthoringError):
            self.create(premise='')
        self.assertFalse(self.path.exists())

    def test_existing_file_is_never_modified(self):
        original = b'USER DATA, NEVER TOUCH OR OVERWRITE'
        self.path.write_bytes(original)
        with self.assertRaises(AuthoringError):
            self.create()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertIsNone(self.session.store)

    def test_race_created_file_is_never_deleted(self):
        sentinel = b'OTHER PROCESS FILE, DO NOT DELETE'
        real_open = os.open

        def racing_open(path, flags, mode=0o777):
            if str(path) == str(self.path):
                self.path.write_bytes(sentinel)
                raise FileExistsError(str(path))
            return real_open(path, flags, mode)

        with patch('ai_novel_factory.desktop.authoring_session.os.open',
                   side_effect=racing_open):
            with self.assertRaises(AuthoringError):
                self.create()
        self.assertEqual(self.path.read_bytes(), sentinel)

    def test_failed_create_deletes_only_newly_reserved_file(self):
        with self.assertRaises(ValueError):
            self.create(title='  ')
        self.assertFalse(self.path.exists())

    def test_failed_scene_load_keeps_active_episode(self):
        self.create()
        self.session.create_episode(1, '')
        self.session.create_episode(2, '')
        self.assertEqual(self.session.episode_number, 2)
        from unittest.mock import patch
        with patch.object(self.session.store, 'list_scenes',
                          side_effect=ValueError('synthetic invalid scene')):
            with self.assertRaises(ValueError):
                self.session.select_episode(1)
        self.assertEqual(self.session.episode_number, 2)

    def test_repeated_project_creation_preserves_existing_novel(self):
        pid = self.create()
        self.session.close()
        with self.assertRaises(AuthoringError):
            self.create(title='새 작품 이름')
        self.session.open_project(str(self.path))
        self.assertEqual(self.session.project_id, pid)
