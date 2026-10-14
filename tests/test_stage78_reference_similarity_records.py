"""Stage 78: no finalization without matching, current review record."""
from dataclasses import replace
from hashlib import sha256
import unittest

from ai_novel_factory.database.reference_catalog import ReferenceCatalog
from ai_novel_factory.reference_similarity_checker import (
    ReferenceMaterial, ReferenceSimilarityError, TextSpan, check_reference_similarity,
)
from ai_novel_factory.reference_similarity_records import ReferenceSimilarityReviewStore

PID = 'b' * 32
DRAFT = '푸른 호수 위를 가로지르는 작은 배는 새로운 항구를 향했다.'
SOURCE = '모래 언덕 사이로 달리는 긴 기차는 먼 기착지를 향해 이동했다.'
BEATS1 = ('setup', 'reversal', 'climax', 'hook')
BEATS2 = ('inciting', 'setback', 'resolution', 'transition')


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.catalog = ReferenceCatalog(':memory:')
        self.record = self.catalog.register(file_name='ref.txt', source_format='txt',
                                            byte_count=len(SOURCE.encode()),
                                            sha256=sha256(SOURCE.encode()).hexdigest())
        self.catalog.change_status(self.record.reference_id, 'analyzing')
        self.catalog.change_status(self.record.reference_id, 'analyzed')
        self.store = ReferenceSimilarityReviewStore(':memory:')

    def tearDown(self):
        self.store.close()
        self.catalog.close()

    def kwargs(self, text=DRAFT):
        return dict(references=(ReferenceMaterial(self.record.reference_id, self.record.sha256,
                                                 SOURCE, (TextSpan(0, len(SOURCE)),), BEATS2),),
                    draft_scenes=(TextSpan(0, len(text)),), draft_beats=BEATS1,
                    required_reference_ids=(self.record.reference_id,), catalog=self.catalog)

    def test_explicit_receipt_then_gate(self):
        kw = self.kwargs()
        report = check_reference_similarity(PID, 1, DRAFT, **kw)
        self.assertEqual(report.status, 'clear')
        with self.assertRaises(ReferenceSimilarityError):
            self.store.require_current_clear_review(PID, 1, DRAFT, **kw)
        receipt = self.store.record(report)
        self.assertEqual(receipt.status, 'clear')
        self.assertFalse(receipt.manuscript_approved)
        self.assertFalse(receipt.publication_approved)
        self.assertEqual(receipt, self.store.require_current_clear_review(PID, 1, DRAFT, **kw))

    def test_changed_draft_requires_new_review(self):
        self.store.record(check_reference_similarity(PID, 1, DRAFT, **self.kwargs()))
        changed = DRAFT + ' 추가 장면.'
        with self.assertRaises(ReferenceSimilarityError):
            self.store.require_current_clear_review(PID, 1, changed, **self.kwargs(changed))

    def test_other_episode_rejected(self):
        self.store.record(check_reference_similarity(PID, 1, DRAFT, **self.kwargs()))
        with self.assertRaises(ReferenceSimilarityError):
            self.store.require_current_clear_review(PID, 2, DRAFT, **self.kwargs())

    def test_reference_text_change_requires_new_review(self):
        self.store.record(check_reference_similarity(PID, 1, DRAFT, **self.kwargs()))
        kw = self.kwargs()
        kw['references'] = (replace(kw['references'][0], text=SOURCE + '추가'),)
        with self.assertRaises(ReferenceSimilarityError):
            self.store.require_current_clear_review(PID, 1, DRAFT, **kw)

    def test_report_with_missing_registration_cannot_record(self):
        kw = self.kwargs()
        kw['catalog'] = None
        report = check_reference_similarity(PID, 1, DRAFT, **kw)
        with self.assertRaises(ReferenceSimilarityError):
            self.store.record(report)

    def test_review_status_never_allows_clear_gate(self):
        report = check_reference_similarity(PID, 1, SOURCE, **self.kwargs(SOURCE))
        self.assertEqual(report.status, 'review')
        self.store.record(report)
        with self.assertRaises(ReferenceSimilarityError):
            self.store.require_current_clear_review(PID, 1, SOURCE, **self.kwargs(SOURCE))

    def test_report_has_no_prose_in_db(self):
        self.store.record(check_reference_similarity(PID, 1, DRAFT, **self.kwargs()))
        ddl = self.store._db.iterdump()
        dumped = '\n'.join(ddl)
        self.assertNotIn('푸른 호수', dumped)
        self.assertNotIn('모래 언덕', dumped)

    def test_forged_approval_report_rejected(self):
        report = check_reference_similarity(PID, 1, DRAFT, **self.kwargs())
        with self.assertRaises(ReferenceSimilarityError):
            self.store.record(replace(report, publication_approved=True))

    def test_bad_path_rejected(self):
        with self.assertRaises(ReferenceSimilarityError):
            ReferenceSimilarityReviewStore('/path/that/does/not/exist/reviews.sqlite')

    def test_duplicate_record_idempotent(self):
        report = check_reference_similarity(PID, 1, DRAFT, **self.kwargs())
        self.store.record(report)
        self.store.record(report)
        self.assertEqual(self.store._db.execute('SELECT COUNT(*) FROM similarity_review').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
