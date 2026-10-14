"""Stage 72 offline character knowledge conflict tests."""
import dataclasses
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ai_novel_factory.database.character_knowledge import CharacterKnowledgeStore
from ai_novel_factory.knowledge_checker import (
    KnowledgeUseClaim, KnowledgeCheckerError, check_character_knowledge,
    check_episode_knowledge,
)


class KnowledgeCheckerTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'knowledge.sqlite'
        self.store = CharacterKnowledgeStore(self.path)
        self.addCleanup(self.store.close)
        self.project = self.store.create_project('주인공의 이야기').project_id
        self.other_project = self.store.create_project('별개의 이야기').project_id
        self.hero = self.store.create_character(self.project, name='주인공',
            personality='신중함', goal='탐구', speech_style='짧게', secret='절대 공개하지 않는 비밀').character_id
        self.rival = self.store.create_character(self.project, name='동료',
            personality='명랑함', goal='친구 돕기', speech_style='반말').character_id
        self.fact = self.store.create_fact(self.project, '숨겨진 비밀 지도가 있다').fact_id
        self.other_fact = self.store.create_fact(self.other_project, '상관 없는 사실').fact_id
        self.text = '주인공이 비밀 지도를 알고 있다고 말한다.'
        self.start = self.text.index('비밀 지도')
        self.claim = KnowledgeUseClaim(self.hero, self.fact, self.start,
                                       self.start + len('비밀 지도'), '비밀 지도')

    _DEFAULT = object()

    def check(self, episode=3, text=None, claims=_DEFAULT, **kwargs):
        return check_character_knowledge(self.store, self.project, episode,
            self.text if text is None else text,
            (self.claim,) if claims is self._DEFAULT else claims, **kwargs)

    def event(self, episode, knows=True, character=None, fact=None):
        self.store.save_event(self.project, character or self.hero,
            fact or self.fact, episode, knows=knows)

    def test_unrecorded_knowledge_flagged(self):
        r = self.check()
        self.assertEqual(r.findings[0].code, 'NOT_RECORDED')
        self.assertFalse(r.passed_declared_uses)

    def test_future_knowledge_flagged(self):
        self.event(5)
        r = self.check(4)
        self.assertEqual(r.findings[0].code, 'NOT_YET_LEARNED')
        self.assertIsNone(r.findings[0].effective_episode)

    def test_learning_effective_at_same_episode(self):
        self.event(5)
        self.assertTrue(self.check(5).passed_declared_uses)

    def test_earlier_episode_cannot_know_later_fact(self):
        self.event(5)
        self.assertFalse(self.check(1).passed_declared_uses)

    def test_knowledge_remains_known(self):
        self.event(1)
        self.assertTrue(self.check(40).passed_declared_uses)

    def test_forgotten_fact_flagged(self):
        self.event(1)
        self.event(2, False)
        finding = self.check(3).findings[0]
        self.assertEqual(finding.code, 'NOT_KNOWN')
        self.assertEqual(finding.effective_episode, 2)

    def test_relearned_fact_allows_use(self):
        self.event(1)
        self.event(2, False)
        self.event(3)
        self.assertTrue(self.check(3).passed_declared_uses)

    def test_explicitly_unknown_is_flagged(self):
        self.event(1, False)
        self.assertEqual(self.check().findings[0].code, 'NOT_KNOWN')

    def test_another_character_does_not_inherit_knowledge(self):
        self.event(1, character=self.rival)
        self.assertEqual(self.check().findings[0].code, 'NOT_RECORDED')

    def test_other_project_cannot_supply_fact(self):
        bad = dataclasses.replace(self.claim, fact_id=self.other_fact)
        with self.assertRaises(KnowledgeCheckerError):
            self.check(claims=(bad,))

    def test_other_project_cannot_supply_character(self):
        foreign = self.store.create_character(self.other_project, name='외부인',
            personality='조용', goal='여행', speech_style='존댓말').character_id
        bad = dataclasses.replace(self.claim, character_id=foreign)
        with self.assertRaises(KnowledgeCheckerError):
            self.check(claims=(bad,))

    def test_missing_character_or_fact_fails_closed(self):
        for key in ('character_id', 'fact_id'):
            with self.subTest(key=key), self.assertRaises(KnowledgeCheckerError):
                self.check(claims=(dataclasses.replace(self.claim, **{key: 'a'*32}),))

    def test_evidence_must_equal_manuscript_span(self):
        for change in ({'evidence': '비밀'}, {'start': self.start+1},
                       {'end': len(self.text)+1}, {'end': self.start},
                       {'start': True}):
            with self.subTest(change=change), self.assertRaises(KnowledgeCheckerError):
                self.check(claims=(dataclasses.replace(self.claim, **change),))

    def test_duplicate_claims_rejected(self):
        with self.assertRaises(KnowledgeCheckerError):
            self.check(claims=(self.claim, self.claim))

    def test_empty_claims_not_full_qc(self):
        r = self.check(claims=())
        self.assertEqual(r.examined_uses, 0)
        self.assertTrue(r.passed_declared_uses)
        self.assertEqual(r.status, 'REQUIRES_HUMAN_REVIEW_NOT_FULL_QC')

    def test_no_plaintext_in_findings_or_report(self):
        r = self.check()
        self.assertNotIn('비밀 지도', repr(r))
        self.assertNotIn('절대 공개하지 않는 비밀', repr(r))
        self.assertEqual(r.manuscript_sha256, sha256(self.text.encode()).hexdigest())
        self.assertEqual(r.findings[0].evidence_sha256, sha256('비밀 지도'.encode()).hexdigest())
        self.assertFalse(r.persisted)
        self.assertFalse(r.publication_approved)

    def test_stale_revision_rejected(self):
        previous = self.store.get_project(self.project).revision
        self.event(1)
        with self.assertRaisesRegex(KnowledgeCheckerError, 'stale'):
            self.check(expected_project_revision=previous)

    def test_current_revision_succeeds(self):
        version = self.store.get_project(self.project).revision
        self.assertEqual(self.check(expected_project_revision=version).project_revision, version)

    def test_revision_change_during_read_rejected(self):
        original = self.store.knowledge_at
        def changes(*args):
            value = original(*args)
            self.event(100)
            return value
        with patch.object(self.store, 'knowledge_at', side_effect=changes):
            with self.assertRaisesRegex(KnowledgeCheckerError, 'changed'):
                self.check()

    def test_checks_multiple_characters_and_facts(self):
        fact2 = self.store.create_fact(self.project, '동료가 알 수 있는 사실').fact_id
        self.event(1)
        self.event(1, character=self.rival, fact=fact2)
        second = KnowledgeUseClaim(self.rival, fact2, self.start,
                                   self.start+len('비밀 지도'), '비밀 지도')
        self.assertEqual(self.check(claims=(self.claim, second)).examined_uses, 2)
        self.assertTrue(self.check(claims=(self.claim, second)).passed_declared_uses)

    def test_invalid_episode_inputs(self):
        for value in (0, -1, 1000001, True, 1.0, '1'):
            with self.subTest(value=value), self.assertRaises(KnowledgeCheckerError):
                self.check(value)

    def test_invalid_claim_collection(self):
        for value in ([], None, [self.claim], tuple([self.claim]*501)):
            with self.subTest(value=type(value)), self.assertRaises(KnowledgeCheckerError):
                self.check(claims=value)

    def test_invalid_manuscript(self):
        for text in ('', '  ', '\ud800', 'a'*1_000_001):
            with self.subTest(length=len(text)), self.assertRaises(KnowledgeCheckerError):
                self.check(text=text)

    def test_invalid_claim_types_and_ids(self):
        for value in ('abc', dataclasses.replace(self.claim, character_id='wrong'),
                      dataclasses.replace(self.claim, fact_id=7)):
            with self.subTest(value=type(value)), self.assertRaises(KnowledgeCheckerError):
                self.check(claims=(value,))

    def test_reopened_sqlite_persists_event_history(self):
        self.event(2)
        self.store.close()
        self.store = CharacterKnowledgeStore(self.path)
        self.addCleanup(self.store.close)
        self.assertEqual(self.check(2).examined_uses, 1)
        self.assertTrue(self.check(2).passed_declared_uses)

    def test_does_not_mutate_existing_database(self):
        before = self.store.get_project(self.project).revision
        self.check()
        self.assertEqual(self.store.get_project(self.project).revision, before)

    def test_preview_adapter_checks_sha_and_approval(self):
        from ai_novel_factory.episode_assembler import EpisodeDraftPreview
        preview = EpisodeDraftPreview(self.project, 3, self.text,
            sha256(self.text.encode()).hexdigest(), (), (), 'offline-mock-v1',
            'DETERMINISTIC_MOCK_NOT_AI')
        self.assertEqual(check_episode_knowledge(self.store, preview, (self.claim,)).examined_uses, 1)
        for altered in (dataclasses.replace(preview, draft='altered'),
                        dataclasses.replace(preview, persisted=True),
                        dataclasses.replace(preview, publication_approved=True),
                        dataclasses.replace(preview, project_id=self.other_project),
                        dataclasses.replace(preview, status='FINAL')):
            with self.subTest(alt=altered.status), self.assertRaises(KnowledgeCheckerError):
                check_episode_knowledge(self.store, altered, (self.claim,))

    def test_preview_adapter_refuses_unapproved_foreign(self):
        from ai_novel_factory.episode_assembler import EpisodeDraftPreview
        preview = EpisodeDraftPreview(self.other_project, 3, self.text,
            sha256(self.text.encode()).hexdigest(), (), (), 'offline-mock-v1',
            'DETERMINISTIC_MOCK_NOT_AI')
        with self.assertRaises(KnowledgeCheckerError):
            check_episode_knowledge(self.store, preview, (self.claim,))

    def test_invalid_revision(self):
        for value in (-1, True, '1', 2**31):
            with self.subTest(value=value), self.assertRaises(KnowledgeCheckerError):
                self.check(expected_project_revision=value)

    def test_unknown_store_rejected(self):
        with self.assertRaises(KnowledgeCheckerError):
            check_character_knowledge(object(), self.project, 1, self.text, (self.claim,))


if __name__ == '__main__':
    unittest.main()
