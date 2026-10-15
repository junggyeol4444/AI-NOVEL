"""Stage 74: human-labelled foreshadow actions/status vs local Novel Bible."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from ai_novel_factory.database.foreshadow import ForeshadowStore
from ai_novel_factory.foreshadow_checker import (
    ForeshadowCheckerError, ForeshadowClaim, check_foreshadowing,
    check_episode_foreshadowing,
)


class ForeshadowCheckerTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'test.sqlite'
        self.store = ForeshadowStore(self.path)
        self.addCleanup(self.store.close)
        self.project = self.store.create_project('검토 대상 소설').project_id
        self.other = self.store.create_project('다른 작품').project_id
        self.thread = self.store.create_thread(self.project, title='잊힌 편지', episode=2,
                                                note='비밀스러운 내용').thread_id
        self.text = '편지가 발견되었다. 편지를 다시 본다. 편지의 진상이 밝혀진다.'
        self.span = '편지가 발견되었다'
        self.start = self.text.index(self.span)
        self.base = ForeshadowClaim(self.thread, self.start,
                                   self.start + len(self.span), self.span,
                                   claimed_action='INSTALL')

    def add(self, episode, action, thread=None, project=None):
        project = project or self.project
        thread = thread or self.thread
        rev = self.store.get_thread(project, thread).revision
        return self.store.add_event(project, thread, episode=episode,
            action=action, expected_revision=rev)

    _DEFAULT = object()

    def check(self, episode=2, claims=_DEFAULT, text=None, **kwargs):
        return check_foreshadowing(self.store, self.project, episode,
            self.text if text is None else text,
            (self.base,) if claims is self._DEFAULT else claims, **kwargs)

    def test_install_at_install_episode(self):
        r = self.check()
        self.assertTrue(r.passed_declared_claims)
        self.assertEqual(r.examined_claims, 1)
        self.assertEqual(r.findings, ())

    def test_no_install_event_before_episode(self):
        self.assertEqual(self.check(1).findings[0].code, 'ACTION_NOT_RECORDED')

    def test_install_cannot_be_claimed_later(self):
        self.assertEqual(self.check(3).findings[0].code, 'ACTION_NOT_RECORDED')

    def test_missing_revisit(self):
        claim = replace(self.base, claimed_action='REVISIT')
        self.assertEqual(self.check(3, (claim,)).findings[0].code, 'ACTION_NOT_RECORDED')

    def test_revisit_at_episode_succeeds(self):
        self.add(4, 'REVISIT')
        claim = replace(self.base, claimed_action='REVISIT')
        self.assertTrue(self.check(4, (claim,)).passed_declared_claims)

    def test_wrong_action_when_other_action_recorded(self):
        self.add(4, 'REVISIT')
        claim = replace(self.base, claimed_action='RESOLVE')
        self.assertEqual(self.check(4, (claim,)).findings[0].code, 'ACTION_CONFLICT')

    def test_resolve_exact_episode_passes(self):
        self.add(5, 'RESOLVE')
        claim = replace(self.base, claimed_action='RESOLVE')
        self.assertTrue(self.check(5, (claim,)).passed_declared_claims)

    def test_abandon_exact_episode_passes(self):
        self.add(4, 'ABANDON')
        claim = replace(self.base, claimed_action='ABANDON')
        self.assertTrue(self.check(4, (claim,)).passed_declared_claims)

    def test_terminal_action_not_present_later(self):
        self.add(4, 'RESOLVE')
        claim = replace(self.base, claimed_action='RESOLVE')
        self.assertEqual(self.check(5, (claim,)).findings[0].code, 'ACTION_NOT_RECORDED')

    def test_open_status_at_install_and_later(self):
        status = replace(self.base, claimed_action=None, claimed_status='OPEN')
        self.assertTrue(self.check(2, (status,)).passed_declared_claims)
        self.assertTrue(self.check(4, (status,)).passed_declared_claims)

    def test_status_before_install_flagged(self):
        status = replace(self.base, claimed_action=None, claimed_status='OPEN')
        r = self.check(1, (status,))
        self.assertEqual((r.findings[0].code, r.findings[0].actual_status),
                         ('NOT_INSTALLED', 'NOT_INSTALLED'))

    def test_developing_status(self):
        self.add(3, 'REVISIT')
        claim = replace(self.base, claimed_action=None, claimed_status='DEVELOPING')
        self.assertTrue(self.check(3, (claim,)).passed_declared_claims)
        self.assertTrue(self.check(7, (claim,)).passed_declared_claims)

    def test_status_conflict_after_revisit(self):
        self.add(3, 'REVISIT')
        claim = replace(self.base, claimed_action=None, claimed_status='OPEN')
        result = self.check(3, (claim,)).findings[0]
        self.assertEqual((result.code, result.actual_status),
                         ('STATUS_CONFLICT', 'DEVELOPING'))

    def test_resolved_status_persists(self):
        self.add(4, 'RESOLVE')
        claim = replace(self.base, claimed_action=None, claimed_status='RESOLVED')
        self.assertTrue(self.check(4, (claim,)).passed_declared_claims)
        self.assertTrue(self.check(20, (claim,)).passed_declared_claims)

    def test_abandoned_status_persists(self):
        self.add(4, 'ABANDON')
        claim = replace(self.base, claimed_action=None, claimed_status='ABANDONED')
        self.assertTrue(self.check(20, (claim,)).passed_declared_claims)

    def test_same_episode_install_and_revisit(self):
        self.add(2, 'REVISIT')
        first = self.base
        second = replace(self.base, claimed_action='REVISIT')
        status = replace(self.base, claimed_action=None, claimed_status='DEVELOPING')
        self.assertTrue(self.check(2, (first, second, status)).passed_declared_claims)

    def test_same_episode_revisit_and_resolve_status_terminal(self):
        self.add(2, 'REVISIT')
        self.add(2, 'RESOLVE')
        status = replace(self.base, claimed_action=None, claimed_status='RESOLVED')
        self.assertTrue(self.check(2, (status,)).passed_declared_claims)
        open_claim = replace(status, claimed_status='OPEN')
        self.assertEqual(self.check(2, (open_claim,)).findings[0].code, 'STATUS_CONFLICT')

    def test_backfilled_event_chronology(self):
        self.add(8, 'RESOLVE')
        self.add(3, 'REVISIT')
        claim = replace(self.base, claimed_action=None, claimed_status='DEVELOPING')
        self.assertTrue(self.check(7, (claim,)).passed_declared_claims)

    def test_cross_project_thread_fails_closed(self):
        foreign = self.store.create_thread(self.other, title='외부', episode=2).thread_id
        with self.assertRaises(ForeshadowCheckerError):
            self.check(claims=(replace(self.base, thread_id=foreign),))

    def test_missing_thread_fails_closed(self):
        with self.assertRaises(ForeshadowCheckerError):
            self.check(claims=(replace(self.base, thread_id='f'*32),))

    def test_invalid_span_or_evidence(self):
        changes = ({'start': True}, {'start': -1}, {'end': len(self.text)+1},
                   {'end': self.start}, {'evidence': '변조'}, {'evidence': ' '},
                   {'evidence': 'z'*4001}, {'start': self.start + 1})
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ForeshadowCheckerError):
                self.check(claims=(replace(self.base, **change),))

    def test_invalid_episode(self):
        for episode in (0, -1, True, 1.0, '3', 1_000_001):
            with self.subTest(episode=episode), self.assertRaises(ForeshadowCheckerError):
                self.check(episode)

    def test_invalid_action_and_status(self):
        changes = ({'claimed_action': None}, {'claimed_status': 'OPEN'},
                   {'claimed_action': 'PAYOFF'}, {'claimed_action': 1},
                   {'claimed_action': None, 'claimed_status': 'NOT_INSTALLED'},
                   {'claimed_action': None, 'claimed_status': True})
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ForeshadowCheckerError):
                self.check(claims=(replace(self.base, **change),))

    def test_invalid_claim_collection(self):
        for claims in (None, [], [self.base], tuple([self.base] * 501)):
            with self.subTest(claims=type(claims)), self.assertRaises(ForeshadowCheckerError):
                self.check(claims=claims)

    def test_duplicate_claim_rejected(self):
        with self.assertRaises(ForeshadowCheckerError):
            self.check(claims=(self.base, self.base))

    def test_different_claims_same_span_are_allowed(self):
        claim = replace(self.base, claimed_action=None, claimed_status='OPEN')
        self.assertTrue(self.check(claims=(self.base, claim)).passed_declared_claims)

    def test_invalid_manuscript(self):
        for text in ('', ' ', '\ud800', 'a' * 1_000_001):
            with self.subTest(length=len(text)), self.assertRaises(ForeshadowCheckerError):
                self.check(text=text)

    def test_no_claims_is_not_full_quality_guarantee(self):
        result = self.check(claims=())
        self.assertTrue(result.passed_declared_claims)
        self.assertEqual(result.examined_claims, 0)
        self.assertEqual(result.status, 'REQUIRES_HUMAN_REVIEW_NOT_FULL_QC')

    def test_report_redacts_story_text_and_notes(self):
        claim = replace(self.base, claimed_action='RESOLVE')
        r = self.check(3, (claim,))
        self.assertNotIn('잊힌 편지', repr(r))
        self.assertNotIn('비밀스러운 내용', repr(r))
        self.assertNotIn(self.span, repr(r))
        self.assertEqual(r.manuscript_sha256, sha256(self.text.encode()).hexdigest())
        self.assertEqual(r.findings[0].evidence_sha256, sha256(self.span.encode()).hexdigest())
        self.assertFalse(r.persisted)
        self.assertFalse(r.publication_approved)

    def test_rejects_stale_revision(self):
        old = self.store.get_project(self.project).revision
        self.add(3, 'REVISIT')
        with self.assertRaisesRegex(ForeshadowCheckerError, 'stale'):
            self.check(expected_project_revision=old)

    def test_current_revision_succeeds(self):
        rev = self.store.get_project(self.project).revision
        self.assertEqual(self.check(expected_project_revision=rev).project_revision, rev)

    def test_rejects_invalid_revision_type(self):
        for value in (True, -1, 1.5, '1'):
            with self.subTest(value=value), self.assertRaises(ForeshadowCheckerError):
                self.check(expected_project_revision=value)

    def test_detects_revision_change_during_read(self):
        original = self.store.get_at
        changed = [False]
        def interfering(*args):
            val = original(*args)
            if not changed[0]:
                self.add(8, 'REVISIT')
                changed[0] = True
            return val
        with patch.object(self.store, 'get_at', side_effect=interfering):
            with self.assertRaisesRegex(ForeshadowCheckerError, 'changed'):
                self.check()

    def test_corrupt_transitions_fail_closed(self):
        self.add(4, 'RESOLVE')
        # Bypass the normal store validation and insert an illegal action.
        with self.store._db:
            self.store._db.execute('''INSERT INTO bible_foreshadow_events VALUES
                (?, ?, ?, 5, 3, 'REVISIT', '', '2026-01-01T00:00:00+00:00')''',
                (self.project, self.thread, 'f'*32))
        with self.assertRaises(ForeshadowCheckerError):
            self.check()

    def test_invalid_store_and_project(self):
        for store, project in ((object(), self.project), (self.store, 'wrong')):
            with self.subTest(store=type(store)), self.assertRaises(ForeshadowCheckerError):
                check_foreshadowing(store, project, 2, self.text, (self.base,))

    def test_no_database_changes(self):
        before = self.store.get_project(self.project).revision
        history_before = self.store.history(self.project, self.thread)
        self.check()
        self.assertEqual(self.store.history(self.project, self.thread), history_before)
        self.assertEqual(self.store.get_project(self.project).revision, before)

    def test_episode_preview_adapter_accepts_draft_only(self):
        from ai_novel_factory.episode_assembler import EpisodeDraftPreview
        preview = EpisodeDraftPreview(self.project, 2, self.text,
            sha256(self.text.encode()).hexdigest(), (), (), 'offline-mock-v1',
            'DETERMINISTIC_MOCK_NOT_AI')
        r = check_episode_foreshadowing(self.store, preview, (self.base,))
        self.assertTrue(r.passed_declared_claims)
        self.assertEqual(r.episode_number, 2)

    def test_episode_preview_rejects_tampering_or_approval(self):
        from ai_novel_factory.episode_assembler import EpisodeDraftPreview
        preview = EpisodeDraftPreview(self.project, 2, self.text,
            sha256(self.text.encode()).hexdigest(), (), (), 'offline-mock-v1',
            'DETERMINISTIC_MOCK_NOT_AI')
        for change in ({'draft': '다른 내용'}, {'persisted': True},
                       {'publication_approved': True}, {'status': 'APPROVED'},
                       {'draft_sha256': '0' * 64}):
            with self.subTest(change=change), self.assertRaises(ForeshadowCheckerError):
                check_episode_foreshadowing(self.store, replace(preview, **change), (self.base,))

    def test_episode_preview_rejects_foreign_project(self):
        from ai_novel_factory.episode_assembler import EpisodeDraftPreview
        preview = EpisodeDraftPreview(self.other, 2, self.text,
            sha256(self.text.encode()).hexdigest(), (), (), 'offline-mock-v1',
            'DETERMINISTIC_MOCK_NOT_AI')
        with self.assertRaises(ForeshadowCheckerError):
            check_episode_foreshadowing(self.store, preview, (self.base,))

    def test_episode_preview_rejects_nonpreview(self):
        with self.assertRaises(ForeshadowCheckerError):
            check_episode_foreshadowing(self.store, object(), (self.base,))

    def test_store_reopens_with_identical_findings(self):
        old = self.check(3, (replace(self.base, claimed_action='RESOLVE'),))
        self.store.close()
        self.store = ForeshadowStore(self.path)
        self.addCleanup(self.store.close)
        new = self.check(3, (replace(self.base, claimed_action='RESOLVE'),))
        self.assertEqual(old, new)


if __name__ == '__main__':
    unittest.main()
