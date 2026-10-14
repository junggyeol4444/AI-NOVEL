"""Stage 60 integration / acceptance: real planning modules, SQLite and privacy."""
from dataclasses import replace
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory.planning import PlanningInput, PlanningError
from ai_novel_factory.planning_pipeline import build_planning_preview
from ai_novel_factory.story_arcs import validate_arc_coverage
from ai_novel_factory.episode_planner import validate_episode_plans, plan_episodes
from ai_novel_factory.scene_planner import validate_scene_plans
from ai_novel_factory.episode_context import ContextFact
from ai_novel_factory.scene_vectors import SceneVector
from ai_novel_factory.database.episodes import EpisodeStore, EpisodeError
from ai_novel_factory.desktop.plot_editor_model import PlotEditorSession
from ai_novel_factory.database.reference_catalog import ReferenceCatalog
from ai_novel_factory.database.pattern_usage import PatternUsageStore, PatternUsageRecord
from ai_novel_factory.references.element_selection import ElementSelection, SelectedElement, FEATURE_LABELS


class PlanningPipelineTests(unittest.TestCase):
    def setUp(self):
        self.spec = PlanningInput('판타지', '우리만의 소재', 7, '긴장', ('참고작_비공개_식별자',))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'episodes.db'
        self.store = EpisodeStore(self.db)
        self.addCleanup(self.store.close)
        self.pid = self.store.create_project('고유 작품').project_id
        self.other = self.store.create_project('다른 작품').project_id
        self.store.create_episode(self.pid, 1)
        self.store.update_episode(self.pid, 1, expected_revision=1, summary='새벽에 일어난 우리 사건', draft='비공개 초고 문장')
        self.store.create_episode(self.pid, 2)
        self.store.update_episode(self.pid, 2, expected_revision=1, summary='우리 사건 후속')
        self.store.create_episode(self.pid, 4)
        self.store.update_episode(self.pid, 4, expected_revision=1, summary='미래 회차 유출 금지')
        self.store.create_episode(self.other, 1)
        self.store.update_episode(self.other, 1, expected_revision=1, summary='다른 작품 기밀 사건')
        self.facts = (ContextFact(self.pid, 'timeline', 'e1', '연표 정보', episode_start=1),
                      ContextFact(self.pid, 'novel_bible', 'b1', '고유한 규칙'),
                      ContextFact(self.pid, 'character', 'future', '비밀', episode_start=4))

    def build(self, **kwargs):
        values = dict(spec=self.spec, project_id=self.pid, episode_number=3,
                      facts=self.facts)
        values.update(kwargs)
        return build_planning_preview(**values)

    def test_end_to_end_51_through_55(self):
        result = self.build(arc_count=2, scene_count=4)
        self.assertEqual(result.premise.episode_count, 7)
        self.assertTrue(validate_arc_coverage(result.arcs))
        self.assertTrue(validate_episode_plans(result.arcs, plan_episodes(result.arcs)))
        self.assertEqual(result.episode.episode_number, 3)
        self.assertEqual(result.episode.arc_number, 1)
        self.assertTrue(validate_scene_plans(result.episode, result.scenes))
        self.assertEqual(len(result.scenes), 4)
        self.assertEqual([s.scene_number for s in result.scenes], [1, 2, 3, 4])
        self.assertEqual([f.source for f in result.context.facts], ['novel_bible', 'timeline'])
        self.assertEqual(result.status, 'DRAFT_REQUIRES_USER_APPROVAL')
        self.assertIsNone(result.pattern)

    def test_no_implicit_writes(self):
        before = self.store.get_project(self.pid).revision
        before_eps = self.store.list_episodes(self.pid)
        self.build(history_store=self.store, history_query='사건')
        self.assertEqual(self.store.get_project(self.pid).revision, before)
        self.assertEqual(self.store.list_episodes(self.pid), before_eps)

    def test_history_57_and_vector_56_together(self):
        vectors = (SceneVector(self.pid, 1, 1, (1., 0., 0.), '우리 과거 장면'),
                   SceneVector(self.pid, 4, 1, (1., 0., 0.), '미래 장면'),
                   SceneVector(self.other, 1, 1, (1., 0., 0.), '다른 작품 장면'))
        result = self.build(history_store=self.store, history_query='사건',
                            vectors=vectors, query_vector=(1., 0., 0.))
        self.assertEqual([(x.episode, x.field) for x in result.history], [(2, 'summary'), (1, 'summary')])
        self.assertEqual([(x.episode_number, x.scene_number) for x in result.similar_scenes], [(1, 1)])
        self.assertNotIn('비공개 초고', repr(result))
        self.assertNotIn('미래 회차 유출', repr(result))
        self.assertNotIn('다른 작품 기밀', repr(result))
        self.assertNotIn('참고작_비공개_식별자', repr(result))

    def test_stage59_explicit_editor_save_then_search(self):
        session = PlotEditorSession()
        self.addCleanup(session.close)
        projects = session.open_existing(self.db)
        self.assertIn((self.pid, '고유 작품'), projects)
        old = self.store.get_episode(self.pid, 2)
        self.assertEqual(old.plot, '')
        session.load(self.pid, 2)
        session.save_plot('사용자가 직접 저장한 계획')
        session.add_scene('장소=서재 / 인물=주인공 / 목표=탐색 / 갈등=시간')
        with EpisodeStore(self.db) as reopened:
            snapshot = reopened.snapshot(self.pid, 2)
            self.assertEqual(snapshot.episode.plot, '사용자가 직접 저장한 계획')
            self.assertEqual(len(snapshot.scenes), 1)
            self.assertEqual(snapshot.episode.draft, '')
            self.assertEqual(snapshot.episode.final_text, '')
            self.assertEqual(self.build(history_store=reopened, history_query='후속').history[0].episode, 2)
        self.assertEqual(len(self.build().scenes), 3)

    def test_read_only_preview_does_not_store_ai_content(self):
        result = self.build()
        self.assertEqual(result.episode.origin, 'DETERMINISTIC_STRUCTURE_NOT_AI')
        self.assertEqual(result.origin, 'OFFLINE_RULE_BASED_PREVIEW_NOT_AI')
        self.assertEqual(self.store.list_episodes(self.pid)[-1].episode, 4)

    def test_deterministic_across_calls(self):
        self.assertEqual(self.build(), self.build())

    def test_no_network_connections(self):
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('external connection')):
            self.assertEqual(self.build().episode.episode_number, 3)

    def test_invalid_project_rejected(self):
        for pid in ('', ' ' * 2, 42, 'x' * 129):
            with self.subTest(pid=pid), self.assertRaises(PlanningError):
                self.build(project_id=pid)

    def test_invalid_episode_rejected(self):
        for episode in (0, -1, True, 8, 1.0):
            with self.subTest(episode=episode), self.assertRaises(PlanningError):
                self.build(episode_number=episode)

    def test_invalid_arc_or_scene_configuration_rejected(self):
        for config in ({'arc_count': 8}, {'arc_count': 0}, {'scene_count': 0}, {'scene_count': 101}):
            with self.subTest(config=config), self.assertRaises(PlanningError):
                self.build(**config)

    def test_project_data_mix_fails_closed(self):
        with self.assertRaises(PlanningError):
            self.build(facts=self.facts + (ContextFact(self.other, 'novel_bible', 'x', '기밀'),))

    def test_reference_source_rejected(self):
        with self.assertRaises(PlanningError):
            self.build(facts=(ContextFact(self.pid, 'reference_novel', 'x', '원문'),))

    def test_context_capacity_fails_closed(self):
        with self.assertRaises(PlanningError):
            self.build(maximum_facts=1)

    def test_history_requires_pair(self):
        with self.assertRaises(PlanningError):
            self.build(history_store=self.store)
        with self.assertRaises(PlanningError):
            self.build(history_query='사건')

    def test_vector_requires_pair(self):
        with self.assertRaises(PlanningError):
            self.build(vectors=())
        with self.assertRaises(PlanningError):
            self.build(query_vector=(1., 0., 0.))

    def test_invalid_vector_no_silent_fallback(self):
        with self.assertRaises(PlanningError):
            self.build(vectors=(), query_vector=(0., 0., 0.))

    def test_pattern_unapproved_rejected(self):
        with self.assertRaises(PlanningError):
            self.build(selection=self._selection())

    def _selection(self):
        return ElementSelection('fantasy', 'equal', ('dialogue_ratio',), 3, 30.,
                                (SelectedElement('dialogue_ratio', FEATURE_LABELS['dialogue_ratio'], .4),))

    def test_pattern_requires_project_authorization(self):
        with self.assertRaises(PlanningError):
            self.build(selection=self._selection(), usage_id='a' * 32,
                       usage_store='not-a-store')

    def test_mismatched_pattern_or_invalid_record_rejected(self):
        with self.assertRaises(PlanningError):
            self.build(selection=self._selection(), usage_id='a' * 32,
                       usage_store='not-a-store', pattern_project_authorized=True)

    def test_real_sqlite_pattern_usage_and_stale_recheck(self):
        from ai_novel_factory.database.genre_patterns import GenrePatternStore
        from ai_novel_factory.database.element_selections import ElementSelectionStore
        from ai_novel_factory.references.profile_pipeline import import_reference_profile

        ref_db = Path(self.tmp.name) / 'reference.db'
        with ReferenceCatalog(ref_db) as catalog:
            genres = GenrePatternStore(catalog)
            for number in range(3):
                source = Path(self.tmp.name) / f'synthetic{number}.txt'
                source.write_text('제1화\n\n' + ('한 사람이 움직였다. 전혀 다른 일이 시작되었다. ' * (15 + number))
                                  + '\n\n제2화\n\n' + ('다음 날 다시 계획했다. ' * 14), encoding='utf-8')
                imported = import_reference_profile(source, catalog=catalog)
                genres.assign(imported.reference.reference_id, 'fantasy')
            genres.build('fantasy')
            selections = ElementSelectionStore(catalog)
            selected = selections.save('fantasy', ['dialogue_ratio'])
            usage_store = PatternUsageStore(catalog)
            usage = usage_store.record('fantasy')
            result = self.build(selection=selected, usage_store=usage_store,
                                usage_id=usage.usage_id, pattern_project_authorized=True)
            self.assertEqual(result.pattern.usage_id, usage.usage_id)
            self.assertEqual(result.pattern.episode, result.episode)
            self.assertEqual(result.pattern.canon_facts, result.context.facts)
            self.assertEqual(tuple(n.feature_key for n in result.pattern.notes), ('dialogue_ratio',))
            self.assertEqual(result.pattern.status, result.status)
            # A changed recipe invalidates previously recorded usage, even if the
            # earlier snapshot was once valid: it must be fetched on every call.
            selections.save('fantasy', ['emotion_balance'])
            with self.assertRaises(PlanningError):
                self.build(selection=selected, usage_store=usage_store,
                           usage_id=usage.usage_id, pattern_project_authorized=True)

    def test_original_novel_bible_higher_priority(self):
        result = self.build()
        self.assertEqual(result.context.facts[0].source, 'novel_bible')
        self.assertNotIn('참고작_비공개_식별자', result.premise.title)
        self.assertNotIn('참고작_비공개_식별자', result.premise.world_outline)

    def test_no_published_approval_exposed(self):
        result = self.build()
        self.assertFalse(hasattr(result, 'publication_approved'))
        self.assertIn('APPROVAL', result.status)


if __name__ == '__main__':
    unittest.main()
