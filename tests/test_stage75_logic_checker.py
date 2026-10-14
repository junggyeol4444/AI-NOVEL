"""Stage 75: reviewer-evidenced logic dependencies, never semantic AI QC."""
from dataclasses import replace
from hashlib import sha256
import unittest

from ai_novel_factory.logic_checker import (
    LogicAction, LogicCheckerError, LogicPremise, check_logic, check_episode_logic,
)
from ai_novel_factory.episode_assembler import EpisodeDraftPreview, SceneSpan


class LogicCheckerTests(unittest.TestCase):
    def setUp(self):
        self.project = 'novel-local-75'
        self.draft = '그녀는 동료를 믿었다. 그는 봉인을 해제했다. 모두 무사히 탈출했다.'
        self.premise_text = '그녀는 동료를 믿었다'
        self.action_text = '그는 봉인을 해제했다'
        self.premise_pos = self.draft.index(self.premise_text)
        self.action_pos = self.draft.index(self.action_text)
        self.premise = LogicPremise(self.project, 'trust', 'MOTIVE', 1, 1,
            self.premise_pos, self.premise_pos + len(self.premise_text), self.premise_text)
        self.action = LogicAction(self.project, 'opening', 'MOTIVE', 2, 1,
            self.action_pos, self.action_pos + len(self.action_text), self.action_text,
            ('trust',))

    def check(self, premises=None, actions=None, **kwargs):
        return check_logic(self.project, 3, self.draft,
            (self.premise,) if premises is None else premises,
            (self.action,) if actions is None else actions, **kwargs)

    def codes(self, premises=None, actions=None):
        return tuple(f.code for f in self.check(premises, actions).findings)

    def test_supported_motive_passes_marked_evidence(self):
        result = self.check()
        self.assertTrue(result.passed_declared_dependencies)
        self.assertEqual((result.examined_actions, result.examined_premises), (1,1))
        self.assertEqual(result.manuscript_sha256, sha256(self.draft.encode()).hexdigest())
        self.assertFalse(result.persisted)
        self.assertFalse(result.publication_approved)
        self.assertIn('NOT_FULL_QC', result.status)

    def test_missing_motivation(self):
        self.assertEqual(self.codes(premises=()), ('NOT_ESTABLISHED',))

    def test_future_motivation_does_not_support_past_action(self):
        self.assertEqual(self.codes(premises=(replace(self.premise,story_step=3),)), ('NOT_YET_ESTABLISHED',))

    def test_same_story_step_is_undecidable(self):
        self.assertEqual(self.codes(premises=(replace(self.premise,story_step=2),)), ('SAME_STEP_UNVERIFIABLE',))

    def test_contradicted_motive(self):
        r = self.check(premises=(replace(self.premise,established=False),))
        self.assertEqual(r.findings[0].code, 'CONTRADICTED_PREMISE')
        self.assertEqual(r.findings[0].premise_sha256, sha256(self.premise_text.encode()).hexdigest())

    def test_ability_use_requires_prior_ability_premise(self):
        a = replace(self.action,kind='ABILITY', required_facts=('seal_power',))
        self.assertEqual(self.codes(actions=(a,)), ('NOT_ESTABLISHED',))
        p = replace(self.premise,kind='ABILITY',fact_key='seal_power')
        self.assertEqual(self.codes(premises=(p,),actions=(a,)), ())

    def test_cause_requires_prior_causal_premise(self):
        a = replace(self.action,kind='CAUSE',required_facts=('trigger',))
        self.assertEqual(self.codes(actions=(a,)), ('NOT_ESTABLISHED',))
        p = replace(self.premise,kind='CAUSE',fact_key='trigger')
        self.assertEqual(self.codes(premises=(p,), actions=(a,)), ())

    def test_resolution_requires_prior_resolution_condition(self):
        a = replace(self.action,kind='RESOLUTION',required_facts=('escape_plan',))
        self.assertEqual(self.codes(actions=(a,)), ('NOT_ESTABLISHED',))
        p = replace(self.premise,kind='RESOLUTION',fact_key='escape_plan')
        self.assertEqual(self.codes(premises=(p,), actions=(a,)), ())

    def test_missing_declared_justification(self):
        self.assertEqual(self.codes(actions=(replace(self.action,required_facts=()),)),
                         ('NO_DECLARED_JUSTIFICATION',))

    def test_coincidence_is_review_flag_not_objective_finding(self):
        r = self.check(actions=(replace(self.action,coincidence=True),))
        self.assertEqual(tuple(f.code for f in r.findings), ('COINCIDENCE_REVIEW',))
        self.assertNotIn(self.action_text, repr(r))

    def test_unsupported_action_with_coincidence_both_reported(self):
        self.assertEqual(self.codes(actions=(replace(self.action,required_facts=(),coincidence=True),)),
                         ('NO_DECLARED_JUSTIFICATION', 'COINCIDENCE_REVIEW'))

    def test_last_chronological_state_wins(self):
        p2 = replace(self.premise, story_step=2, established=False)
        p3 = replace(self.premise, story_step=3, established=True)
        action = replace(self.action, story_step=4)
        self.assertEqual(self.codes(premises=(self.premise,p2,p3), actions=(action,)), ())
        self.assertEqual(self.codes(premises=(self.premise,p2), actions=(action,)),
                         ('CONTRADICTED_PREMISE',))

    def test_conflicting_same_step_evidence_ambiguous(self):
        p2 = replace(self.premise, story_step=2)
        p3 = replace(self.premise,story_step=2,established=False,
                     start=self.action_pos,end=self.action_pos+len(self.action_text),
                     evidence=self.action_text)
        self.assertEqual(self.codes(premises=(p2,p3),actions=(replace(self.action,story_step=4),)),
                         ('AMBIGUOUS_PREMISE',))

    def test_flashback_prose_order_not_assumed_chronology(self):
        # The earlier event can appear later in the prose; story_step is explicit.
        premise = replace(self.premise,start=self.action_pos,
                          end=self.action_pos+len(self.action_text),evidence=self.action_text)
        action = replace(self.action,start=self.premise_pos,
                         end=self.premise_pos+len(self.premise_text),evidence=self.premise_text)
        self.assertEqual(self.codes(premises=(premise,), actions=(action,)), ())

    def test_wrong_kind_same_key_does_not_justify_action(self):
        self.assertEqual(self.codes(premises=(replace(self.premise, kind='ABILITY'),)),
                         ('NOT_ESTABLISHED',))

    def test_multiple_dependencies_and_independent_findings(self):
        a = replace(self.action,required_facts=('trust', 'ability_missing', 'causal_missing'))
        self.assertEqual(self.codes(actions=(a,)), ('NOT_ESTABLISHED', 'NOT_ESTABLISHED'))

    def test_empty_annotations_not_certified_as_full_qc(self):
        r = self.check(premises=(), actions=())
        self.assertTrue(r.passed_declared_dependencies)
        self.assertEqual(r.examined_actions,0)
        self.assertIn('NOT_FULL_QC',r.status)

    def test_cross_project_premise_rejected(self):
        with self.assertRaises(LogicCheckerError):
            self.check(premises=(replace(self.premise,project_id='other'),))

    def test_cross_project_action_rejected(self):
        with self.assertRaises(LogicCheckerError):
            self.check(actions=(replace(self.action,project_id='other'),))

    def test_evidence_mismatch_rejected(self):
        with self.assertRaises(LogicCheckerError):
            self.check(actions=(replace(self.action,evidence='altered'),))

    def test_premise_evidence_mismatch_rejected(self):
        with self.assertRaises(LogicCheckerError):
            self.check(premises=(replace(self.premise,evidence='altered'),))

    def test_bad_manuscript_hash_rejected(self):
        with self.assertRaises(LogicCheckerError):
            self.check(expected_manuscript_sha256='0'*64)

    def test_good_manuscript_hash(self):
        self.assertTrue(self.check(expected_manuscript_sha256=sha256(self.draft.encode()).hexdigest()).passed_declared_dependencies)

    def test_bad_project_identifier(self):
        with self.assertRaises(LogicCheckerError):
            check_logic('invalid\nproject',1,self.draft,(),())

    def test_duplicate_action_identifier_rejected(self):
        with self.assertRaises(LogicCheckerError):
            self.check(actions=(self.action,self.action))

    def test_duplicate_premise_annotation_rejected(self):
        with self.assertRaises(LogicCheckerError):
            self.check(premises=(self.premise,self.premise))

    def test_duplicate_dependency_rejected(self):
        with self.assertRaises(LogicCheckerError):
            self.check(actions=(replace(self.action,required_facts=('trust','trust')),))

    def test_bad_kind_rejected(self):
        with self.assertRaises(LogicCheckerError):
            self.check(actions=(replace(self.action,kind='MAGIC'),))

    def test_bad_action_id_rejected(self):
        with self.assertRaises(LogicCheckerError):
            self.check(actions=(replace(self.action,action_id='../bad'),))

    def test_bad_fact_key_rejected(self):
        with self.assertRaises(LogicCheckerError):
            self.check(premises=(replace(self.premise,fact_key='../bad'),))

    def test_bad_scene_number_rejected(self):
        with self.assertRaises(LogicCheckerError):
            self.check(actions=(replace(self.action,scene_number=101),))

    def test_zero_and_boolean_story_steps_rejected(self):
        for bad in (0,True,-1,'2',1_000_001):
            with self.subTest(bad=bad), self.assertRaises(LogicCheckerError):
                self.check(actions=(replace(self.action,story_step=bad),))

    def test_bool_offsets_rejected(self):
        with self.assertRaises(LogicCheckerError):
            self.check(actions=(replace(self.action,start=True),))

    def test_bool_established_rejected_if_not_bool(self):
        with self.assertRaises(LogicCheckerError):
            self.check(premises=(replace(self.premise,established=1),))

    def test_bad_coincidence_flag_rejected(self):
        with self.assertRaises(LogicCheckerError):
            self.check(actions=(replace(self.action,coincidence='yes'),))

    def test_action_requirement_limit(self):
        a = replace(self.action,required_facts=tuple(f'f{i}' for i in range(33)))
        with self.assertRaises(LogicCheckerError): self.check(actions=(a,))

    def test_premise_limit(self):
        with self.assertRaises(LogicCheckerError): self.check(premises=(self.premise,)*1001)

    def test_action_limit(self):
        with self.assertRaises(LogicCheckerError): self.check(actions=(self.action,)*501)

    def test_invalid_surrogate_unicode_rejected(self):
        with self.assertRaises(LogicCheckerError):
            check_logic(self.project,1,'bad\ud800',(),())

    def test_findings_do_not_echo_manuscript(self):
        r = self.check(premises=())
        self.assertNotIn(self.draft, repr(r))
        self.assertNotIn(self.action_text,repr(r))
        self.assertEqual(r.findings[0].start,self.action_pos)

    def test_draft_preview_adapter(self):
        scene = SceneSpan(1,0,len(self.draft),sha256(self.draft.encode()).hexdigest(),'p'*64,('rule',))
        preview = EpisodeDraftPreview(self.project,3,self.draft,
            sha256(self.draft.encode()).hexdigest(),(scene,),('rule',),
            'offline-mock-v1','DETERMINISTIC_MOCK_NOT_AI')
        self.assertTrue(check_episode_logic(preview,(self.premise,),(self.action,)).passed_declared_dependencies)
        with self.assertRaises(LogicCheckerError):
            check_episode_logic(replace(preview,draft=self.draft+'!'),(self.premise,),(self.action,))
        with self.assertRaises(LogicCheckerError):
            check_episode_logic(replace(preview,persisted=True),(self.premise,),(self.action,))
        with self.assertRaises(LogicCheckerError):
            check_episode_logic(replace(preview,publication_approved=True),(self.premise,),(self.action,))
        with self.assertRaises(LogicCheckerError):
            check_episode_logic(replace(preview,scenes=(replace(scene,draft_sha256='0'*64),)),
                                (self.premise,),(self.action,))

    def test_adapter_rejects_cross_scene_span(self):
        first = '동기'
        second = '행동'
        text=first+'\n\n'+second
        s1=SceneSpan(1,0,2,sha256(first.encode()).hexdigest(),'p'*64,())
        s2=SceneSpan(2,4,6,sha256(second.encode()).hexdigest(),'p'*64,())
        preview=EpisodeDraftPreview(self.project,3,text,sha256(text.encode()).hexdigest(),
            (s1,s2),('r',),'offline-mock-v1','DETERMINISTIC_MOCK_NOT_AI')
        p=LogicPremise(self.project,'reason','MOTIVE',1,1,0,2,'동기')
        a=LogicAction(self.project,'act','MOTIVE',2,1,4,6,'행동',('reason',))
        with self.assertRaises(LogicCheckerError):
            check_episode_logic(preview,(p,),(a,))
        self.assertTrue(check_episode_logic(preview,(p,),(replace(a,scene_number=2),)).passed_declared_dependencies)


if __name__ == '__main__':
    unittest.main()
