"""Stage 89 / ANF-REQ-067: local review/consent gate, no publisher."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import sqlite3
import tempfile
import unittest

from ai_novel_factory.database.reference_catalog import ReferenceCatalog
from ai_novel_factory.database.episodes import EpisodeStore
from ai_novel_factory.database.foreshadow import ForeshadowStore
from ai_novel_factory.ending_audit import EndingReport
from ai_novel_factory.manuscript_versions import ManuscriptVersionStore
from ai_novel_factory.publication_approval import (
    ApprovalChallenge, EpisodeSimilarityInput, PublicationApprovalError,
    PublicationApprovalStore, PublicationReviewEvidence,
)
from ai_novel_factory.reference_similarity_checker import (
    ReferenceMaterial, TextSpan, check_reference_similarity,
)
from ai_novel_factory.reference_similarity_records import ReferenceSimilarityReviewStore

TEXT1 = '푸른 호수 위를 가로지르는 작은 배는 새로운 항구를 향했다.'
TEXT2 = '바람을 따라 걷던 여행자는 오래된 길 끝에서 문을 발견했다.'
SOURCE = '모래 언덕 사이로 달리는 긴 기차는 먼 기착지를 향해 이동했다.'
BEATS1 = ('setup', 'reversal', 'climax', 'hook')
BEATS2 = ('inciting', 'setback', 'resolution', 'transition')


class PublicationApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'novel.db'
        self.store = PublicationApprovalStore(self.path)
        self.addCleanup(self.store.close)
        self.catalog = ReferenceCatalog(':memory:')
        self.addCleanup(self.catalog.close)
        self.similarity = ReferenceSimilarityReviewStore(':memory:')
        self.addCleanup(self.similarity.close)
        self.pid = self.store.create_project('독립적인 소설').project_id
        with ManuscriptVersionStore(self.path) as db:
            for number, text in enumerate((TEXT1, TEXT2), 1):
                ep = db.create_episode(self.pid, number)
                db.save_version(self.pid, number, text, kind='FINAL', expected_revision=ep.revision)

    def evidence(self, *, no_refs=True, report=None, **kwargs):
        if report is None:
            report = self.store.inspect_ending(self.pid, 2,
                foreshadow_inventory_reviewed=True,
                conflict_inventory_reviewed=True,
                timeline_inventory_reviewed=True)
        args = dict(ending_report=report, reference_catalog=self.catalog,
            similarity_store=self.similarity, no_references_confirmed=no_refs,
            foreshadow_inventory_reviewed=True,
            conflict_inventory_reviewed=True,
            timeline_inventory_reviewed=True)
        args.update(kwargs)
        return PublicationReviewEvidence(**args)

    def begin(self, **kwargs):
        ev = self.evidence(**kwargs)
        return self.store.begin_review(self.pid, ev), ev

    def approve(self, ticket, ev):
        return self.store.decide(self.pid, ticket.request.request_id, ev,
                                 decision='APPROVE', confirmation=ticket.confirmation('APPROVE'))

    def test_pending_is_not_authorization(self):
        ticket, ev = self.begin()
        self.assertEqual(ticket.request.status, 'PENDING')
        with self.assertRaises(PublicationApprovalError):
            self.store.require_current_publication_approval(self.pid, ticket.request.request_id, ev)

    def test_approve_explicit_then_gate(self):
        ticket, ev = self.begin()
        self.assertEqual(self.approve(ticket, ev).status, 'APPROVED')
        gate = self.store.require_current_publication_approval(self.pid, ticket.request.request_id, ev)
        self.assertEqual(gate.status, 'LOCAL_APPROVAL_CURRENT_NOT_PUBLISHED')
        self.assertFalse(gate.identity_authenticated)
        self.assertFalse(gate.publication_executed)
        self.assertEqual(self.store.list_events(self.pid, ticket.request.request_id),
                         ('REQUESTED', 'APPROVED'))

    def test_reject_is_not_approval(self):
        ticket, ev = self.begin()
        rejected = self.store.decide(self.pid, ticket.request.request_id, ev,
            decision='REJECT', confirmation=ticket.confirmation('REJECT'))
        self.assertEqual(rejected.status, 'REJECTED')
        with self.assertRaises(PublicationApprovalError):
            self.store.require_current_publication_approval(self.pid, ticket.request.request_id, ev)

    def test_revoke_invalidates_gate(self):
        ticket, ev = self.begin()
        self.approve(ticket, ev)
        request_id = ticket.request.request_id
        with self.assertRaises(PublicationApprovalError):
            self.store.revoke(self.pid, request_id, confirmation='yes')
        self.assertEqual(self.store.revoke(self.pid, request_id,
            confirmation=f'REVOKE {request_id}').status, 'REVOKED')
        with self.assertRaises(PublicationApprovalError):
            self.store.require_current_publication_approval(self.pid, request_id, ev)

    def test_reject_does_not_allow_reapprove(self):
        ticket, ev = self.begin()
        self.store.decide(self.pid, ticket.request.request_id, ev,
            decision='REJECT', confirmation=ticket.confirmation('REJECT'))
        with self.assertRaises(PublicationApprovalError):
            self.approve(ticket, ev)

    def test_approve_twice_rejected(self):
        ticket, ev = self.begin()
        self.approve(ticket, ev)
        with self.assertRaises(PublicationApprovalError):
            self.approve(ticket, ev)

    def test_wrong_challenge_fails_closed(self):
        ticket, ev = self.begin()
        for text in ('APPROVE', 'yes', 'APPROVE '+ticket.request.request_id+' '+('a'*24),
                     ticket.confirmation('REJECT'), ticket.confirmation('APPROVE')+' '):
            with self.subTest(text=text[:10]), self.assertRaises(PublicationApprovalError):
                self.store.decide(self.pid, ticket.request.request_id, ev,
                                  decision='APPROVE', confirmation=text)
        self.assertEqual(self.store.get_request(self.pid, ticket.request.request_id).status, 'PENDING')

    def test_wrong_decision_type(self):
        ticket, ev = self.begin()
        for value in (True, 1, None, 'PUBLISH'):
            with self.subTest(value=value), self.assertRaises(PublicationApprovalError):
                self.store.decide(self.pid, ticket.request.request_id, ev,
                                  decision=value, confirmation=ticket.confirmation('APPROVE'))

    def test_confirmation_secret_not_in_database(self):
        ticket, ev = self.begin()
        self.approve(ticket, ev)
        dump = '\n'.join(self.store._db.iterdump())
        self.assertNotIn(ticket.code, dump)
        review_rows = self.store._db.execute('SELECT * FROM bible_publication_review').fetchall()
        self.assertNotIn(TEXT1, repr([tuple(row) for row in review_rows]))

    def test_challenge_redacted_repr(self):
        ticket, ev = self.begin()
        self.assertNotIn(ticket.code, repr(ticket))
        self.assertFalse(ticket.request.identity_authenticated)

    def test_snapshot_sha64(self):
        ticket, ev = self.begin()
        self.assertEqual(len(ticket.request.manifest_sha256), 64)
        int(ticket.request.manifest_sha256, 16)

    def test_new_request_supersedes_old(self):
        old, ev = self.begin()
        self.approve(old, ev)
        new = self.store.begin_review(self.pid, ev)
        self.assertEqual(self.store.get_request(self.pid, old.request.request_id).status, 'SUPERSEDED')
        with self.assertRaises(PublicationApprovalError):
            self.store.require_current_publication_approval(self.pid, old.request.request_id, ev)
        self.assertEqual(new.request.status, 'PENDING')

    def test_project_isolation(self):
        ticket, ev = self.begin()
        other = self.store.create_project('다른 작품').project_id
        with self.assertRaises(PublicationApprovalError):
            self.store.get_request(other, ticket.request.request_id)
        with self.assertRaises(PublicationApprovalError):
            self.store.decide(other, ticket.request.request_id, ev,
                decision='APPROVE', confirmation=ticket.confirmation('APPROVE'))

    def test_reopen_persists_approval(self):
        ticket, ev = self.begin()
        self.approve(ticket, ev)
        with PublicationApprovalStore(self.path) as other:
            self.assertEqual(other.get_request(self.pid, ticket.request.request_id).status, 'APPROVED')
            self.assertEqual(other.require_current_publication_approval(
                self.pid, ticket.request.request_id, ev).request_id, ticket.request.request_id)

    def test_stale_after_final_version_change(self):
        ticket, ev = self.begin()
        self.approve(ticket, ev)
        with ManuscriptVersionStore(self.path) as db:
            ep = db.get_episode(self.pid, 2)
            db.save_version(self.pid, 2, '다른 내용', kind='REVISION', expected_revision=ep.revision)
        with self.assertRaises(PublicationApprovalError):
            self.store.require_current_publication_approval(self.pid, ticket.request.request_id, ev)

    def test_stale_after_project_rule_change(self):
        ticket, ev = self.begin()
        self.approve(ticket, ev)
        self.store.save_rule(self.pid, 'genre', 'fantasy')
        with self.assertRaises(PublicationApprovalError):
            self.store.require_current_publication_approval(self.pid, ticket.request.request_id, ev)

    def test_stale_before_approval_blocks(self):
        ticket, ev = self.begin()
        self.store.save_rule(self.pid, 'genre', 'fantasy')
        with self.assertRaises(PublicationApprovalError):
            self.approve(ticket, ev)
        self.assertEqual(self.store.get_request(self.pid, ticket.request.request_id).status, 'PENDING')

    def test_missing_final_candidate(self):
        with ManuscriptVersionStore(self.path) as db:
            ep = db.get_episode(self.pid, 2)
            db.save_version(self.pid, 2, '새 초고', kind='DRAFT', expected_revision=ep.revision)
        with self.assertRaises(PublicationApprovalError):
            self.store.begin_review(self.pid, self.evidence())

    def test_untracked_final_candidate_blocks(self):
        with EpisodeStore(self.path) as db:
            ep = db.get_episode(self.pid, 2)
            db.update_episode(self.pid, 2, expected_revision=ep.revision, final_text='무단 교체')
        with self.assertRaises(PublicationApprovalError):
            self.store.begin_review(self.pid, self.evidence())

    def test_missing_version_blocks(self):
        with sqlite3.connect(self.path) as db:
            db.execute('DELETE FROM bible_manuscript_versions WHERE project_id=? AND episode=2', (self.pid,))
        with self.assertRaises(PublicationApprovalError):
            self.store.begin_review(self.pid, self.evidence())

    def test_missing_inventory_review_blocks(self):
        with self.assertRaises(PublicationApprovalError):
            self.store.begin_review(self.pid, replace(self.evidence(),
                conflict_inventory_reviewed=False))

    def test_incomplete_ending_blocks(self):
        with ForeshadowStore(self.path) as db:
            db.create_thread(self.pid, title='미회수', episode=1)
        ev = self.evidence()
        self.assertFalse(ev.ending_report.ready_for_human_review)
        with self.assertRaises(PublicationApprovalError):
            self.store.begin_review(self.pid, ev)

    def test_wrong_ending_project_blocks(self):
        ev = self.evidence()
        with self.assertRaises(PublicationApprovalError):
            self.store.begin_review(self.pid, replace(ev,
                ending_report=replace(ev.ending_report, project_id='f'*32)))

    def test_forged_ready_flag_fails(self):
        ev = self.evidence()
        with self.assertRaises(PublicationApprovalError):
            self.store.begin_review(self.pid, replace(ev,
                ending_report=replace(ev.ending_report, evidence_digest='0'*64)))

    def test_no_reference_confirmation_required(self):
        with self.assertRaises(PublicationApprovalError):
            self.store.begin_review(self.pid, self.evidence(no_refs=False))

    def test_reference_registration_invalidates_no_reference_claim(self):
        self.register_reference()
        with self.assertRaises(PublicationApprovalError):
            self.store.begin_review(self.pid, self.evidence())

    def register_reference(self):
        ref = self.catalog.register(file_name='source.txt', source_format='txt',
            byte_count=len(SOURCE.encode()), sha256=sha256(SOURCE.encode()).hexdigest())
        self.catalog.change_status(ref.reference_id, 'analyzing')
        self.catalog.change_status(ref.reference_id, 'analyzed')
        return ref

    def with_reference_evidence(self, *, record=True):
        ref = self.register_reference()
        material = ReferenceMaterial(ref.reference_id, ref.sha256, SOURCE,
                                     (TextSpan(0, len(SOURCE)),), BEATS2)
        anns = []
        for number, text in enumerate((TEXT1, TEXT2), 1):
            ann = EpisodeSimilarityInput(number, (TextSpan(0, len(text)),), BEATS1)
            anns.append(ann)
            if record:
                result = check_reference_similarity(self.pid, number, text,
                    references=(material,), draft_scenes=ann.scenes,
                    draft_beats=ann.beats, required_reference_ids=(ref.reference_id,),
                    catalog=self.catalog)
                self.assertTrue(result.passed_checked_scope)
                self.similarity.record(result)
        return self.evidence(no_refs=False, references=(material,), annotations=tuple(anns))

    def test_reference_checks_required_and_current(self):
        ev = self.with_reference_evidence()
        ticket = self.store.begin_review(self.pid, ev)
        self.approve(ticket, ev)
        self.assertEqual(self.store.require_current_publication_approval(
            self.pid, ticket.request.request_id, ev).status,
            'LOCAL_APPROVAL_CURRENT_NOT_PUBLISHED')

    def test_reference_missing_receipt_blocks(self):
        ev = self.with_reference_evidence(record=False)
        with self.assertRaises(PublicationApprovalError):
            self.store.begin_review(self.pid, ev)

    def test_reference_missing_annotation_blocks(self):
        ev = self.with_reference_evidence()
        with self.assertRaises(PublicationApprovalError):
            self.store.begin_review(self.pid, replace(ev, annotations=ev.annotations[:1]))

    def test_reference_wrong_source_blocks(self):
        ev = self.with_reference_evidence()
        bad = replace(ev.references[0], text=SOURCE+' 새로운 내용')
        with self.assertRaises(PublicationApprovalError):
            self.store.begin_review(self.pid, replace(ev, references=(bad,)))

    def test_reference_change_after_approval_blocks(self):
        ev = self.with_reference_evidence()
        ticket = self.store.begin_review(self.pid, ev)
        self.approve(ticket, ev)
        self.catalog.change_status(ev.references[0].reference_id, 'analyzing')
        with self.assertRaises(PublicationApprovalError):
            self.store.require_current_publication_approval(self.pid, ticket.request.request_id, ev)

    def test_reference_missing_current_inputs_at_gate_blocks(self):
        ev = self.with_reference_evidence()
        ticket = self.store.begin_review(self.pid, ev)
        self.approve(ticket, ev)
        with self.assertRaises(PublicationApprovalError):
            self.store.require_current_publication_approval(self.pid, ticket.request.request_id,
                replace(ev, references=(), no_references_confirmed=True))

    def test_reference_report_with_review_status_blocks(self):
        ev = self.with_reference_evidence()
        # Change stored receipt to review; require_current_clear_review must reject it.
        with self.similarity._db:
            self.similarity._db.execute("UPDATE similarity_review SET status='review'")
        with self.assertRaises(PublicationApprovalError):
            self.store.begin_review(self.pid, ev)

    def test_approval_has_no_implicit_publish_side_effect(self):
        ticket, ev = self.begin()
        self.approve(ticket, ev)
        with EpisodeStore(self.path) as db:
            self.assertEqual(db.get_episode(self.pid, 1).final_text, TEXT1)
        self.assertFalse(self.store.get_request(self.pid, ticket.request.request_id).publication_executed)

    def test_new_review_does_not_approve_automatically(self):
        ticket, ev = self.begin()
        self.approve(ticket, ev)
        newer = self.store.begin_review(self.pid, ev)
        self.assertEqual(newer.request.status, 'PENDING')

    def test_reject_after_change_still_possible(self):
        ticket, ev = self.begin()
        self.store.save_rule(self.pid, 'genre', 'fantasy')
        self.assertEqual(self.store.decide(self.pid, ticket.request.request_id, ev,
            decision='REJECT', confirmation=ticket.confirmation('REJECT')).status, 'REJECTED')

    def test_invalid_request_id_rejected(self):
        ticket, ev = self.begin()
        for rid in ('invalid', '0'*32, None):
            with self.subTest(rid=rid), self.assertRaises(Exception):
                self.store.get_request(self.pid, rid)

    def test_events_no_manuscript(self):
        ticket, ev = self.begin()
        self.approve(ticket, ev)
        self.assertEqual(self.store.list_events(self.pid, ticket.request.request_id),
                         ('REQUESTED', 'APPROVED'))

    def test_database_challenge_hash_not_plaintext(self):
        ticket, ev = self.begin()
        row = self.store._db.execute('''SELECT challenge_sha256 FROM bible_publication_review
            WHERE request_id=?''', (ticket.request.request_id,)).fetchone()
        self.assertNotEqual(row[0], ticket.code)
        self.assertEqual(len(row[0]), 64)


if __name__ == '__main__':
    unittest.main()
