"""Auto novel writer's saved author settings and eight-character context."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from ai_novel_factory.auto_novel_run import (
    _character_bible_context, _auto_author_source_stamp,
)


class AuthorSnapshotAndContextTests(unittest.TestCase):
    def test_compacts_eight_long_characters_without_omitting_final_secret(self):
        characters = tuple(SimpleNamespace(
            name=f'등장인물{i}', personality=f'성격{i}-' + '가' * 195,
            goal=f'목표{i}-' + '나' * 195,
            speech_style=f'말투{i}-' + '다' * 175,
            secret=f'비밀{i}-' + '라' * 155)
            for i in range(1, 9))
        before = repr(characters)
        context = _character_bible_context(characters)
        self.assertLessEqual(len(context), 6500)
        for i in range(1, 9):
            self.assertIn(f'등장인물{i}', context)
            for prefix in (f'성격{i}-', f'목표{i}-', f'말투{i}-', f'비밀{i}-'):
                self.assertIn(prefix, context)
        self.assertEqual(repr(characters), before)

    def test_short_character_context_keeps_all_original_details(self):
        character = SimpleNamespace(name='연', personality='용감함',
            goal='평화를 찾기', speech_style='차분한 존댓말', secret='숨은 친구')
        ctx = _character_bible_context((character,))
        for word in ('연', '용감함', '평화를 찾기', '차분한 존댓말', '숨은 친구'):
            self.assertIn(word, ctx)
        self.assertEqual(_character_bible_context(()), '')

    def test_project_title_change_invalidates_snapshot_not_own_revision(self):
        rules = [SimpleNamespace(key='genre', value='판타지', revision=1)]
        chars = [SimpleNamespace(character_id='a', revision=1, name='연',
            personality='용감', goal='평화', speech_style='차분', secret='비밀')]
        chapters = [SimpleNamespace(episode=1, revision=1)]
        project = SimpleNamespace(title='첫 제목', revision=3)
        class Episodes:
            def get_project(self, _): return project
            def list_rules(self, _): return rules
            def list_episodes(self, _): return chapters
        class Characters:
            def __init__(self, _): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def list_characters(self, _): return chars
        with patch('ai_novel_factory.auto_novel_run.CharacterStore', Characters):
            baseline = _auto_author_source_stamp(Episodes(), 'local.sqlite', 'book', 2)
            self.assertEqual(baseline[2], ((1, 1),))
            project.revision += 1
            self.assertEqual(baseline, _auto_author_source_stamp(Episodes(), 'local.sqlite', 'book', 2))
            project.title = '변경한 제목'
            self.assertNotEqual(baseline, _auto_author_source_stamp(Episodes(), 'local.sqlite', 'book', 2))
            project.title = '첫 제목'
            chars[0].goal = '다른 목표'
            self.assertNotEqual(baseline, _auto_author_source_stamp(Episodes(), 'local.sqlite', 'book', 2))


if __name__ == '__main__':
    unittest.main()
