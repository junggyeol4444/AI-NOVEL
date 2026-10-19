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

    def test_saved_episode_character_goal_reaches_native_scene_payload(self):
        # This exercises the real authoring session and an isolated temporary
        # SQLite DB; it never invokes an external model or accesses user files.
        import sys
        from ai_novel_factory.local_models import _message
        self.session.create_project(
            str(self.path), '가상 원고', '테스트 작가', '가상의 고문서 사건',
            extra_rules={'characters_per_episode': '5000'})
        self.session.create_episode(1, '사라진 기록을 찾는다')
        self.session.add_scene('서가에서 첫 번째 흔적을 발견한다')
        def prepared():
            request, _, _ = self.session.prepare_generation(
                sys.executable, ('--gguf', 'synthetic.gguf'), True,
                '기록관이 낡은 종이를 읽는다', '사서가 문을 막는다',
                '도서관 서가', ('기록관', '사서'))
            return request
        one = prepared()
        self.assertEqual(one.target_chars, 5000)
        self.assertEqual(_message(one)['request']['target_chars'], 5000)
        self.assertIn('회차당 목표 글자 수: 5000', one.novel_bible)
        self.assertNotIn('characters_per_episode:', one.novel_bible)
        self.session.add_scene('뒷문으로 나가는 다른 장면')
        two = prepared()
        self.assertEqual(two.target_chars, 2500)
        self.assertEqual(_message(two)['request']['target_chars'], 2500)
        # A per-scene partial does NOT satisfy the entire episode target.
        self.assertLess(two.target_chars, int(
            self.session.rule('characters_per_episode')))

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

    def test_failed_existing_project_open_preserves_current_work(self):
        old_pid = self.create()
        old_path = self.session.path
        self.session.create_episode(1, '기존 작업의 회차')
        other = Path(self.temp.name) / 'synthetic-other.sqlite'
        from ai_novel_factory.database.episodes import EpisodeStore
        with EpisodeStore(other) as storage:
            storage.create_project('외부 가상 작품')
        with patch('ai_novel_factory.desktop.authoring_session.EpisodeStore.list_episodes',
                   side_effect=ValueError('synthetic malformed chapter list')):
            with self.assertRaises(ValueError):
                self.session.open_project(str(other))
        self.assertEqual(self.session.project_id, old_pid)
        self.assertEqual(self.session.path, old_path)
        self.assertEqual(self.session.episode_number, 1)
        self.assertEqual(self.session.episode().plot, '기존 작업의 회차')

    def test_invalid_import_metadata_or_checks_preserves_live_session(self):
        # A malformed but structurally valid external novel cannot replace
        # the current project merely because its episode list was readable.
        pid = self.create()
        self.session.create_episode(1, '계속 보존할 기존 회차')
        self.session.pending_draft = '화면에 아직 저장하지 않은 가상 원고'
        original_store = self.session.store
        old_path = self.session.path
        from ai_novel_factory.database.episodes import EpisodeStore
        other = Path(self.temp.name) / 'synthetic-corrupted-external.sqlite'
        with EpisodeStore(other) as database:
            imported_id = database.create_project('합성 외부 작품').project_id
            database.create_episode(imported_id, 1, plot='합성 외부 회차')
        for broken_read in ('get_project', 'list_rules', 'list_checks'):
            with self.subTest(read=broken_read):
                with patch.object(EpisodeStore, broken_read,
                                  side_effect=ValueError('synthetic corrupt import')):
                    with self.assertRaises(ValueError):
                        self.session.open_project(str(other))
                self.assertIs(self.session.store, original_store)
                self.assertEqual(self.session.project_id, pid)
                self.assertEqual(self.session.path, old_path)
                self.assertEqual(self.session.episode_number, 1)
                self.assertEqual(self.session.pending_draft,
                                 '화면에 아직 저장하지 않은 가상 원고')
                self.assertEqual(self.session.episode().plot, '계속 보존할 기존 회차')

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
