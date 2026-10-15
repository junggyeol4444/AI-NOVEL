"""Continuation of Stage 95 ONLY: title/note/metadata local review binding."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
import unittest

from ai_novel_factory.publication_metadata import save_metadata
from ai_novel_factory.publisher_adapter import PublisherAdapterError
from ai_novel_factory.publisher_asset_review import (
    PublisherAssetReviewError, PublisherAssetReviewStore,
    simulate_reviewed_offline_upload,
)
import test_stage95_publisher_adapter as fixture_module


class Stage95PublisherAssetReviewTests(unittest.TestCase):
    def setUp(self):
        fixture_module.Stage95PublisherAdapterTests.setUp(self)
        self.approval.decide(self.pid, self.ticket.request.request_id, self.evidence,
                             decision='APPROVE', confirmation=self.ticket.confirmation('APPROVE'))
        self.plan_obj = fixture_module.Stage95PublisherAdapterTests.plan(self)
        self.meta_path = save_metadata(self.metadata, self.parent).path
        self.metadata_sha = sha256(self.meta_path.read_bytes()).hexdigest()
        self.assets = PublisherAssetReviewStore(self.parent/'publisher_asset_reviews.sqlite')
        self.addCleanup(self.assets.close)

    def request(self):
        return self.assets.request_review(
            self.plan_obj, self.export.directory, self.meta_path,
            expected_metadata_sha256=self.metadata_sha,
            approval_store=self.approval, evidence=self.evidence)

    def decide(self, challenge, *, decision='REVIEW', confirmation=None):
        if confirmation is None:
            confirmation = challenge.confirmation() if decision == 'REVIEW' else (
                'REJECT-PUBLISHER-ASSETS '+challenge.review_id+' '+challenge.confirmation_code)
        return self.assets.decide(
            challenge.review_id, self.plan_obj, self.export.directory, self.meta_path,
            expected_metadata_sha256=self.metadata_sha, approval_store=self.approval,
            evidence=self.evidence, decision=decision, confirmation=confirmation)

    def simulate(self, review_id, **kwargs):
        return simulate_reviewed_offline_upload(
            kwargs.get('plan', self.plan_obj), self.export.directory, self.meta_path,
            expected_metadata_sha256=kwargs.get('metadata_sha', self.metadata_sha),
            review_id=review_id, review_store=self.assets,
            approval_store=self.approval, evidence=self.evidence)

    def test_pending_blocks_even_valid_manuscript_approval(self):
        challenge = self.request()
        with self.assertRaises(PublisherAssetReviewError): self.simulate(challenge.review_id)

    def test_explicit_review_allows_only_offline_mock(self):
        ch = self.request()
        record = self.decide(ch)
        self.assertEqual(record.status, 'REVIEWED')
        receipt = self.simulate(ch.review_id)
        self.assertEqual(receipt.status, 'LOCAL_SIMULATION_NOT_UPLOADED')
        self.assertFalse(receipt.publication_executed)
        self.assertFalse(receipt.official_sandbox_upload_verified)
        self.assertNotIn(self.metadata.title, repr(record))
        self.assertNotIn(self.metadata.description, repr(record))
        self.assertNotIn(self.metadata.title, repr(receipt))

    def test_bad_explicit_code_fails(self):
        ch = self.request()
        with self.assertRaises(PublisherAssetReviewError): self.decide(ch, confirmation='CONFIRM-PUBLISHER-ASSETS '+ch.review_id+' '+'0'*32)
        self.decide(ch)

    def test_reject_fails_closed(self):
        ch = self.request()
        self.assertEqual(self.decide(ch, decision='REJECT').status, 'REJECTED')
        with self.assertRaises(PublisherAssetReviewError): self.simulate(ch.review_id)

    def test_repeated_decision_disallowed(self):
        ch = self.request(); self.decide(ch)
        with self.assertRaises(PublisherAssetReviewError): self.decide(ch)

    def test_revocation_blocks(self):
        ch = self.request(); self.decide(ch)
        with self.assertRaises(PublisherAssetReviewError): self.assets.revoke(ch.review_id, confirmation='REVOKE wrong')
        self.assets.revoke(ch.review_id, confirmation='REVOKE-PUBLISHER-ASSETS '+ch.review_id)
        with self.assertRaises(PublisherAssetReviewError): self.simulate(ch.review_id)

    def test_metadata_tampering_is_detected(self):
        ch = self.request(); self.decide(ch)
        self.meta_path.write_bytes(self.meta_path.read_bytes()+b' ')  # envelope no longer canonical
        with self.assertRaises(PublisherAssetReviewError): self.simulate(ch.review_id)

    def test_metadata_replacement_with_new_checksum_invalidates_prior_review(self):
        ch = self.request(); self.decide(ch)
        self.meta_path.unlink()
        save_metadata(replace(self.metadata, description='변경된 설명'), self.parent)
        fresh_sha = sha256(self.meta_path.read_bytes()).hexdigest()
        with self.assertRaises(PublisherAssetReviewError): self.simulate(ch.review_id, metadata_sha=fresh_sha)

    def test_modified_title_detected(self):
        ch = self.request(); self.decide(ch)
        (self.export.directory / 'episode_0001_title.txt').write_text('변경', encoding='utf-8')
        with self.assertRaises(PublisherAssetReviewError): self.simulate(ch.review_id)

    def test_modified_author_note_detected(self):
        ch = self.request(); self.decide(ch)
        (self.export.directory / 'episode_0001_author_note.txt').write_text('변경', encoding='utf-8')
        with self.assertRaises(PublisherAssetReviewError): self.simulate(ch.review_id)

    def test_approval_revocation_invalidates_assets(self):
        ch = self.request(); self.decide(ch)
        self.approval.revoke(self.pid, self.ticket.request.request_id,
                             confirmation=f'REVOKE {self.ticket.request.request_id}')
        with self.assertRaises(PublisherAssetReviewError): self.simulate(ch.review_id)

    def test_rule_change_invalidates_assets(self):
        ch = self.request(); self.decide(ch)
        self.approval.save_rule(self.pid, 'genre', '다른 장르')
        with self.assertRaises(PublisherAssetReviewError): self.simulate(ch.review_id)

    def test_different_project_metadata_rejected(self):
        self.meta_path.unlink()
        save_metadata(replace(self.metadata, project_id='other-project'), self.parent)
        self.metadata_sha = sha256(self.meta_path.read_bytes()).hexdigest()
        with self.assertRaises(PublisherAssetReviewError): self.request()

    def test_bad_digest_rejected(self):
        for v in ('bad', '', 'Z'*64, None, True):
            with self.subTest(v=v), self.assertRaises(PublisherAssetReviewError):
                self.assets.request_review(
                    self.plan_obj, self.export.directory, self.meta_path,
                    expected_metadata_sha256=v, approval_store=self.approval,
                    evidence=self.evidence)

    def test_plan_swap_is_rejected(self):
        ch = self.request(); self.decide(ch)
        with self.assertRaises(PublisherAssetReviewError): self.simulate(ch.review_id,
            plan=replace(self.plan_obj, plan_sha256='f'*64))

    def test_wrong_identifier_is_rejected(self):
        ch = self.request(); self.decide(ch)
        with self.assertRaises(PublisherAssetReviewError): self.simulate('bogus')
        with self.assertRaises(PublisherAssetReviewError): self.simulate('0'*32)

    def test_read_only_and_no_network(self):
        ch = self.request(); self.decide(ch)
        original = {f.name: sha256(f.read_bytes()).hexdigest()
                    for f in self.export.directory.iterdir()}
        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            self.simulate(ch.review_id)
        self.assertEqual(original, {f.name: sha256(f.read_bytes()).hexdigest()
                                    for f in self.export.directory.iterdir()})

    def test_db_reopen_retains_review_without_code(self):
        ch = self.request(); self.decide(ch)
        self.assets.close()
        self.assets = PublisherAssetReviewStore(self.parent/'publisher_asset_reviews.sqlite')
        self.addCleanup(self.assets.close)
        self.assertEqual(self.simulate(ch.review_id).accepted_episode_count, 1)
        data = (self.parent/'publisher_asset_reviews.sqlite').read_bytes()
        self.assertNotIn(ch.confirmation_code.encode(), data)
        self.assertNotIn(self.metadata.description.encode(), data)

    def test_review_cannot_be_created_before_89_approval(self):
        self.approval.revoke(self.pid, self.ticket.request.request_id,
                             confirmation=f'REVOKE {self.ticket.request.request_id}')
        with self.assertRaises(PublisherAssetReviewError): self.request()

    def test_confirmed_review_is_not_platform_permission(self):
        ch = self.request(); self.decide(ch)
        from ai_novel_factory.publisher_adapter import upload_to_real_platform
        with self.assertRaises(PublisherAdapterError):
            upload_to_real_platform(ch.review_id)


if __name__ == '__main__':
    unittest.main()
