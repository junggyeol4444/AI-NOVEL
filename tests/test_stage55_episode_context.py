import unittest
from dataclasses import replace
from ai_novel_factory.episode_planner import EpisodePlan
from ai_novel_factory.episode_context import ContextFact, select_episode_context
from ai_novel_factory.planning import PlanningError

class Stage55ContextTests(unittest.TestCase):
    def setUp(self):
        self.ep = EpisodePlan(3, 1, '', ('battle',), ('hero',), '', (), '')
        self.bible = ContextFact('p', 'novel_bible', 'canon', 'Only one sun')
    def choose(self, facts, **kw):
        return select_episode_context('p', self.ep, tuple(facts), **kw)
    def test_canon_first(self):
        result=self.choose([ContextFact('p','timeline','event','Battle'),self.bible]); self.assertEqual(result.facts[0],self.bible)
    def test_empty(self): self.assertEqual(self.choose([]).facts, ())
    def test_active_interval(self):
        self.assertEqual(self.choose([replace(self.bible,episode_start=4)]).facts, ())
        self.assertEqual(self.choose([replace(self.bible,episode_end=3)]).facts,(replace(self.bible,episode_end=3),))
    def test_character_match(self):
        self.assertEqual(len(self.choose([replace(self.bible,character_ids=('hero',))]).facts),1)
        self.assertEqual(len(self.choose([replace(self.bible,character_ids=('other',))]).facts),0)
    def test_event_match(self):
        self.assertEqual(len(self.choose([replace(self.bible,event_ids=('battle',))]).facts),1)
    def test_reference_rejected(self):
        with self.assertRaises(PlanningError): self.choose([replace(self.bible,source='reference_novel')])
    def test_other_project_rejected(self):
        with self.assertRaises(PlanningError): self.choose([replace(self.bible,project_id='q')])
    def test_duplicate_rejected(self):
        with self.assertRaises(PlanningError): self.choose([self.bible,self.bible])
    def test_overflow_fails_closed(self):
        with self.assertRaises(PlanningError): self.choose([self.bible],maximum=0)
        with self.assertRaises(PlanningError): self.choose([self.bible,replace(self.bible,fact_id='b')],maximum=1)
    def test_invalid_bounds(self):
        with self.assertRaises(PlanningError): self.choose([replace(self.bible,episode_end=0)])
    def test_invalid_tag_type(self):
        with self.assertRaises(PlanningError): self.choose([replace(self.bible,character_ids=['hero'])])
    def test_deterministic(self):
        a=ContextFact('p','world','a','World')
        self.assertEqual(self.choose([a,self.bible]),self.choose([self.bible,a]))
