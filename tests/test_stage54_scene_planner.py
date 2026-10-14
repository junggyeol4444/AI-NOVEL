import unittest
from dataclasses import replace
from ai_novel_factory.episode_planner import EpisodePlan
from ai_novel_factory.scene_planner import plan_scenes, validate_scene_plans
from ai_novel_factory.planning import PlanningError


class ScenePlannerTests(unittest.TestCase):
    def setUp(self):
        self.episode = EpisodePlan(2, 1, '검토', (), (), '', (), '')

    def test_default_three(self):
        scenes = plan_scenes(self.episode)
        self.assertEqual([s.scene_number for s in scenes], [1, 2, 3])
        self.assertTrue(validate_scene_plans(self.episode, scenes))

    def test_custom_count(self):
        self.assertEqual(len(plan_scenes(self.episode, 1)), 1)

    def test_empty_slots_no_invented_content(self):
        s = plan_scenes(self.episode)[0]
        self.assertEqual((s.location, s.characters, s.goal, s.conflict), ('', (), '', ''))
        self.assertEqual(s.status, 'DRAFT_REQUIRES_USER_APPROVAL')

    def test_deterministic(self):
        self.assertEqual(plan_scenes(self.episode), plan_scenes(self.episode))

    def test_reject_invalid_counts(self):
        for count in (0, -1, True, 101, 1.5):
            with self.subTest(count=count), self.assertRaises(PlanningError):
                plan_scenes(self.episode, count)

    def test_reject_invalid_maximum(self):
        with self.assertRaises(PlanningError):
            plan_scenes(self.episode, maximum=True)

    def test_reject_invalid_episode(self):
        with self.assertRaises(PlanningError):
            plan_scenes(replace(self.episode, episode_number=0))

    def test_detect_wrong_episode(self):
        scenes = plan_scenes(self.episode)
        self.assertFalse(validate_scene_plans(self.episode, (replace(scenes[0], episode_number=1),) + scenes[1:]))

    def test_detect_duplicate_or_gap(self):
        scenes = plan_scenes(self.episode)
        self.assertFalse(validate_scene_plans(self.episode, (scenes[0], scenes[0], scenes[2])))

    def test_details_required(self):
        scenes = plan_scenes(self.episode, 1)
        self.assertFalse(validate_scene_plans(self.episode, scenes, require_details=True))
        filled = replace(scenes[0], location='광장', characters=('주인공',), goal='단서 확보', conflict='경비 방해')
        self.assertTrue(validate_scene_plans(self.episode, (filled,), require_details=True))

    def test_reject_bad_field_type(self):
        scenes = plan_scenes(self.episode, 1)
        self.assertFalse(validate_scene_plans(self.episode, (replace(scenes[0], characters=['인물']),)))

    def test_empty_collection_invalid(self):
        self.assertFalse(validate_scene_plans(self.episode, ()))
