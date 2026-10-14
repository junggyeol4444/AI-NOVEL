"""Stage 83 local manuscript versioning regression tests."""
import hashlib
import tempfile
from pathlib import Path
import unittest

from ai_novel_factory.database.episodes import EpisodeStore
from ai_novel_factory.manuscript_versions import ManuscriptVersionStore, ManuscriptVersionError


class VersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'versions.db'
        self.store = ManuscriptVersionStore(self.path)
        self.pid = self.store.create_project('원고').project_id
        self.ep = self.store.create_episode(self.pid, 1)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def save(self, text='초고', kind='DRAFT', **kwargs):
        return self.store.save_version(self.pid, 1, text, kind=kind,
            expected_revision=self.store.get_episode(self.pid, 1).revision, **kwargs)

    def test_draft_version(self):
        v = self.save()
        self.assertEqual((v.kind, v.ordinal, v.episode_revision), ('DRAFT', 1, 2))
        self.assertEqual(self.store.get_episode(self.pid, 1).draft, '초고')

    def test_revision_version(self):
        self.save()
        v = self.save('수정', 'REVISION')
        self.assertEqual((v.ordinal, v.draft), (2, '수정'))

    def test_final_candidate(self):
        self.save()
        v = self.save('최종 후보', 'FINAL')
        self.assertEqual(v.final_text, '최종 후보')
        self.assertFalse(v.publication_approved)

    def test_final_not_publication_approval(self):
        self.assertFalse(self.save('후보', 'FINAL').as_dict()['publication_approved'])

    def test_new_revision_invalidates_final(self):
        self.save('초고')
        self.save('최종', 'FINAL')
        self.save('수정 후', 'REVISION')
        self.assertEqual(self.store.get_episode(self.pid, 1).final_text, '')

    def test_draft_after_final_invalidates(self):
        self.save('최종', 'FINAL')
        self.save('새 초고', 'DRAFT')
        self.assertEqual(self.store.get_episode(self.pid, 1).final_text, '')

    def test_final_preserves_draft(self):
        self.save('초고')
        self.save('최종', 'FINAL')
        self.assertEqual(self.store.get_episode(self.pid, 1).draft, '초고')

    def test_history_preserves_original(self):
        a = self.save('이전')
        self.save('이후', 'REVISION')
        self.assertEqual(self.store.get_version(self.pid, 1, a.version_id).draft, '이전')

    def test_ordinal_order(self):
        for text, kind in [('하나','DRAFT'),('둘','REVISION'),('셋','FINAL')]:
            self.save(text,kind)
        self.assertEqual([v.ordinal for v in self.store.list_versions(self.pid,1)], [1,2,3])

    def test_reopen_persistence(self):
        v = self.save('보존')
        self.store.close()
        self.store = ManuscriptVersionStore(self.path)
        self.assertEqual(self.store.get_version(self.pid,1,v.version_id).draft, '보존')

    def test_redaction_default(self):
        v = self.save('민감 원고', note='민감 주석')
        self.assertNotIn('민감', str(v.as_dict()))

    def test_explicit_reveal(self):
        v = self.save('원고 내용', note='편집자 주석')
        self.assertEqual(v.as_dict(reveal=True)['draft'], '원고 내용')

    def test_fingerprint_sha256(self):
        v = self.save()
        self.assertEqual(len(v.fingerprint), 64)
        int(v.fingerprint,16)

    def test_duplicate_rejected(self):
        self.save()
        with self.assertRaises(ManuscriptVersionError):
            self.save()
        self.assertEqual(len(self.store.list_versions(self.pid,1)), 1)

    def test_empty_rejected(self):
        with self.assertRaises(ManuscriptVersionError):
            self.save('')

    def test_whitespace_rejected(self):
        with self.assertRaises(ManuscriptVersionError):
            self.save('  \n ')

    def test_invalid_kind_rejected(self):
        with self.assertRaises(ManuscriptVersionError):
            self.save('x','APPROVED')

    def test_baseline_kind_not_writable(self):
        with self.assertRaises(ManuscriptVersionError):
            self.save('x','BASELINE')

    def test_invalid_type(self):
        with self.assertRaises(ManuscriptVersionError):
            self.save('x', None)

    def test_invalid_note(self):
        with self.assertRaises(ManuscriptVersionError):
            self.save('x', note='x'*2049)

    def test_control_characters(self):
        with self.assertRaises(ManuscriptVersionError):
            self.save('x\x00y')

    def test_oversized(self):
        with self.assertRaises(ManuscriptVersionError):
            self.save('한'*200_000)

    def test_revision_conflict(self):
        self.save()
        with self.assertRaises(ManuscriptVersionError):
            self.store.save_version(self.pid,1,'new',kind='REVISION',expected_revision=1)

    def test_no_change_on_revision_conflict(self):
        self.save()
        before = self.store.get_episode(self.pid,1)
        with self.assertRaises(ManuscriptVersionError):
            self.store.save_version(self.pid,1,'new',kind='REVISION',expected_revision=1)
        self.assertEqual(self.store.get_episode(self.pid,1), before)

    def test_existing_draft_requires_baseline(self):
        self.store.update_episode(self.pid,1,expected_revision=1,draft='기존')
        with self.assertRaises(ManuscriptVersionError):
            self.save('새 원고')

    def test_capture_existing_draft(self):
        self.store.update_episode(self.pid,1,expected_revision=1,draft='기존')
        baseline = self.store.capture_current(self.pid,1,expected_revision=2)
        self.assertEqual((baseline.kind,baseline.draft),('BASELINE','기존'))
        self.assertEqual(self.save('새 원고').ordinal,2)

    def test_capture_existing_final(self):
        self.store.update_episode(self.pid,1,expected_revision=1,final_text='기존 최종')
        baseline = self.store.capture_current(self.pid,1,expected_revision=2)
        self.assertEqual(baseline.final_text,'기존 최종')
        self.save('새 수정', 'REVISION')
        self.assertEqual(self.store.get_episode(self.pid,1).final_text,'')

    def test_capture_preserves_revision(self):
        self.store.update_episode(self.pid,1,expected_revision=1,draft='기존')
        self.store.capture_current(self.pid,1,expected_revision=2)
        self.assertEqual(self.store.get_episode(self.pid,1).revision,2)

    def test_capture_twice_rejected(self):
        self.store.update_episode(self.pid,1,expected_revision=1,draft='기존')
        self.store.capture_current(self.pid,1,expected_revision=2)
        with self.assertRaises(ManuscriptVersionError):
            self.store.capture_current(self.pid,1,expected_revision=2)

    def test_capture_empty_rejected(self):
        with self.assertRaises(ManuscriptVersionError):
            self.store.capture_current(self.pid,1,expected_revision=1)

    def test_capture_stale_rejected(self):
        self.store.update_episode(self.pid,1,expected_revision=1,draft='기존')
        with self.assertRaises(ManuscriptVersionError):
            self.store.capture_current(self.pid,1,expected_revision=1)

    def test_external_update_detected(self):
        self.save()
        external = EpisodeStore(self.path)
        try:
            external.update_episode(self.pid,1,expected_revision=2,draft='우회')
        finally:
            external.close()
        with self.assertRaises(ManuscriptVersionError):
            self.save('이후', 'REVISION')

    def test_external_scene_edit_detected(self):
        self.save()
        self.store.add_scene(self.pid,1,1,'장면',expected_revision=2)
        with self.assertRaises(ManuscriptVersionError):
            self.save('이후', 'REVISION')

    def test_external_same_revision_tamper_detected(self):
        self.save()
        with self.store._db:
            self.store._db.execute('UPDATE bible_episodes SET draft=? WHERE project_id=? AND episode=?',
                                   ('조작',self.pid,1))
        with self.assertRaises(ManuscriptVersionError):
            self.save('이후', 'REVISION')

    def test_history_text_tamper_detected(self):
        v = self.save()
        self.store._db.execute('UPDATE bible_manuscript_versions SET draft=? WHERE version_id=?',
                               ('조작',v.version_id))
        with self.assertRaises(ManuscriptVersionError):
            self.store.list_versions(self.pid,1)

    def test_history_kind_tamper_detected(self):
        v = self.save()
        self.store._db.execute('UPDATE bible_manuscript_versions SET kind=? WHERE version_id=?',
                               ('FINAL',v.version_id))
        with self.assertRaises(ManuscriptVersionError):
            self.store.list_versions(self.pid,1)

    def test_history_note_tamper_detected(self):
        v = self.save(note='정상')
        self.store._db.execute('UPDATE bible_manuscript_versions SET note=? WHERE version_id=?',
                               ('조작',v.version_id))
        with self.assertRaises(ManuscriptVersionError):
            self.store.list_versions(self.pid,1)

    def test_missing_version(self):
        with self.assertRaises(ManuscriptVersionError):
            self.store.get_version(self.pid,1,'f'*32)

    def test_cross_project_access(self):
        v = self.save()
        other = self.store.create_project('다른 작품').project_id
        self.store.create_episode(other,1)
        with self.assertRaises(ManuscriptVersionError):
            self.store.get_version(other,1,v.version_id)

    def test_cross_episode_access(self):
        v = self.save()
        self.store.create_episode(self.pid,2)
        with self.assertRaises(ManuscriptVersionError):
            self.store.get_version(self.pid,2,v.version_id)

    def test_restore_creates_new_version(self):
        old = self.save('옛날')
        self.save('새 버전','REVISION')
        restored = self.store.restore_as_revision(self.pid,1,old.version_id,expected_revision=3)
        self.assertEqual((restored.kind,restored.ordinal,restored.draft),('REVISION',3,'옛날'))
        self.assertEqual(len(self.store.list_versions(self.pid,1)),3)

    def test_restore_final_as_draft(self):
        v = self.save('최종 후보','FINAL')
        self.save('새 초고','DRAFT')
        restored = self.store.restore_as_revision(self.pid,1,v.version_id,expected_revision=3)
        self.assertEqual(restored.draft,'최종 후보')
        self.assertEqual(restored.final_text,'')
        self.assertFalse(restored.publication_approved)

    def test_restore_stale_rejected(self):
        old = self.save('옛날')
        self.save('새 버전','REVISION')
        with self.assertRaises(ManuscriptVersionError):
            self.store.restore_as_revision(self.pid,1,old.version_id,expected_revision=2)

    def test_restore_same_content_rejected(self):
        v = self.save('옛날')
        with self.assertRaises(ManuscriptVersionError):
            self.store.restore_as_revision(self.pid,1,v.version_id,expected_revision=2)

    def test_delete_with_history_rejected(self):
        self.save()
        with self.assertRaises(ManuscriptVersionError):
            self.store.delete_episode(self.pid,1,expected_revision=2)

    def test_delete_without_history_allowed(self):
        self.store.delete_episode(self.pid,1,expected_revision=1)
        self.assertEqual(self.store.list_episodes(self.pid),())

    def test_project_revision_bumped_once(self):
        before = self.store.get_project(self.pid).revision
        self.save()
        self.assertEqual(self.store.get_project(self.pid).revision,before+1)

    def test_no_unwanted_final_or_export(self):
        v = self.save('초고')
        self.assertEqual(self.store.get_episode(self.pid,1).final_text,'')
        self.assertEqual(v.as_dict()['final_text'],'[redacted]')

    def test_atomic_insert_failure_rollback(self):
        # An injected DB failure after episode UPDATE must roll back both changes.
        self.store._db.execute('''CREATE TRIGGER reject_version BEFORE INSERT ON bible_manuscript_versions
            BEGIN SELECT RAISE(ABORT, 'blocked'); END''')
        before = self.store.get_episode(self.pid,1)
        project_before = self.store.get_project(self.pid).revision
        with self.assertRaises(Exception):
            self.save('초고')
        self.assertEqual(self.store.get_episode(self.pid,1),before)
        self.assertEqual(self.store.get_project(self.pid).revision,project_before)
        self.assertEqual(len(self.store.list_versions(self.pid,1)),0)

    def test_no_duplicate_on_failed_write(self):
        self.save()
        with self.assertRaises(ManuscriptVersionError):
            self.save()
        self.assertEqual([v.ordinal for v in self.store.list_versions(self.pid,1)],[1])

    def test_notes_preserved(self):
        v = self.save('초고',note='수동 편집')
        self.assertEqual(self.store.get_version(self.pid,1,v.version_id).note,'수동 편집')

    def test_episode_revision_in_history(self):
        a = self.save('a');b = self.save('b','REVISION')
        self.assertEqual((a.episode_revision,b.episode_revision),(2,3))

    def test_no_original_source_ingestion(self):
        self.save('사용자 원고')
        self.assertEqual(self.store.list_versions(self.pid,1)[0].draft,'사용자 원고')


if __name__ == '__main__':
    unittest.main()
