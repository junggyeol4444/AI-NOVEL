"""Stage 82 / ANF-REQ-058: reviewed canon application, rollback and idempotence."""
import hashlib
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from ai_novel_factory.database.episodes import EpisodeStore
from ai_novel_factory.database.event_timeline import EventTimelineStore
from ai_novel_factory.database.foreshadow import ForeshadowStore
from ai_novel_factory.memory_delta import (
    FinalTextAttestation, MemoryDeltaReviewStore, extract_memory_delta)
from ai_novel_factory.memory_application import (
    MemoryCanonStore, MemoryApproval, MemoryApplicationError)


def h(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


class MemoryApplicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'canon.db'
        self.canon = MemoryCanonStore(self.path)
        self.pid = self.canon.create_project('작품').project_id
        self.c1 = self.canon.create_character(self.pid, name='가', personality='신중함',
            goal='여행', speech_style='간결함')
        self.c2 = self.canon.create_character(self.pid, name='나', personality='용감함',
            goal='연구', speech_style='단호함')
        self.world = self.canon.create_entry(self.pid, category='region', name='도시',
                                             description='산 위 도시')
        self.timeline_store = EventTimelineStore(self.path)
        self.timeline = self.timeline_store.create_event(self.pid, title='첫 만남')
        self.thread = ForeshadowStore.create_thread(self.canon, self.pid, title='봉인',
                                                     episode=1, note='암시')
        self.episodes = EpisodeStore(self.path)
        self.episodes.create_episode(self.pid, 3)
        self.new_thread_id = 'f' * 32
        self.text = ('시작\n'
            f'[[ANF_MEMORY|FACT|{self.c1.character_id}|능력을 얻음]]\n'
            f'[[ANF_MEMORY|FACT|{self.world.entry_id}|마을이 확장됨]]\n'
            f'[[ANF_MEMORY|FACT|{self.timeline.event_id}|비가 내림]]\n'
            f'[[ANF_MEMORY|RELATIONSHIP|{self.c1.character_id}|{self.c2.character_id}|동맹]]\n'
            f'[[ANF_MEMORY|FORESHADOW|{self.thread.thread_id}|REVISIT|봉인을 다시 봄]]\n'
            f'[[ANF_MEMORY|FORESHADOW|{self.new_thread_id}|INSTALL|새 단서]]')
        self.set_text(self.text)
        self.reviews = MemoryDeltaReviewStore(Path(self.tmp.name) / 'reviews.db')
        self.delta = extract_memory_delta(self.episodes, self.evidence)
        self.reviews.save(self.episodes, self.evidence, self.delta)

    def tearDown(self):
        self.reviews.close()
        self.episodes.close()
        self.canon.close()
        self.timeline_store.close()
        self.tmp.cleanup()

    def set_text(self, text):
        old = self.episodes.get_episode(self.pid, 3)
        ep = self.episodes.update_episode(self.pid, 3, expected_revision=old.revision,
                                          final_text=text)
        self.evidence = FinalTextAttestation(self.pid, 3, ep.revision, h(text),
                                             'approved-ref-12345', True)

    def approvals(self):
        items = []
        for change in self.delta.changes:
            if change.kind == 'FACT':
                target_id = change.fields[0]
                if target_id == self.c1.character_id:
                    kind, rev = 'character', self.canon.get_character(self.pid, target_id).revision
                elif target_id == self.world.entry_id:
                    kind, rev = 'world', self.canon.get_entry(self.pid, target_id).revision
                else:
                    kind, rev = 'timeline', EventTimelineStore.get_event(
                        self.canon, self.pid, target_id).revision
                items.append(MemoryApproval(change.change_id, kind, target_id,
                                             'reviewer-approval-123', True, rev))
            elif change.kind == 'RELATIONSHIP':
                items.append(MemoryApproval(change.change_id, 'relationship', '',
                                             'reviewer-approval-123', True))
            elif change.fields[1] == 'INSTALL':
                items.append(MemoryApproval(change.change_id, 'foreshadow',
                    change.fields[0], 'reviewer-approval-123', True,
                    new_thread_title='새로운 복선'))
            else:
                items.append(MemoryApproval(change.change_id, 'foreshadow',
                    change.fields[0], 'reviewer-approval-123', True,
                    self.canon.get_thread(self.pid, change.fields[0]).revision))
        return tuple(items)

    def apply(self, approvals=None):
        return self.canon.apply(self.episodes, self.reviews, self.evidence,
                                approvals if approvals is not None else self.approvals())

    def count(self, table):
        return self.canon._db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]

    def test_apply_all_kinds(self):
        result = self.apply()
        self.assertEqual((result.applied, result.already_applied), (6, 0))
        self.assertFalse(result.publication_approved)
        self.assertEqual(self.count('bible_memory_facts'), 3)
        self.assertEqual(self.count('bible_memory_applications'), 6)
        self.assertEqual(self.canon.get_event(self.pid, self.c1.character_id,
            self.c2.character_id, 3).relationship, '동맹')
        self.assertEqual(ForeshadowStore.get_at(self.canon, self.pid, self.thread.thread_id, 3).status, 'DEVELOPING')
        self.assertEqual(ForeshadowStore.get_at(self.canon, self.pid, self.new_thread_id, 3).status, 'OPEN')

    def test_fact_links_character(self):
        self.apply(self.approvals()[:1])
        self.assertEqual(self.canon.list_facts(self.pid, 'character', self.c1.character_id)[0][1],
                         '능력을 얻음')

    def test_fact_links_world(self):
        self.apply(self.approvals()[1:2])
        self.assertEqual(self.canon.list_facts(self.pid, 'world', self.world.entry_id)[0][1],
                         '마을이 확장됨')

    def test_fact_links_timeline(self):
        self.apply(self.approvals()[2:3])
        self.assertEqual(self.canon.list_facts(self.pid, 'timeline', self.timeline.event_id)[0][1],
                         '비가 내림')

    def test_canon_fields_not_overwritten(self):
        self.apply(self.approvals()[:3])
        self.assertEqual(self.canon.get_character(self.pid, self.c1.character_id).goal, '여행')
        self.assertEqual(self.canon.get_entry(self.pid, self.world.entry_id).description, '산 위 도시')
        self.assertEqual(EventTimelineStore.get_event(self.canon, self.pid,
                         self.timeline.event_id).title, '첫 만남')

    def test_idempotent_all(self):
        decisions = self.approvals()
        self.apply(decisions)
        rev = self.canon.get_project(self.pid).revision
        result = self.apply(decisions)
        self.assertEqual((result.applied, result.already_applied), (0, 6))
        self.assertEqual(self.canon.get_project(self.pid).revision, rev)
        self.assertEqual(self.count('bible_memory_applications'), 6)

    def test_partial_then_rest(self):
        decisions = self.approvals()
        self.apply(decisions[:3])
        result = self.apply(decisions[3:])
        self.assertEqual(result.applied, 3)
        self.assertEqual(self.count('bible_memory_applications'), 6)

    def test_replay_subset(self):
        decisions = self.approvals()
        self.apply(decisions[:1])
        self.assertEqual(self.apply(decisions[:1]).already_applied, 1)

    def test_persist_reopen(self):
        decisions = self.approvals()
        self.apply(decisions)
        self.canon.close()
        self.canon = MemoryCanonStore(self.path)
        self.assertEqual(self.apply(decisions).already_applied, 6)

    def test_reject_unreviewed(self):
        self.reviews._db.execute('DELETE FROM memory_delta_reviews')
        self.reviews._db.commit()
        with self.assertRaises(MemoryApplicationError):
            self.apply()

    def test_reject_stale_manuscript(self):
        decisions = self.approvals()
        self.set_text(self.text + '\n수정')
        with self.assertRaises(MemoryApplicationError):
            self.apply(decisions)
        self.assertEqual(self.count('bible_memory_applications'), 0)

    def test_reject_stale_revision(self):
        decisions = self.approvals()
        ep = self.episodes.get_episode(self.pid, 3)
        self.episodes.update_episode(self.pid, 3, expected_revision=ep.revision,
                                     summary='수정')
        with self.assertRaises(MemoryApplicationError):
            self.apply(decisions)

    def test_reject_wrong_approval_reference(self):
        decisions = self.approvals()
        with self.assertRaises(MemoryApplicationError):
            self.canon.apply(self.episodes, self.reviews,
                replace(self.evidence, approval_reference='different-ref-123'), decisions)

    def test_reject_false_approval(self):
        decision = replace(self.approvals()[0], explicitly_approved_by_user=False)
        with self.assertRaises(MemoryApplicationError):
            self.apply((decision,))

    def test_reject_numeric_true(self):
        decision = replace(self.approvals()[0], explicitly_approved_by_user=1)
        with self.assertRaises(MemoryApplicationError):
            self.apply((decision,))

    def test_reject_empty_reviewer_reference(self):
        with self.assertRaises(MemoryApplicationError):
            self.apply((replace(self.approvals()[0], reviewer_reference=''),))

    def test_reject_invalid_change_id(self):
        with self.assertRaises(MemoryApplicationError):
            self.apply((replace(self.approvals()[0], change_id='0'*64),))

    def test_reject_duplicate_decisions(self):
        d = self.approvals()[0]
        with self.assertRaises(MemoryApplicationError):
            self.apply((d, d))

    def test_reject_non_tuple_decisions(self):
        with self.assertRaises(MemoryApplicationError):
            self.apply(list(self.approvals()))

    def test_reject_empty_decisions(self):
        with self.assertRaises(MemoryApplicationError):
            self.apply(())

    def test_reject_wrong_target_kind(self):
        with self.assertRaises(MemoryApplicationError):
            self.apply((replace(self.approvals()[0], target_kind='world'),))

    def test_reject_wrong_target_id(self):
        with self.assertRaises(MemoryApplicationError):
            self.apply((replace(self.approvals()[0], target_id=self.c2.character_id),))

    def test_reject_stale_target_revision(self):
        with self.assertRaises(MemoryApplicationError):
            self.apply((replace(self.approvals()[0], expected_target_revision=100),))

    def test_reject_missing_target(self):
        decisions = self.approvals()
        self.canon.delete_character(self.pid, self.c1.character_id,
                                    expected_revision=self.c1.revision)
        with self.assertRaises(MemoryApplicationError):
            self.apply(decisions[:1])

    def test_reject_existing_relation_same_episode(self):
        self.canon.save_relation(self.pid, self.c1.character_id, self.c2.character_id,
                                 3, relationship='적대')
        with self.assertRaises(MemoryApplicationError):
            self.apply(self.approvals()[3:4])
        self.assertEqual(self.canon.get_event(self.pid, self.c1.character_id,
                         self.c2.character_id, 3).relationship, '적대')

    def test_atomic_rollback_on_relation_conflict(self):
        decisions = self.approvals()
        self.canon.save_relation(self.pid, self.c1.character_id, self.c2.character_id,
                                 3, relationship='적대')
        with self.assertRaises(MemoryApplicationError):
            self.apply(decisions[:4])
        self.assertEqual(self.count('bible_memory_facts'), 0)
        self.assertEqual(self.count('bible_memory_applications'), 0)

    def test_atomic_rollback_on_invalid_foreshadow(self):
        decisions = self.approvals()
        self.canon.add_event(self.pid, self.thread.thread_id, episode=2,
                             action='RESOLVE', note='끝', expected_revision=self.thread.revision)
        decisions = (*decisions[:4], replace(decisions[4], expected_target_revision=2))
        with self.assertRaises(MemoryApplicationError):
            self.apply(decisions[:5])
        self.assertEqual(self.count('bible_memory_facts'), 0)
        self.assertEqual(self.count('bible_memory_applications'), 0)

    def test_foreshadow_install_requires_title(self):
        with self.assertRaises(MemoryApplicationError):
            self.apply((replace(self.approvals()[5], new_thread_title=''),))

    def test_foreshadow_existing_requires_revision(self):
        with self.assertRaises(MemoryApplicationError):
            self.apply((replace(self.approvals()[4], expected_target_revision=None),))

    def test_reject_reapproval_change(self):
        decisions = self.approvals()
        self.apply(decisions[:1])
        with self.assertRaises(MemoryApplicationError):
            self.apply((replace(decisions[0], reviewer_reference='another-reviewer-123'),))
        self.assertEqual(self.count('bible_memory_applications'), 1)

    def test_reject_journal_tamper(self):
        decisions = self.approvals()
        self.apply(decisions[:1])
        self.canon._db.execute('''UPDATE bible_memory_applications SET
            decision_sha256=? WHERE change_id=?''', ('0'*64, decisions[0].change_id))
        self.canon._db.commit()
        with self.assertRaises(MemoryApplicationError):
            self.apply(decisions[:1])

    def test_reject_fact_tamper(self):
        decisions = self.approvals()
        self.apply(decisions[:1])
        self.canon._db.execute('UPDATE bible_memory_facts SET fact_text=?', ('변조',))
        self.canon._db.commit()
        with self.assertRaises(MemoryApplicationError):
            self.apply(decisions[:1])

    def test_reject_relation_tamper(self):
        decisions = self.approvals()
        self.apply(decisions[3:4])
        self.canon._db.execute('UPDATE bible_relationship_events SET relationship=?', ('변조',))
        self.canon._db.commit()
        with self.assertRaises(MemoryApplicationError):
            self.apply(decisions[3:4])

    def test_reject_foreshadow_tamper(self):
        decisions = self.approvals()
        self.apply(decisions[4:5])
        self.canon._db.execute('''UPDATE bible_foreshadow_events SET note=?
            WHERE episode=3''', ('변조',))
        self.canon._db.commit()
        with self.assertRaises(MemoryApplicationError):
            self.apply(decisions[4:5])

    def test_reject_relation_record_id_tamper(self):
        decisions = self.approvals()
        self.apply(decisions[3:4])
        self.canon._db.execute('''UPDATE bible_memory_applications
            SET canon_record_id=? WHERE change_id=?''',
            ('forged', decisions[3].change_id))
        self.canon._db.commit()
        with self.assertRaises(MemoryApplicationError):
            self.apply(decisions[3:4])

    def test_reject_foreshadow_invalid_title(self):
        with self.assertRaises(MemoryApplicationError):
            self.apply((replace(self.approvals()[5], new_thread_title='X'*121),))

    def test_project_isolation(self):
        other = self.canon.create_project('다른 작품').project_id
        decisions = self.approvals()
        with self.assertRaises(MemoryApplicationError):
            self.canon.apply(self.episodes, self.reviews,
                replace(self.evidence, project_id=other), decisions[:1])
        self.assertEqual(self.count('bible_memory_applications'), 0)

    def test_no_manuscript_change(self):
        before = self.episodes.get_episode(self.pid, 3)
        self.apply()
        after = self.episodes.get_episode(self.pid, 3)
        self.assertEqual(before, after)

    def test_missing_fact_target(self):
        with self.assertRaises(MemoryApplicationError):
            self.canon.list_facts(self.pid, 'invalid', self.c1.character_id)

    def test_no_canon_writes_on_invalid_approval(self):
        before = self.canon.get_project(self.pid).revision
        with self.assertRaises(MemoryApplicationError):
            self.apply((replace(self.approvals()[0], explicitly_approved_by_user=False),))
        self.assertEqual(self.canon.get_project(self.pid).revision, before)

    def test_no_private_text_in_error(self):
        try:
            self.apply((replace(self.approvals()[0], target_id='secret manuscript'),))
        except MemoryApplicationError as e:
            self.assertNotIn('secret manuscript', str(e))
        else:
            self.fail('should reject')


if __name__ == '__main__':
    unittest.main()
