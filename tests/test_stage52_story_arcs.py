"""Stage 52 acceptance: every episode belongs to exactly one Story Arc."""
import unittest
from dataclasses import replace
from ai_novel_factory.planning import PlanningInput, PlanningError, draft_premise
from ai_novel_factory.story_arcs import plan_story_arcs, validate_arc_coverage


class StoryArcTests(unittest.TestCase):
    def setUp(self):
        self.spec = PlanningInput('판타지', '독창적 소재', 250, '긴장', ('참고작 원문 비밀',))

    def test_coverage_250(self):
        p = plan_story_arcs(self.spec)
        self.assertTrue(validate_arc_coverage(p))
        self.assertEqual((p.arcs[0].start_episode, p.arcs[-1].end_episode), (1, 250))
        self.assertEqual(sum(a.end_episode-a.start_episode+1 for a in p.arcs), 250)

    def test_explicit_arc_count(self):
        p = plan_story_arcs(self.spec, 6)
        self.assertEqual(len(p.arcs), 6)
        self.assertTrue(validate_arc_coverage(p))
        self.assertLessEqual(max(a.end_episode-a.start_episode for a in p.arcs), 42)

    def test_single_episode(self):
        p = plan_story_arcs(PlanningInput('SF', '우주', 1, '밝음'))
        self.assertEqual((p.arcs[0].start_episode, p.arcs[0].end_episode), (1, 1))
        self.assertTrue(validate_arc_coverage(p))

    def test_premise_input(self):
        self.assertEqual(plan_story_arcs(self.spec), plan_story_arcs(draft_premise(self.spec)))

    def test_bad_counts(self):
        for n in (0, -1, 251, True, 1.1, '3'):
            with self.subTest(n=n), self.assertRaises(PlanningError):
                plan_story_arcs(self.spec, n)

    def test_invalid_premise(self):
        with self.assertRaises(PlanningError):
            plan_story_arcs(replace(draft_premise(self.spec), episode_count=True))

    def test_no_reference_leak(self):
        p = plan_story_arcs(self.spec)
        self.assertNotIn('비밀', str(p))
        self.assertEqual(p.status, 'DRAFT_REQUIRES_USER_APPROVAL')

    def test_determinism(self):
        self.assertEqual(plan_story_arcs(self.spec, 4), plan_story_arcs(self.spec, 4))

    def test_detect_gap_overlap_and_wrong_number(self):
        p = plan_story_arcs(self.spec, 3)
        a = p.arcs
        for bad in (replace(a[1], start_episode=a[1].start_episode + 1),
                    replace(a[1], start_episode=a[1].start_episode - 1),
                    replace(a[1], number=4)):
            self.assertFalse(validate_arc_coverage(replace(p, arcs=(a[0], bad, a[2]))))

    def test_detect_truncated_plan(self):
        p = plan_story_arcs(self.spec, 3)
        self.assertFalse(validate_arc_coverage(replace(p, arcs=p.arcs[:-1])))
