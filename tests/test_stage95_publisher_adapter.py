"""Stage 95 local-only adapter tests, including stage-89 + stage-94 integration."""
from __future__ import annotations
from dataclasses import replace
from hashlib import sha256
import tempfile
from pathlib import Path
import unittest

from ai_novel_factory.database.reference_catalog import ReferenceCatalog
from ai_novel_factory.manuscript_versions import ManuscriptVersionStore
from ai_novel_factory.publication_approval import PublicationApprovalStore, PublicationReviewEvidence
from ai_novel_factory.publication_metadata import MetadataDraft
from ai_novel_factory.episode_upload_files import UploadEpisode, export_upload_drafts
from ai_novel_factory.publisher_adapter import (
    PublisherAdapterError, LocalSandboxPublisherAdapter, PublisherAdapterContract,
    prepare_offline_publisher_plan, simulate_offline_upload, upload_to_real_platform,
)

TEXT = '신규 작품의 주인공은 스스로 마을을 떠나 여행길에 올랐다.'


class Stage95PublisherAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.parent = Path(self.tmp.name)
        self.dbfile = self.parent / 'novel.sqlite'
        self.approval = PublicationApprovalStore(self.dbfile)
        self.addCleanup(self.approval.close)
        self.catalog = ReferenceCatalog(':memory:')
        self.addCleanup(self.catalog.close)
        self.pid = self.approval.create_project('로컬 모의 작품').project_id
        with ManuscriptVersionStore(self.dbfile) as v:
            e = v.create_episode(self.pid, 1)
            v.save_version(self.pid, 1, TEXT, kind='FINAL', expected_revision=e.revision)
        self.report = self.approval.inspect_ending(self.pid, 1,
            foreshadow_inventory_reviewed=True, conflict_inventory_reviewed=True,
            timeline_inventory_reviewed=True)
        self.evidence = PublicationReviewEvidence(
            ending_report=self.report, reference_catalog=self.catalog,
            similarity_store=None, no_references_confirmed=True,
            foreshadow_inventory_reviewed=True, conflict_inventory_reviewed=True,
            timeline_inventory_reviewed=True)
        self.ticket = self.approval.begin_review(self.pid, self.evidence)
        self.metadata = MetadataDraft(project_id=self.pid, title='독창적 제목', author='저자',
                                      description='새로운 마을을 향하는 장편 이야기',
                                      category='판타지', keywords=('모험','여정'), price_amount='0',
                                      currency='KRW', language='ko')
        self.export = export_upload_drafts(self.metadata,
            [UploadEpisode(1, '1화 시작', TEXT, '새로운 소식')], self.parent)

    def approve(self):
        self.approval.decide(self.pid, self.ticket.request.request_id,
            self.evidence, decision='APPROVE',
            confirmation=self.ticket.confirmation('APPROVE'))

    def plan(self, *, digest=None, project=None, evidence=None):
        return prepare_offline_publisher_plan(
            self.export.directory, expected_draft_sha256=self.export.manifest_sha256 if digest is None else digest,
            project_id=project or self.pid, approval_request_id=self.ticket.request.request_id,
            approval_store=self.approval, evidence=evidence or self.evidence)

    def test_pending_blocks_preview(self):
        with self.assertRaises(PublisherAdapterError): self.plan()

    def test_approved_local_mock_only(self):
        self.approve()
        plan = self.plan()
        receipt = simulate_offline_upload(plan, self.export.directory,
            approval_store=self.approval, evidence=self.evidence)
        self.assertEqual(receipt.status, 'LOCAL_SIMULATION_NOT_UPLOADED')
        self.assertEqual(receipt.accepted_episode_count, 1)
        self.assertEqual(receipt.plan_sha256, plan.plan_sha256)
        self.assertFalse(receipt.official_api_spec_verified)
        self.assertFalse(receipt.official_sandbox_upload_verified)
        self.assertFalse(receipt.publication_executed)
        self.assertEqual(len(plan.artifacts), 1)
        self.assertEqual(plan.artifacts[0].body_sha256, sha256(TEXT.encode()).hexdigest())
        self.assertNotIn(TEXT, repr(plan))
        self.assertNotIn(TEXT, repr(receipt))
        self.assertIsInstance(LocalSandboxPublisherAdapter(), PublisherAdapterContract)

    def test_wrong_manifest_digest_blocks(self):
        self.approve()
        with self.assertRaises(PublisherAdapterError): self.plan(digest='0'*64)

    def test_wrong_project_blocks(self):
        self.approve()
        with self.assertRaises(PublisherAdapterError): self.plan(project='another_project')

    def test_invalid_digest_blocks(self):
        self.approve()
        for value in ('xx', 'Z'*64, '', True):
            with self.subTest(value=value), self.assertRaises(PublisherAdapterError):
                self.plan(digest=value)

    def test_tampered_body_blocks(self):
        self.approve()
        p = self.export.directory / 'episode_0001_body.txt'
        p.write_text('변조된 본문', encoding='utf-8')
        with self.assertRaises(PublisherAdapterError): self.plan()

    def test_mismatched_approved_text_blocks_even_with_valid_manifest(self):
        self.approve()
        # Freshly exported unrelated text has internally correct hashes but
        # cannot reuse approval for the DB's different FINAL manuscript.
        self.export.directory.rename(self.parent/'old_drafts')
        second = export_upload_drafts(self.metadata,
            [UploadEpisode(1, '1화 시작', '검증되지 않은 새 본문')], self.parent)
        with self.assertRaises(PublisherAdapterError): self.plan(digest=second.manifest_sha256)

    def test_cancel_or_revoke_blocks(self):
        self.approve()
        plan = self.plan()
        self.approval.revoke(self.pid, self.ticket.request.request_id,
            confirmation=f'REVOKE {self.ticket.request.request_id}')
        with self.assertRaises(PublisherAdapterError):
            simulate_offline_upload(plan, self.export.directory,
                approval_store=self.approval, evidence=self.evidence)

    def test_change_after_plan_blocks(self):
        self.approve()
        plan = self.plan()
        self.approval.save_rule(self.pid, 'genre', 'new genre')
        with self.assertRaises(PublisherAdapterError):
            simulate_offline_upload(plan, self.export.directory,
                approval_store=self.approval, evidence=self.evidence)

    def test_plan_forgery_blocks(self):
        self.approve()
        plan = self.plan()
        for p in (replace(plan, adapter_id='some-platform'),
                  replace(plan, official_api_spec_verified=True),
                  replace(plan, plan_sha256='f'*64),
                  replace(plan, artifacts=()),
                  replace(plan, publication_executed=True)):
            with self.subTest(value=repr(p)[:60]), self.assertRaises(PublisherAdapterError):
                simulate_offline_upload(p, self.export.directory,
                    approval_store=self.approval, evidence=self.evidence)

    def test_arbitrary_adapter_rejected(self):
        self.approve()
        plan = self.plan()
        class FakePublisher:
            def simulate(self, plan): raise RuntimeError('SHOULD NOT RUN')
        with self.assertRaises(PublisherAdapterError):
            simulate_offline_upload(plan, self.export.directory,
                approval_store=self.approval, evidence=self.evidence, adapter=FakePublisher())

    def test_simulation_is_read_only(self):
        self.approve()
        plan = self.plan()
        before = {p.name: sha256(p.read_bytes()).hexdigest()
                  for p in self.export.directory.iterdir()}
        for _ in range(2):
            simulate_offline_upload(plan, self.export.directory,
                approval_store=self.approval, evidence=self.evidence)
        after = {p.name: sha256(p.read_bytes()).hexdigest()
                 for p in self.export.directory.iterdir()}
        self.assertEqual(before, after)
        self.assertEqual(self.approval.get_request(self.pid,
            self.ticket.request.request_id).status, 'APPROVED')

    def test_real_upload_explicitly_prohibited(self):
        for args in ((), ('real-platform',), (object(),)):
            with self.assertRaises(PublisherAdapterError): upload_to_real_platform(*args)

    def test_stored_no_network_calls(self):
        from unittest.mock import patch
        self.approve()
        plan = self.plan()
        with patch('socket.socket', side_effect=AssertionError('NETWORK')):
            receipt = simulate_offline_upload(plan, self.export.directory,
                approval_store=self.approval, evidence=self.evidence)
        self.assertEqual(receipt.accepted_episode_count, 1)


if __name__ == '__main__': unittest.main()
