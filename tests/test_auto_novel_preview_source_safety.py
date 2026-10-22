"""Disposable SQLite tests: reject stale or cancelled whole-story AI previews.

No external model, user manuscript, network or publication is accessed.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ai_novel_factory.auto_novel_run import AutoNovelRunError, run_auto_novel
from ai_novel_factory.database.episodes import EpisodeStore
from ai_novel_factory.local_models import LocalExecutableProvider, SceneDraftResult


class PreviewDraftSourceSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'preview-only.sqlite'
        with EpisodeStore(self.path) as store:
            self.project_id = store.create_project('가상 단편 소설').project_id
            for key, value in (
                ('genre', '판타지'), ('subject', '등불 마을의 비밀'),
                ('mood', '긴장감'), ('target_episodes', '30'),
            ):
                store.save_rule(self.project_id, key, value)
        # The runtime enforces exact LocalExecutableProvider identity.
        # No model process is ever started in these tests.
        self.provider = object.__new__(LocalExecutableProvider)

    def _run(self, *, should_stop=None):
        return run_auto_novel(self.path, self.project_id, self.provider,
                              through_episode=1, target_chars=500,
                              scenes_per_episode=1, should_stop=should_stop)

    @staticmethod
    def _result(request):
        return SceneDraftResult(request.project_id, request.episode_number,
                                request.scene_number, '검증 전 가상 전체 줄거리 초안',
                                'local-executable-v1')

    def _assert_preview_missing(self):
        with EpisodeStore(self.path) as db:
            self.assertNotIn('ai_story_outline_preview',
                             [rule.key for rule in db.list_rules(self.project_id)])

    def test_bible_change_during_generation_rejects_preview_without_rollback_of_edit(self):
        def synthetic_result(request, _provider):
            with EpisodeStore(self.path) as other:
                old = other.get_rule(self.project_id, 'mood')
                other.save_rule(self.project_id, 'mood', '차분함',
                                expected_revision=old.revision)
            return self._result(request)
        with patch('ai_novel_factory.auto_novel_run.draft_scene',
                   side_effect=synthetic_result):
            with self.assertRaises(AutoNovelRunError):
                self._run()
        self._assert_preview_missing()
        with EpisodeStore(self.path) as db:
            self.assertEqual(db.get_rule(self.project_id, 'mood').value, '차분함')
            self.assertEqual(db.list_episodes(self.project_id), ())

    def test_existing_later_chapter_edit_during_generation_rejects_whole_story_preview(self):
        with EpisodeStore(self.path) as db:
            db.create_episode(self.project_id, 5, plot='저장된 5화')
        def synthetic_result(request, _provider):
            with EpisodeStore(self.path) as other:
                old = other.get_episode(self.project_id, 5)
                other.update_episode(self.project_id, 5,
                                     expected_revision=old.revision,
                                     plot='작가가 수정한 5화')
            return self._result(request)
        with patch('ai_novel_factory.auto_novel_run.draft_scene',
                   side_effect=synthetic_result):
            with self.assertRaises(AutoNovelRunError):
                self._run()
        self._assert_preview_missing()
        with EpisodeStore(self.path) as db:
            self.assertEqual(db.get_episode(self.project_id, 5).plot,
                             '작가가 수정한 5화')

    def test_stop_after_generation_before_persistence_keeps_sqlite_unchanged(self):
        stop = [False]
        def synthetic_result(request, _provider):
            stop[0] = True
            return self._result(request)
        with patch('ai_novel_factory.auto_novel_run.draft_scene',
                   side_effect=synthetic_result):
            report = self._run(should_stop=lambda: stop[0])
        self.assertTrue(report.stopped)
        self.assertEqual(report.created_episodes, ())
        self._assert_preview_missing()
        with EpisodeStore(self.path) as db:
            self.assertEqual(db.list_episodes(self.project_id), ())

    def test_unchanged_preview_can_be_saved_only_as_unapproved_rule(self):
        calls = [0]
        def synthetic_result(request, _provider):
            calls[0] += 1
            if calls[0] == 1:
                return self._result(request)
            raise InterruptedError()
        with patch('ai_novel_factory.auto_novel_run.draft_scene',
                   side_effect=synthetic_result):
            report = self._run()
        self.assertTrue(report.stopped)
        with EpisodeStore(self.path) as db:
            self.assertEqual(db.list_episodes(self.project_id), ())
            self.assertEqual(
                db.get_rule(self.project_id, 'ai_story_outline_preview').value,
                '검증 전 가상 전체 줄거리 초안')


if __name__ == '__main__':
    unittest.main()
