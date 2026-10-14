"""Stage 81: explicit final-text memory markers produce review-only SQLite candidates."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import sqlite3
import tempfile
import unittest

from ai_novel_factory.database.episodes import EpisodeStore
from ai_novel_factory.memory_delta import (
    FinalTextAttestation, MemoryDeltaError, MemoryDeltaReviewStore,
    extract_memory_delta,
)

PID = 'a' * 32
CID = 'b' * 32
TID = 'c' * 32
TEXT = (f'처음 사건. [[ANF_MEMORY|FACT|{CID}|새로운 능력을 얻었다]]\n'
        f'다음 사건. [[ANF_MEMORY|RELATIONSHIP|{CID}|{TID}|동맹]]\n'
        f'마지막 사건. [[ANF_MEMORY|FORESHADOW|{TID}|REVISIT|다시 등장]]')


def h(s):
    return sha256(s.encode('utf-8')).hexdigest()


class MemoryDeltaStage81Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.episodes = EpisodeStore(Path(self.temp.name) / 'episode.db')
        self.pid = self.episodes.create_project('테스트 작품').project_id
        self.episodes.create_episode(self.pid, 3)
        ep = self.episodes.get_episode(self.pid, 3)
        ep = self.episodes.update_episode(self.pid, 3, expected_revision=ep.revision, final_text=TEXT)
        self.evidence = FinalTextAttestation(self.pid, 3, ep.revision, h(TEXT), 'review-confirmed-123', True)
        self.reviews = MemoryDeltaReviewStore(Path(self.temp.name) / 'review.db')

    def tearDown(self):
        self.reviews.close()
        self.episodes._db.close()
        self.temp.cleanup()

    def delta(self, evidence=None):
        return extract_memory_delta(self.episodes, evidence or self.evidence)

    def test_extract_three_kinds(self):
        d = self.delta()
        self.assertEqual([c.kind for c in d.changes], ['FACT', 'RELATIONSHIP', 'FORESHADOW'])
        self.assertEqual(d.changes[0].fields, (CID, '새로운 능력을 얻었다'))
        self.assertEqual(d.changes[1].fields, (CID, TID, '동맹'))
        self.assertEqual(d.changes[2].fields, (TID, 'REVISIT', '다시 등장'))

    def test_offsets_and_hashes(self):
        d = self.delta()
        for c in d.changes:
            self.assertEqual(h(TEXT[c.start:c.end]), c.marker_sha256)
            self.assertEqual(len(c.change_id), 64)

    def test_review_only(self):
        d = self.delta()
        self.assertEqual(d.status, 'PENDING_HUMAN_REVIEW_NOT_APPLIED')
        self.assertFalse(d.canon_applied)
        self.assertFalse(d.publication_approved)
        self.assertTrue(all(c.status == 'PENDING_HUMAN_REVIEW' for c in d.changes))

    def test_save_and_list(self):
        d = self.delta()
        self.assertEqual(self.reviews.save(self.episodes, self.evidence, d), 3)
        self.assertEqual(self.reviews.list_review(self.episodes, self.evidence), d.changes)
        self.assertEqual(self.episodes.get_episode(self.pid, 3).final_text, TEXT)

    def test_idempotent(self):
        d = self.delta()
        self.reviews.save(self.episodes, self.evidence, d)
        self.reviews.save(self.episodes, self.evidence, d)
        self.assertEqual(self.reviews._db.execute('SELECT count(*) FROM memory_delta_reviews').fetchone()[0], 3)

    def test_reopen_review_db(self):
        d = self.delta()
        self.reviews.save(self.episodes, self.evidence, d)
        self.reviews.close()
        self.reviews = MemoryDeltaReviewStore(Path(self.temp.name) / 'review.db')
        self.assertEqual(self.reviews.list_review(self.episodes, self.evidence), d.changes)

    def test_missing_review_fails_closed(self):
        with self.assertRaises(MemoryDeltaError):
            self.reviews.list_review(self.episodes, self.evidence)

    def test_stale_final_text_fails(self):
        d = self.delta()
        self.reviews.save(self.episodes, self.evidence, d)
        ep = self.episodes.get_episode(self.pid, 3)
        self.episodes.update_episode(self.pid, 3, expected_revision=ep.revision, final_text=TEXT + '수정')
        for action in (self.delta, lambda: self.reviews.save(self.episodes, self.evidence, d),
                       lambda: self.reviews.list_review(self.episodes, self.evidence)):
            with self.assertRaises(MemoryDeltaError):
                action()

    def test_stale_revision_after_unrelated_edit_fails(self):
        ep = self.episodes.get_episode(self.pid, 3)
        self.episodes.update_episode(self.pid, 3, expected_revision=ep.revision, summary='요약')
        with self.assertRaises(MemoryDeltaError):
            self.delta()

    def test_wrong_project_rejected(self):
        with self.assertRaises(MemoryDeltaError):
            self.delta(replace(self.evidence, project_id='d' * 32))

    def test_wrong_episode_rejected(self):
        with self.assertRaises(MemoryDeltaError):
            self.delta(replace(self.evidence, episode_number=4))

    def test_wrong_hash_rejected(self):
        with self.assertRaises(MemoryDeltaError):
            self.delta(replace(self.evidence, final_sha256='0' * 64))

    def test_unapproved_rejected(self):
        with self.assertRaises(MemoryDeltaError):
            self.delta(replace(self.evidence, explicitly_approved_by_user=False))

    def test_approval_reference_required(self):
        with self.assertRaises(MemoryDeltaError):
            self.delta(replace(self.evidence, approval_reference=''))

    def test_fake_boolean_rejected(self):
        with self.assertRaises(MemoryDeltaError):
            self.delta(replace(self.evidence, explicitly_approved_by_user=1))

    def test_wrong_revision_rejected(self):
        with self.assertRaises(MemoryDeltaError):
            self.delta(replace(self.evidence, episode_revision=1))

    def test_tampered_delta_rejected(self):
        d = self.delta()
        with self.assertRaises(MemoryDeltaError):
            self.reviews.save(self.episodes, self.evidence, replace(d, changes=d.changes[:1]))

    def test_tampered_approval_rejected(self):
        d = self.delta()
        with self.assertRaises(MemoryDeltaError):
            self.reviews.save(self.episodes, replace(self.evidence, approval_reference='another-confirmed-123'), d)

    def test_tampered_row_detected(self):
        d = self.delta()
        self.reviews.save(self.episodes, self.evidence, d)
        self.reviews._db.execute("UPDATE memory_delta_reviews SET fields_json='[]' WHERE change_id=?", (d.changes[0].change_id,))
        self.reviews._db.commit()
        with self.assertRaises(MemoryDeltaError):
            self.reviews.list_review(self.episodes, self.evidence)

    def test_tampered_row_cannot_be_ignored_on_save(self):
        d = self.delta()
        self.reviews.save(self.episodes, self.evidence, d)
        self.reviews._db.execute("UPDATE memory_delta_reviews SET kind='FACT' WHERE change_id=?", (d.changes[1].change_id,))
        self.reviews._db.commit()
        with self.assertRaises(MemoryDeltaError):
            self.reviews.save(self.episodes, self.evidence, d)

    def test_atomic_rollback_on_conflict(self):
        d = self.delta()
        self.reviews._db.execute('''INSERT INTO memory_delta_reviews VALUES
            (?,?,?,?,?,?,?,?,?,?,?,?)''', (d.changes[-1].change_id, self.pid, 3, d.episode_revision,
            d.final_sha256, d.approval_reference, 'FACT', '[]', 1, 2, '0'*64, 'PENDING_HUMAN_REVIEW'))
        self.reviews._db.commit()
        with self.assertRaises(MemoryDeltaError):
            self.reviews.save(self.episodes, self.evidence, d)
        self.assertEqual(self.reviews._db.execute('SELECT count(*) FROM memory_delta_reviews').fetchone()[0], 1)

    def test_no_markers_returns_empty_review(self):
        ep = self.episodes.get_episode(self.pid, 3)
        ep = self.episodes.update_episode(self.pid, 3, expected_revision=ep.revision, final_text='일반 원고')
        evidence = replace(self.evidence, episode_revision=ep.revision, final_sha256=h('일반 원고'))
        self.assertEqual(self.delta(evidence).changes, ())
        self.assertEqual(self.reviews.save(self.episodes, evidence, self.delta(evidence)), 0)
        self.assertEqual(self.reviews.list_review(self.episodes, evidence), ())

    def test_unclosed_marker_rejected(self):
        self.assert_invalid_text('[[ANF_MEMORY|FACT|인물|내용')

    def test_bad_kind_rejected(self):
        self.assert_invalid_text('[[ANF_MEMORY|UNKNOWN|인물|내용]]')

    def test_bad_arity_rejected(self):
        self.assert_invalid_text('[[ANF_MEMORY|FACT|인물]]')

    def test_empty_field_rejected(self):
        self.assert_invalid_text('[[ANF_MEMORY|FACT|인물|]]')

    def test_self_relation_rejected(self):
        self.assert_invalid_text('[[ANF_MEMORY|RELATIONSHIP|a|a|친구]]')

    def test_bad_foreshadow_action_rejected(self):
        self.assert_invalid_text('[[ANF_MEMORY|FORESHADOW|a|DELETE|끝]]')

    def test_nested_marker_rejected(self):
        self.assert_invalid_text('[[ANF_MEMORY|FACT|a|[[ANF_MEMORY|FACT|b|c]]]]')

    def test_too_many_markers_rejected(self):
        self.assert_invalid_text('[[ANF_MEMORY|FACT|a|b]]' * 201)

    def test_no_prose_in_error(self):
        ep = self.episodes.get_episode(self.pid, 3)
        ep = self.episodes.update_episode(self.pid, 3, expected_revision=ep.revision, final_text='[[ANF_MEMORY|FACT|비밀주인공|]]')
        evidence = replace(self.evidence, episode_revision=ep.revision, final_sha256=h(ep.final_text))
        with self.assertRaises(MemoryDeltaError) as err:
            self.delta(evidence)
        self.assertNotIn('비밀주인공', str(err.exception))

    def test_no_prose_in_repr(self):
        self.assertNotIn('새로운 능력을 얻었다', repr(self.delta().changes[0]))

    def test_explicit_evidence_required(self):
        with self.assertRaises(MemoryDeltaError):
            extract_memory_delta(self.episodes, None)

    def test_project_canon_untouched(self):
        before = self.episodes.get_project(self.pid).revision
        self.reviews.save(self.episodes, self.evidence, self.delta())
        self.assertEqual(self.episodes.get_project(self.pid).revision, before)

    def test_distinct_approval_reference_changes_review_provenance(self):
        d = self.delta()
        self.reviews.save(self.episodes, self.evidence, d)
        evidence2 = replace(self.evidence, approval_reference='different-confirmation-987')
        with self.assertRaises(MemoryDeltaError):
            self.reviews.list_review(self.episodes, evidence2)

    def test_wrong_source_store_type(self):
        with self.assertRaises(MemoryDeltaError):
            extract_memory_delta(object(), self.evidence)

    def assert_invalid_text(self, text):
        ep = self.episodes.get_episode(self.pid, 3)
        ep = self.episodes.update_episode(self.pid, 3, expected_revision=ep.revision, final_text=text)
        evidence = replace(self.evidence, episode_revision=ep.revision, final_sha256=h(text))
        with self.assertRaises(MemoryDeltaError):
            self.delta(evidence)


if __name__ == '__main__':
    unittest.main()
