"""Stage 58 regression tests: opt-in, provenance, canon precedence and privacy."""
import unittest
from dataclasses import replace
from unittest.mock import patch
import socket

from ai_novel_factory.pattern_application import apply_reference_patterns
from ai_novel_factory.episode_planner import EpisodePlan
from ai_novel_factory.episode_context import EpisodeContext, ContextFact
from ai_novel_factory.references.element_selection import (
    ElementSelection, SelectedElement, FEATURE_KEYS, FEATURE_LABELS,
)
from ai_novel_factory.database.pattern_usage import PatternUsageRecord
from ai_novel_factory.planning import PlanningError


class Stage58PatternApplicationTests(unittest.TestCase):
    def setUp(self):
        self.episode = EpisodePlan(7, 2, '우리 작품의 목표', ('자체 사건',), ('주인공',),
                                   '두려움에서 희망', ('고유 복선',), '고유한 Hook')
        self.bible = ContextFact('work-1', 'novel_bible', 'rule', '우리 작품 설정이 우선한다')
        self.timeline = ContextFact('work-1', 'timeline', 'event', '우리 작품 사건')
        self.context = EpisodeContext('work-1', 7, (self.bible, self.timeline))
        keys = ('dialogue_ratio', 'cliffhanger_episode_rate', 'event_cue_density_per_1000')
        self.selection = ElementSelection('fantasy', 'equal', keys, 3, 40.0, (
            SelectedElement('dialogue_ratio', FEATURE_LABELS['dialogue_ratio'], .4),
            SelectedElement('cliffhanger_episode_rate', FEATURE_LABELS['cliffhanger_episode_rate'], .7),
            SelectedElement('event_cue_density_per_1000', FEATURE_LABELS['event_cue_density_per_1000'], 6.2),
        ))
        self.usage = PatternUsageRecord('a' * 32, 'fantasy', 'fantasy', 'equal', keys,
                                        None, '2026-10-13T00:00:00.000000+00:00', True)

    def apply(self, **changes):
        return apply_reference_patterns(changes.get('episode', self.episode),
                                        changes.get('context', self.context),
                                        changes.get('selection', self.selection),
                                        changes.get('usage', self.usage))

    def test_selected_metrics_are_attached_to_specific_episode(self):
        output = self.apply()
        self.assertEqual(output.episode.episode_number, 7)
        self.assertEqual(tuple(note.feature_key for note in output.notes), self.selection.selected_keys)
        self.assertEqual(tuple(note.plan_field for note in output.notes),
                         ('scene_dialogue', 'ending_hook', 'required_events'))

    def test_canon_and_plot_are_preserved_not_overridden(self):
        out = self.apply()
        self.assertEqual(out.canon_facts[0], self.bible)
        self.assertIs(out.episode, self.episode)
        self.assertEqual(out.episode.ending_hook, '고유한 Hook')
        self.assertEqual(out.episode.required_events, ('자체 사건',))
        self.assertEqual(out.status, 'DRAFT_REQUIRES_USER_APPROVAL')

    def test_reference_secrets_never_appear(self):
        out = self.apply()
        self.assertNotIn('참고작 고유 표현 카나리아', repr(out))
        self.assertTrue(all(n.review_question for n in out.notes))
        self.assertTrue(all(n.label == FEATURE_LABELS[n.feature_key] for n in out.notes))

    def test_reject_stale_usage(self):
        with self.assertRaises(PlanningError):
            self.apply(usage=replace(self.usage, current=False))

    def test_reject_unrecorded_usage(self):
        with self.assertRaises(PlanningError):
            self.apply(usage=None)

    def test_reject_cross_genre_usage_until_supported(self):
        with self.assertRaises(PlanningError):
            self.apply(usage=replace(self.usage, pattern_genre='romance'))

    def test_reject_mismatched_keys(self):
        with self.assertRaises(PlanningError):
            self.apply(usage=replace(self.usage, selected_keys=('dialogue_ratio',)))

    def test_reject_mismatched_weighting(self):
        with self.assertRaises(PlanningError):
            self.apply(selection=replace(self.selection, weighting='characters'))

    def test_reject_mismatched_genre(self):
        with self.assertRaises(PlanningError):
            self.apply(selection=replace(self.selection, genre='romance'))

    def test_reject_future_episode_context(self):
        with self.assertRaises(PlanningError):
            self.apply(context=replace(self.context, episode_number=8))

    def test_reject_other_project_fact(self):
        with self.assertRaises(PlanningError):
            self.apply(context=replace(self.context, facts=(replace(self.bible, project_id='other'),)))

    def test_reject_reference_source(self):
        with self.assertRaises(PlanningError):
            self.apply(context=replace(self.context, facts=(replace(self.bible, source='reference_novel'),)))

    def test_reject_non_draft_episode(self):
        with self.assertRaises(PlanningError):
            self.apply(episode=replace(self.episode, status='FINAL'))

    def test_reject_too_concentrated(self):
        with self.assertRaises(PlanningError):
            self.apply(selection=replace(self.selection, max_share_percent=60.1))

    def test_reject_nonfinite_values(self):
        for invalid in (float('nan'), float('inf'), -1, True):
            with self.subTest(invalid=invalid), self.assertRaises(PlanningError):
                self.apply(selection=replace(self.selection, elements=(
                    replace(self.selection.elements[0], observed_mean=invalid),
                    *self.selection.elements[1:])))

    def test_reject_corrupt_labels(self):
        with self.assertRaises(PlanningError):
            self.apply(selection=replace(self.selection, elements=(
                replace(self.selection.elements[0], label='reference raw prose'),
                *self.selection.elements[1:])))

    def test_only_one_selected_feature(self):
        one = replace(self.selection, selected_keys=('dialogue_ratio',),
                      elements=(self.selection.elements[0],))
        usage = replace(self.usage, selected_keys=('dialogue_ratio',))
        self.assertEqual(len(self.apply(selection=one, usage=usage).notes), 1)

    def test_no_network(self):
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('network')):
            self.assertEqual(len(self.apply().notes), 3)

    def test_deterministic_no_mutation(self):
        original = self.episode
        self.assertEqual(self.apply(), self.apply())
        self.assertEqual(original, self.episode)


if __name__ == '__main__':
    unittest.main()
