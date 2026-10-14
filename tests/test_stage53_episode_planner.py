import unittest
from dataclasses import replace
from ai_novel_factory.planning import PlanningInput, PlanningError
from ai_novel_factory.story_arcs import plan_story_arcs
from ai_novel_factory.episode_planner import plan_episodes, validate_episode_plans


class EpisodePlannerTests(unittest.TestCase):
    def setUp(self):
        self.arcs = plan_story_arcs(PlanningInput('판타지', '소재', 67, '긴장', ('참고작 비밀',)), 3)

    def test_full_coverage(self):
        plans = plan_episodes(self.arcs)
        self.assertEqual(len(plans), 67)
        self.assertTrue(validate_episode_plans(self.arcs, plans))

    def test_arc_boundaries(self):
        plans = plan_episodes(self.arcs)
        for arc in self.arcs.arcs:
            self.assertEqual(plans[arc.start_episode - 1].arc_number, arc.number)
            self.assertEqual(plans[arc.end_episode - 1].arc_number, arc.number)

    def test_empty_story_fields_require_review(self):
        p = plan_episodes(self.arcs)[0]
        self.assertEqual(p.required_events, ())
        self.assertEqual(p.status, 'DRAFT_REQUIRES_USER_APPROVAL')
        self.assertNotIn('비밀', str(p))

    def test_deterministic(self):
        self.assertEqual(plan_episodes(self.arcs), plan_episodes(self.arcs))

    def test_reject_invalid_arc(self):
        broken = replace(self.arcs, episode_count=68)
        with self.assertRaises(PlanningError):
            plan_episodes(broken)

    def test_reject_limit(self):
        with self.assertRaises(PlanningError):
            plan_episodes(self.arcs, maximum=66)

    def test_reject_invalid_limit(self):
        with self.assertRaises(PlanningError):
            plan_episodes(self.arcs, maximum=True)

    def test_detect_duplicate(self):
        plans = plan_episodes(self.arcs)
        self.assertFalse(validate_episode_plans(self.arcs, (plans[0],) + plans[:-1]))

    def test_detect_wrong_arc(self):
        plans = plan_episodes(self.arcs)
        self.assertFalse(validate_episode_plans(self.arcs, (replace(plans[0], arc_number=2),) + plans[1:]))

    def test_detect_truncated(self):
        self.assertFalse(validate_episode_plans(self.arcs, plan_episodes(self.arcs)[:-1]))
