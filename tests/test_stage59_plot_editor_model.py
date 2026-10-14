"""Stage 59: local episode/scene plot editor session integration tests."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_novel_factory.desktop.plot_editor_model import PlotEditorError, PlotEditorSession
from ai_novel_factory.database.episodes import EpisodeError, EpisodeStore


class PlotEditorSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'bible.sqlite'
        with EpisodeStore(self.path) as db:
            self.a = db.create_project('작품 A').project_id
            self.b = db.create_project('작품 B').project_id
            db.create_episode(self.a, 1, plot='원래 회차 플롯')
            db.create_episode(self.a, 2, plot='2화 목표')
            db.create_episode(self.b, 1, plot='B 플롯')
        self.editor = PlotEditorSession()
        self.addCleanup(self.editor.close)

    def _open(self):
        self.editor.open_existing(self.path)
        return self.editor.load(self.a, 1)

    def test_open_only_existing(self):
        with self.assertRaises(PlotEditorError):
            self.editor.open_existing(self.path.parent / 'missing.db')
        self.assertFalse((self.path.parent / 'missing.db').exists())

    def test_reject_empty_existing_file_without_creating_schema(self):
        target = self.path.parent / 'empty.db'
        target.touch()
        with self.assertRaises(PlotEditorError):
            self.editor.open_existing(target)
        self.assertEqual(target.stat().st_size, 0)

    def test_reject_non_sqlite_file(self):
        target = self.path.parent / 'fake.db'
        target.write_text('not sqlite')
        with self.assertRaises(PlotEditorError):
            self.editor.open_existing(target)
        self.assertEqual(target.read_text(), 'not sqlite')

    def test_reject_remote_like_or_symlink(self):
        with self.assertRaises(PlotEditorError):
            self.editor.open_existing('//server/share/db')
        link = self.path.parent / 'link.db'
        try:
            link.symlink_to(self.path)
        except (OSError, NotImplementedError):
            self.skipTest('symlink not available')
        with self.assertRaises(PlotEditorError):
            self.editor.open_existing(link)

    def test_list_projects_and_episodes(self):
        items = self.editor.open_existing(self.path)
        self.assertEqual([title for _, title in items], ['작품 A', '작품 B'])
        self.assertEqual(self.editor.list_episodes(self.a), (1, 2))
        self.assertEqual(self.editor.list_episodes(self.b), (1,))

    def test_requires_explicit_open_and_load(self):
        with self.assertRaises(PlotEditorError):
            self.editor.save_plot('no')
        self.editor.open_existing(self.path)
        with self.assertRaises(PlotEditorError):
            self.editor.add_scene('no')

    def test_load_no_write(self):
        view = self._open()
        self.assertEqual(view.plot, '원래 회차 플롯')
        self.assertEqual(view.revision, 1)
        with EpisodeStore(self.path) as db:
            self.assertEqual(db.get_episode(self.a, 1).revision, 1)

    def test_explicit_plot_save(self):
        self._open()
        view = self.editor.save_plot('새 플롯\n수동 확정 전')
        self.assertEqual(view.plot, '새 플롯\n수동 확정 전')
        self.assertEqual(view.revision, 2)
        with EpisodeStore(self.path) as db:
            ep = db.get_episode(self.a, 1)
            self.assertEqual(ep.plot, '새 플롯\n수동 확정 전')
            self.assertEqual(ep.final_text, '')
            self.assertEqual(ep.draft, '')

    def test_scene_add_edit_delete(self):
        self._open()
        view = self.editor.add_scene('광장 / 단서 조사')
        self.assertEqual(len(view.scenes), 1)
        sid = view.scenes[0][0]
        self.assertEqual(view.scenes[0][1:], (1, '광장 / 단서 조사'))
        view = self.editor.save_scene(sid, '강당 / 갈등과 목표')
        self.assertEqual(view.scenes[0][2], '강당 / 갈등과 목표')
        view = self.editor.delete_scene(sid)
        self.assertEqual(view.scenes, ())
        with EpisodeStore(self.path) as db:
            self.assertEqual(db.list_scenes(self.a, 1), ())

    def test_multiple_scenes_positions(self):
        self._open()
        self.editor.add_scene('1')
        self.editor.add_scene('2')
        view = self.editor.current
        self.assertEqual([s[1] for s in view.scenes], [1, 2])
        self.editor.delete_scene(view.scenes[0][0])
        after = self.editor.add_scene('new')
        self.assertEqual([s[1] for s in after.scenes], [1, 2])

    def test_stale_episode_save_prevents_lost_update(self):
        self._open()
        with EpisodeStore(self.path) as second:
            second.update_episode(self.a, 1, expected_revision=1, plot='다른 창 변경')
        with self.assertRaises(EpisodeError):
            self.editor.save_plot('오래된 데이터')
        with EpisodeStore(self.path) as db:
            self.assertEqual(db.get_episode(self.a, 1).plot, '다른 창 변경')
        self.assertEqual(self.editor.current.plot, '원래 회차 플롯')

    def test_stale_scene_save_prevents_lost_update(self):
        self._open()
        sid = self.editor.add_scene('원래 장면').scenes[0][0]
        with EpisodeStore(self.path) as second:
            second.update_scene(self.a, 1, sid, expected_revision=2, text='다른 사용자')
        with self.assertRaises(EpisodeError):
            self.editor.save_scene(sid, '덮어쓰기 금지')
        with EpisodeStore(self.path) as db:
            self.assertEqual(db.get_scene(self.a, 1, sid).text, '다른 사용자')

    def test_cross_project_separation(self):
        self._open()
        self.editor.save_plot('A 전용')
        self.editor.load(self.b, 1)
        self.assertEqual(self.editor.current.plot, 'B 플롯')
        with EpisodeStore(self.path) as db:
            self.assertEqual(db.get_episode(self.b, 1).plot, 'B 플롯')

    def test_cross_project_scene_not_editable(self):
        self._open()
        sid = self.editor.add_scene('A 장면').scenes[0][0]
        self.editor.load(self.b, 1)
        with self.assertRaises(PlotEditorError):
            self.editor.save_scene(sid, 'B가 쓰기')

    def test_create_episode_explicit(self):
        self.editor.open_existing(self.path)
        view = self.editor.create_episode(self.a, 3)
        self.assertEqual(view.episode_number, 3)
        self.assertEqual(view.plot, '')
        self.assertEqual(self.editor.list_episodes(self.a), (1, 2, 3))

    def test_duplicate_episode_rejected(self):
        self.editor.open_existing(self.path)
        with self.assertRaises(EpisodeError):
            self.editor.create_episode(self.a, 1)

    def test_invalid_text_not_saved(self):
        self._open()
        with self.assertRaises(EpisodeError):
            self.editor.save_plot('\x00')
        with EpisodeStore(self.path) as db:
            self.assertEqual(db.get_episode(self.a, 1).plot, '원래 회차 플롯')

    def test_invalid_scene_id_not_saved(self):
        self._open()
        with self.assertRaises(PlotEditorError):
            self.editor.save_scene('f' * 32, '잘못된 장면')

    def test_close_resets_connection_and_state(self):
        self._open()
        self.editor.close()
        self.assertFalse(self.editor.connected)
        self.assertIsNone(self.editor.current)
        with self.assertRaises(PlotEditorError):
            self.editor.save_plot('text')

    def test_open_new_db_resets_previous_selection(self):
        self._open()
        other_path = self.path.parent / 'other.db'
        with EpisodeStore(other_path) as db:
            db.create_project('다른 작품')
        self.editor.open_existing(other_path)
        self.assertIsNone(self.editor.current)


if __name__ == '__main__':
    unittest.main()
