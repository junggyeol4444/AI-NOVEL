"""Stage 88 / ANF-REQ-061: ending audit remains read-only and fail-closed."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest

from ai_novel_factory.ending_audit import EndingAuditError, EndingReviewStore
from ai_novel_factory.database.foreshadow import ForeshadowStore
from ai_novel_factory.database.event_timeline import EventTimelineStore
from ai_novel_factory.database.episodes import EpisodeStore


class EndingAuditTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'novel.db'
        self.store = EndingReviewStore(self.path)
        self.addCleanup(self.store.close)
        self.project = self.store.create_project('오프라인 창작물').project_id
        with EpisodeStore(self.path) as db:
            for number in (1, 2):
                e = db.create_episode(self.project, number)
                db.update_episode(self.project, number, expected_revision=e.revision,
                                  final_text=f'독창적인 회차 {number}의 검토 후보')

    def report(self, **kwargs):
        return self.store.inspect_ending(self.project, 2, **kwargs)

    def ready(self):
        return self.report(foreshadow_inventory_reviewed=True,
                           conflict_inventory_reviewed=True,
                           timeline_inventory_reviewed=True)

    def test_empty_unreviewed_is_blocked(self):
        r = self.report()
        self.assertFalse(r.ready_for_human_review)
        self.assertEqual(len(r.findings), 3)

    def test_partial_inventory_blocks(self):
        r = self.report(conflict_inventory_reviewed=True)
        self.assertEqual(len(r.findings), 2)

    def test_empty_explicitly_reviewed_is_ready_for_human_only(self):
        r = self.ready()
        self.assertTrue(r.ready_for_human_review)
        self.assertEqual(r.status, 'NOT_FINALIZED_REQUIRES_USER_APPROVAL')
        self.assertEqual(r.final_manuscript_count, 2)
        self.assertEqual(r.findings, ())

    def test_bool_only_inventory_flags(self):
        with self.assertRaises(EndingAuditError):
            self.report(conflict_inventory_reviewed=1)

    def test_invalid_ending_episode(self):
        for episode in (0, -1, 1001, True, '2'):
            with self.subTest(episode=episode), self.assertRaises(EndingAuditError):
                self.store.inspect_ending(self.project, episode)

    def test_missing_ending_episode_blocks(self):
        r = self.store.inspect_ending(self.project, 3, foreshadow_inventory_reviewed=True,
            conflict_inventory_reviewed=True, timeline_inventory_reviewed=True)
        self.assertIn('ENDING_MANUSCRIPTS_MISSING', [f.code for f in r.findings])

    def test_blank_final_blocks(self):
        with EpisodeStore(self.path) as db:
            e = db.get_episode(self.project, 2)
            db.update_episode(self.project, 2, expected_revision=e.revision, final_text='')
        self.assertFalse(self.ready().ready_for_human_review)

    def test_future_manuscript_blocks(self):
        with EpisodeStore(self.path) as db:
            db.create_episode(self.project, 3)
            e = db.get_episode(self.project, 3)
            db.update_episode(self.project, 3, expected_revision=e.revision, draft='초고')
        self.assertIn('MANUSCRIPT_AFTER_ENDING', [f.code for f in self.ready().findings])

    def test_conflict_open_blocks(self):
        c = self.store.create_conflict(self.project, title='주요 갈등', opened_episode=1)
        r = self.ready()
        self.assertFalse(r.ready_for_human_review)
        self.assertEqual(next(f.item_ids for f in r.findings if f.code == 'CONFLICT_UNRESOLVED'),
                         (c.conflict_id,))

    def test_conflict_resolved_allows_review(self):
        c = self.store.create_conflict(self.project, title='주요 갈등', opened_episode=1)
        result = self.store.close_conflict(self.project, c.conflict_id, closed_episode=2,
                                           outcome='RESOLVED', expected_revision=1)
        self.assertEqual((result.status, result.revision), ('RESOLVED', 2))
        self.assertTrue(self.ready().ready_for_human_review)

    def test_conflict_abandoned_needs_review(self):
        c = self.store.create_conflict(self.project, title='주요 갈등', opened_episode=1)
        self.store.close_conflict(self.project, c.conflict_id, closed_episode=2,
                                  outcome='ABANDONED', expected_revision=1)
        self.assertIn('CONFLICT_ABANDONED_NEEDS_REVIEW',
                      [f.code for f in self.ready().findings])

    def test_conflict_future_close_blocks(self):
        c = self.store.create_conflict(self.project, title='주요 갈등', opened_episode=1)
        self.store.close_conflict(self.project, c.conflict_id, closed_episode=3,
                                  outcome='RESOLVED', expected_revision=1)
        self.assertIn('CONFLICT_EVENT_AFTER_ENDING', [f.code for f in self.ready().findings])

    def test_conflict_future_open_blocks(self):
        self.store.create_conflict(self.project, title='후일 갈등', opened_episode=3)
        self.assertIn('CONFLICT_EVENT_AFTER_ENDING', [f.code for f in self.ready().findings])

    def test_conflict_stale_revision_rejected(self):
        c = self.store.create_conflict(self.project, title='갈등', opened_episode=1)
        with self.assertRaises(EndingAuditError):
            self.store.close_conflict(self.project, c.conflict_id, closed_episode=2,
                                      outcome='RESOLVED', expected_revision=2)
        self.assertEqual(self.store.get_conflict(self.project, c.conflict_id).status, 'OPEN')

    def test_conflict_terminal_cannot_close_again(self):
        c = self.store.create_conflict(self.project, title='갈등', opened_episode=1)
        self.store.close_conflict(self.project, c.conflict_id, closed_episode=2,
                                  outcome='RESOLVED', expected_revision=1)
        with self.assertRaises(EndingAuditError):
            self.store.close_conflict(self.project, c.conflict_id, closed_episode=2,
                                      outcome='RESOLVED', expected_revision=2)

    def test_conflict_backwards_close_rejected(self):
        c = self.store.create_conflict(self.project, title='갈등', opened_episode=2)
        with self.assertRaises(EndingAuditError):
            self.store.close_conflict(self.project, c.conflict_id, closed_episode=1,
                                      outcome='RESOLVED', expected_revision=1)

    def test_conflict_invalid_outcome_rejected(self):
        c = self.store.create_conflict(self.project, title='갈등', opened_episode=1)
        with self.assertRaises(EndingAuditError):
            self.store.close_conflict(self.project, c.conflict_id, closed_episode=2,
                                      outcome='FINISHED', expected_revision=1)

    def test_conflict_project_isolation(self):
        other = self.store.create_project('다른 작품').project_id
        c = self.store.create_conflict(self.project, title='갈등', opened_episode=1)
        self.assertEqual(self.store.list_conflicts(other), ())
        with self.assertRaises(EndingAuditError):
            self.store.get_conflict(other, c.conflict_id)

    def test_conflict_persists_reopen(self):
        c = self.store.create_conflict(self.project, title='갈등', opened_episode=1)
        with EndingReviewStore(self.path) as other:
            self.assertEqual(other.get_conflict(self.project, c.conflict_id), c)

    def test_corrupted_conflict_fails_closed(self):
        c = self.store.create_conflict(self.project, title='갈등', opened_episode=1)
        with sqlite3.connect(self.path) as conn:
            conn.execute('PRAGMA ignore_check_constraints=ON')
            conn.execute('''UPDATE bible_ending_conflicts SET status='RESOLVED'
                            WHERE conflict_id=?''', (c.conflict_id,))
        with self.assertRaises(EndingAuditError):
            self.ready()

    def test_foreshadow_open_blocks(self):
        with ForeshadowStore(self.path) as db:
            thread = db.create_thread(self.project, title='숨은 복선', episode=1)
        r = self.ready()
        self.assertIn('FORESHADOW_UNRESOLVED', [f.code for f in r.findings])
        self.assertEqual(r.foreshadow_count, 1)

    def test_foreshadow_developing_blocks(self):
        with ForeshadowStore(self.path) as db:
            t = db.create_thread(self.project, title='복선', episode=1)
            db.add_event(self.project, t.thread_id, episode=2, action='REVISIT', expected_revision=1)
        self.assertIn('FORESHADOW_UNRESOLVED', [f.code for f in self.ready().findings])

    def test_foreshadow_resolved_allows(self):
        with ForeshadowStore(self.path) as db:
            t = db.create_thread(self.project, title='복선', episode=1)
            db.add_event(self.project, t.thread_id, episode=2, action='RESOLVE', expected_revision=1)
        self.assertTrue(self.ready().ready_for_human_review)

    def test_foreshadow_abandoned_needs_review(self):
        with ForeshadowStore(self.path) as db:
            t = db.create_thread(self.project, title='복선', episode=1)
            db.add_event(self.project, t.thread_id, episode=2, action='ABANDON', expected_revision=1)
        self.assertIn('FORESHADOW_ABANDONED_NEEDS_REVIEW',
                      [f.code for f in self.ready().findings])

    def test_foreshadow_future_install_blocks(self):
        with ForeshadowStore(self.path) as db:
            db.create_thread(self.project, title='미래 복선', episode=3)
        codes = [f.code for f in self.ready().findings]
        self.assertIn('FORESHADOW_AFTER_ENDING', codes)
        self.assertIn('FORESHADOW_NOT_INSTALLED_BY_ENDING', codes)

    def test_foreshadow_future_resolution_blocks(self):
        with ForeshadowStore(self.path) as db:
            t = db.create_thread(self.project, title='복선', episode=1)
            db.add_event(self.project, t.thread_id, episode=3, action='RESOLVE', expected_revision=1)
        codes = [f.code for f in self.ready().findings]
        self.assertIn('FORESHADOW_AFTER_ENDING', codes)
        self.assertIn('FORESHADOW_UNRESOLVED', codes)

    def test_timeline_known_date_passes(self):
        with EventTimelineStore(self.path) as db:
            db.create_event(self.project, title='사건', when='2026-10-12T00:00:00+00:00')
        self.assertTrue(self.ready().ready_for_human_review)

    def test_timeline_unknown_date_needs_review(self):
        with EventTimelineStore(self.path) as db:
            db.create_event(self.project, title='사건')
        self.assertIn('TIMELINE_UNKNOWN_DATES_NEEDS_REVIEW',
                      [f.code for f in self.ready().findings])

    def test_timeline_corruption_fails_closed(self):
        with EventTimelineStore(self.path) as db:
            a = db.create_event(self.project, title='A', when='2026-10-12T00:00:00+00:00')
            b = db.create_event(self.project, title='B', when='2026-10-13T00:00:00+00:00')
        with sqlite3.connect(self.path) as conn:
            conn.execute('''INSERT INTO bible_timeline_order(project_id,before_id,after_id)
                            VALUES(?,?,?)''', (self.project, b.event_id, a.event_id))
        self.assertIn('TIMELINE_INVALID', [f.code for f in self.ready().findings])

    def test_report_digest_stable(self):
        self.assertEqual(self.ready().evidence_digest, self.ready().evidence_digest)

    def test_require_current_review_succeeds_without_finalizing(self):
        r = self.ready()
        current = self.store.require_current_review(r, foreshadow_inventory_reviewed=True,
            conflict_inventory_reviewed=True, timeline_inventory_reviewed=True)
        self.assertEqual(r, current)
        with EpisodeStore(self.path) as db:
            self.assertTrue(db.get_episode(self.project, 2).final_text)

    def test_require_current_review_blocks_unreviewed(self):
        with self.assertRaises(EndingAuditError):
            self.store.require_current_review(self.report(),
                foreshadow_inventory_reviewed=True, conflict_inventory_reviewed=True,
                timeline_inventory_reviewed=True)

    def test_require_current_review_rejects_forged_flag(self):
        r = self.ready()
        with self.assertRaises(EndingAuditError):
            self.store.require_current_review(r, foreshadow_inventory_reviewed=False,
                conflict_inventory_reviewed=True, timeline_inventory_reviewed=True)

    def test_require_current_review_rejects_manuscript_change(self):
        r = self.ready()
        with EpisodeStore(self.path) as db:
            ep = db.get_episode(self.project, 1)
            db.update_episode(self.project, 1, expected_revision=ep.revision, final_text='수정 원고')
        with self.assertRaises(EndingAuditError):
            self.store.require_current_review(r, foreshadow_inventory_reviewed=True,
                conflict_inventory_reviewed=True, timeline_inventory_reviewed=True)

    def test_require_current_review_rejects_new_conflict(self):
        r = self.ready()
        self.store.create_conflict(self.project, title='추가 갈등', opened_episode=2)
        with self.assertRaises(EndingAuditError):
            self.store.require_current_review(r, foreshadow_inventory_reviewed=True,
                conflict_inventory_reviewed=True, timeline_inventory_reviewed=True)

    def test_require_current_review_rejects_foreshadow_change(self):
        r = self.ready()
        with ForeshadowStore(self.path) as db:
            db.create_thread(self.project, title='추가 복선', episode=1)
        with self.assertRaises(EndingAuditError):
            self.store.require_current_review(r, foreshadow_inventory_reviewed=True,
                conflict_inventory_reviewed=True, timeline_inventory_reviewed=True)

    def test_report_does_not_expose_manuscript_or_titles(self):
        with EpisodeStore(self.path) as db:
            e = db.get_episode(self.project, 2)
            db.update_episode(self.project, 2, expected_revision=e.revision,
                              final_text='원고 비밀 문구 987654')
        r = self.ready()
        self.assertNotIn('원고 비밀', repr(r))
        self.assertNotIn('오프라인 창작물', repr(r))

    def test_bad_conflict_id_does_not_echo_title(self):
        with self.assertRaises(EndingAuditError) as ctx:
            self.store.get_conflict(self.project, '0'*32)
        self.assertNotIn('오프라인 창작물', str(ctx.exception))

    def test_no_implicit_completion_state_created(self):
        self.ready()
        with sqlite3.connect(self.path) as conn:
            tables = {row[0] for row in conn.execute('SELECT name FROM sqlite_master WHERE type="table"')}
        self.assertNotIn('bible_completion_approved', tables)

    def test_memory_database_rejected(self):
        with self.assertRaises(EndingAuditError):
            EndingReviewStore(':memory:')


if __name__ == '__main__':
    unittest.main()
