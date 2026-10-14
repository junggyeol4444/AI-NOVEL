"""Stage 47 / ANF-REQ-037: authored foreshadowing state transitions and persistence."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from ai_novel_factory.database.foreshadow import (
    ACTIONS, FINAL, STATUSES, ForeshadowError, ForeshadowStore,
    _action, _episode, _note, _status_after, _title,
)
from ai_novel_factory.database.foreshadow_cli import main as cli
from ai_novel_factory.database.novel_bible import NovelBibleError, NovelBibleStore


class ForeshadowTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.path = self.folder / "canon.db"
        self.store = ForeshadowStore(self.path)
        self.addCleanup(self.store.close)
        self.project = self.store.create_project("내 작품").project_id

    def thread(self, episode=2, title="사용자 복선", project=None, note="설치 메모"):
        return self.store.create_thread(project or self.project, title=title,
                                        episode=episode, note=note)

    def add(self, item, episode, action, note="후속 메모", project=None, revision=None):
        return self.store.add_event(project or self.project, item.thread_id,
            episode=episode, action=action, note=note,
            expected_revision=revision if revision is not None else
            self.store.get_thread(project or self.project, item.thread_id).revision)

    def test_no_threads(self):
        report = self.store.audit(self.project)
        self.assertEqual((report.thread_count, report.event_count), (0, 0))
        self.assertEqual(report.unfinished_thread_ids, ())

    def test_thread_create(self):
        item = self.thread()
        self.assertEqual(item.revision, 1)
        self.assertEqual(item.title, "사용자 복선")
        self.assertEqual(self.store.get_thread(self.project, item.thread_id), item)

    def test_create_adds_install(self):
        item = self.thread()
        events = self.store.history(self.project, item.thread_id)
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0].episode, events[0].action), (2, "INSTALL"))
        self.assertEqual(events[0].note, "설치 메모")

    def test_before_install_is_unknown(self):
        item = self.thread(5)
        state = self.store.get_at(self.project, item.thread_id, 4)
        self.assertEqual(state.status, "NOT_INSTALLED")
        self.assertIsNone(state.effective_episode)
        self.assertIsNone(state.last_action)

    def test_at_install_open(self):
        item = self.thread()
        self.assertEqual(self.store.get_at(self.project, item.thread_id, 2).status, "OPEN")

    def test_open_persists(self):
        item = self.thread()
        self.assertEqual(self.store.get_at(self.project, item.thread_id, 20).status, "OPEN")

    def test_revisit_developing(self):
        item = self.thread()
        self.add(item, 3, "REVISIT")
        self.assertEqual(self.store.get_at(self.project, item.thread_id, 3).status, "DEVELOPING")

    def test_developing_persists(self):
        item = self.thread()
        self.add(item, 3, "REVISIT")
        self.assertEqual(self.store.get_at(self.project, item.thread_id, 40).status, "DEVELOPING")

    def test_multiple_revisits(self):
        item = self.thread()
        self.add(item, 3, "REVISIT")
        self.add(item, 5, "REVISIT")
        self.assertEqual(self.store.get_at(self.project, item.thread_id, 4).effective_episode, 3)
        self.assertEqual(self.store.get_at(self.project, item.thread_id, 5).effective_episode, 5)

    def test_resolve_directly_from_open(self):
        item = self.thread()
        self.add(item, 3, "RESOLVE")
        self.assertEqual(self.store.get_at(self.project, item.thread_id, 3).status, "RESOLVED")

    def test_resolve_after_revisit(self):
        item = self.thread()
        self.add(item, 3, "REVISIT")
        self.add(item, 7, "RESOLVE")
        self.assertEqual(self.store.get_at(self.project, item.thread_id, 6).status, "DEVELOPING")
        self.assertEqual(self.store.get_at(self.project, item.thread_id, 7).status, "RESOLVED")

    def test_abandon_directly_from_open(self):
        item = self.thread()
        self.add(item, 3, "ABANDON")
        self.assertEqual(self.store.get_at(self.project, item.thread_id, 3).status, "ABANDONED")

    def test_abandon_after_revisit(self):
        item = self.thread()
        self.add(item, 3, "REVISIT")
        self.add(item, 7, "ABANDON")
        self.assertEqual(self.store.get_at(self.project, item.thread_id, 7).status, "ABANDONED")

    def test_cannot_revisit_after_resolve(self):
        item = self.thread()
        self.add(item, 3, "RESOLVE")
        with self.assertRaises(ForeshadowError):
            self.add(item, 4, "REVISIT")
        self.assertEqual(len(self.store.history(self.project, item.thread_id)), 2)

    def test_cannot_resolve_twice(self):
        item = self.thread()
        self.add(item, 3, "RESOLVE")
        with self.assertRaises(ForeshadowError):
            self.add(item, 4, "RESOLVE")

    def test_cannot_abandon_after_resolve(self):
        item = self.thread()
        self.add(item, 3, "RESOLVE")
        with self.assertRaises(ForeshadowError):
            self.add(item, 4, "ABANDON")

    def test_cannot_resolve_after_abandon(self):
        item = self.thread()
        self.add(item, 3, "ABANDON")
        with self.assertRaises(ForeshadowError):
            self.add(item, 4, "RESOLVE")

    def test_cannot_revisit_after_abandon(self):
        item = self.thread()
        self.add(item, 3, "ABANDON")
        with self.assertRaises(ForeshadowError):
            self.add(item, 4, "REVISIT")

    def test_cannot_install_twice(self):
        item = self.thread()
        with self.assertRaises(ForeshadowError):
            self.add(item, 3, "INSTALL")

    def test_cannot_backdate_before_install(self):
        item = self.thread(3)
        with self.assertRaises(ForeshadowError):
            self.add(item, 2, "REVISIT")

    def test_backfill_valid_earlier_episode(self):
        item = self.thread(1)
        self.add(item, 8, "RESOLVE")
        self.add(item, 3, "REVISIT")
        self.assertEqual(self.store.get_at(self.project, item.thread_id, 5).status, "DEVELOPING")
        self.assertEqual(self.store.get_at(self.project, item.thread_id, 9).status, "RESOLVED")

    def test_backfill_after_terminal_rejected(self):
        item = self.thread(1)
        self.add(item, 8, "RESOLVE")
        with self.assertRaises(ForeshadowError):
            self.add(item, 9, "REVISIT")

    def test_same_episode_revisit_then_resolve(self):
        item = self.thread(1)
        self.add(item, 2, "REVISIT")
        self.add(item, 2, "RESOLVE")
        self.assertEqual(self.store.get_at(self.project, item.thread_id, 2).status, "RESOLVED")

    def test_same_episode_resolve_then_revisit_rejected(self):
        item = self.thread(1)
        self.add(item, 2, "RESOLVE")
        with self.assertRaises(ForeshadowError):
            self.add(item, 2, "REVISIT")

    def test_same_episode_install_then_revisit(self):
        item = self.thread(1)
        self.add(item, 1, "REVISIT")
        self.assertEqual(self.store.get_at(self.project, item.thread_id, 1).status, "DEVELOPING")

    def test_same_episode_insert_sequence(self):
        item = self.thread(1)
        first = self.add(item, 2, "REVISIT")
        second = self.add(item, 2, "RESOLVE")
        self.assertLess(first.sequence, second.sequence)

    def test_history_sorted_by_episode_then_sequence(self):
        item = self.thread(1)
        self.add(item, 8, "RESOLVE")
        self.add(item, 3, "REVISIT")
        self.assertEqual([e.episode for e in self.store.history(self.project, item.thread_id)],
                         [1, 3, 8])

    def test_thread_revision_bumps(self):
        item = self.thread(1)
        self.add(item, 2, "REVISIT")
        self.assertEqual(self.store.get_thread(self.project, item.thread_id).revision, 2)

    def test_project_revision_bumps(self):
        initial = self.store.get_project(self.project).revision
        item = self.thread(1)
        self.add(item, 2, "REVISIT")
        self.assertEqual(self.store.get_project(self.project).revision, initial + 2)

    def test_invalid_action_rolls_back_revision(self):
        item = self.thread()
        before = self.store.get_project(self.project).revision
        with self.assertRaises(ForeshadowError):
            self.add(item, 3, "INSTALL")
        self.assertEqual(self.store.get_project(self.project).revision, before)
        self.assertEqual(self.store.get_thread(self.project, item.thread_id).revision, 1)

    def test_terminal_failure_rolls_back_revision(self):
        item = self.thread()
        self.add(item, 3, "RESOLVE")
        before = self.store.get_project(self.project).revision
        with self.assertRaises(ForeshadowError):
            self.add(item, 4, "ABANDON")
        self.assertEqual(self.store.get_project(self.project).revision, before)
        self.assertEqual(self.store.get_thread(self.project, item.thread_id).revision, 2)

    def test_stale_revision_rejected(self):
        item = self.thread()
        self.add(item, 3, "REVISIT")
        with self.assertRaises(ForeshadowError):
            self.add(item, 4, "RESOLVE", revision=1)

    def test_missing_revision_rejected(self):
        item = self.thread()
        with self.assertRaises(NovelBibleError):
            self.store.add_event(self.project, item.thread_id, episode=3,
                                 action="REVISIT", expected_revision=None)

    def test_two_connections_conflict(self):
        item = self.thread()
        with ForeshadowStore(self.path) as other:
            other.add_event(self.project, item.thread_id, episode=3,
                            action="REVISIT", expected_revision=1)
            with self.assertRaises(ForeshadowError):
                self.store.add_event(self.project, item.thread_id, episode=4,
                                     action="RESOLVE", expected_revision=1)

    def test_project_isolation(self):
        item = self.thread()
        other_project = self.store.create_project("다른 작품").project_id
        with self.assertRaises(ForeshadowError):
            self.store.get_thread(other_project, item.thread_id)
        with self.assertRaises(ForeshadowError):
            self.store.add_event(other_project, item.thread_id, episode=3,
                                 action="REVISIT", expected_revision=1)
        self.assertEqual(self.store.audit(other_project).thread_count, 0)

    def test_two_threads_independent(self):
        a = self.thread(title="첫 복선")
        b = self.thread(title="둘째 복선")
        self.add(a, 3, "RESOLVE")
        self.add(b, 4, "ABANDON")
        self.assertEqual(self.store.get_at(self.project, a.thread_id, 10).status, "RESOLVED")
        self.assertEqual(self.store.get_at(self.project, b.thread_id, 10).status, "ABANDONED")

    def test_audit_counts_all_statuses(self):
        a = self.thread(title="A")
        b = self.thread(title="B")
        c = self.thread(title="C")
        d = self.thread(title="D")
        self.add(b, 3, "REVISIT")
        self.add(c, 3, "RESOLVE")
        self.add(d, 3, "ABANDON")
        report = self.store.audit(self.project)
        self.assertEqual((report.thread_count, report.event_count), (4, 7))
        self.assertEqual((report.open_count, report.developing_count,
                          report.resolved_count, report.abandoned_count), (1, 1, 1, 1))
        self.assertEqual(set(report.unfinished_thread_ids), {a.thread_id, b.thread_id})

    def test_audit_closed_empty_unfinished(self):
        item = self.thread()
        self.add(item, 3, "RESOLVE")
        self.assertEqual(self.store.audit(self.project).unfinished_thread_ids, ())

    def test_update_title(self):
        item = self.thread()
        updated = self.store.update_thread(self.project, item.thread_id,
                                           title="바뀐 제목", expected_revision=1)
        self.assertEqual((updated.title, updated.revision), ("바뀐 제목", 2))

    def test_update_title_stale(self):
        item = self.thread()
        self.store.update_thread(self.project, item.thread_id,
                                 title="바뀐 제목", expected_revision=1)
        with self.assertRaises(ForeshadowError):
            self.store.update_thread(self.project, item.thread_id,
                                     title="이전 버전", expected_revision=1)

    def test_update_event_note(self):
        item = self.thread()
        event = self.add(item, 3, "REVISIT")
        updated = self.store.update_event(self.project, item.thread_id, event.event_id,
            episode=3, action="REVISIT", note="변경", expected_revision=2)
        self.assertEqual(updated.note, "변경")
        self.assertEqual(self.store.get_thread(self.project, item.thread_id).revision, 3)

    def test_update_event_episode(self):
        item = self.thread()
        event = self.add(item, 5, "REVISIT")
        self.store.update_event(self.project, item.thread_id, event.event_id,
            episode=3, action="REVISIT", expected_revision=2)
        self.assertEqual(self.store.get_at(self.project, item.thread_id, 4).status, "DEVELOPING")

    def test_update_event_terminal_action(self):
        item = self.thread()
        event = self.add(item, 3, "RESOLVE")
        self.store.update_event(self.project, item.thread_id, event.event_id,
            episode=3, action="ABANDON", expected_revision=2)
        self.assertEqual(self.store.get_at(self.project, item.thread_id, 4).status, "ABANDONED")

    def test_update_event_invalid_transition_rolls_back(self):
        item = self.thread()
        revisit = self.add(item, 3, "REVISIT")
        self.add(item, 5, "RESOLVE")
        with self.assertRaises(ForeshadowError):
            self.store.update_event(self.project, item.thread_id, revisit.event_id,
                episode=6, action="REVISIT", expected_revision=3)
        self.assertEqual(self.store.get_event(self.project, item.thread_id,
                                              revisit.event_id).episode, 3)
        self.assertEqual(self.store.get_thread(self.project, item.thread_id).revision, 3)

    def test_update_install_episode(self):
        item = self.thread(3)
        install = self.store.history(self.project, item.thread_id)[0]
        self.store.update_event(self.project, item.thread_id, install.event_id,
            episode=1, action="INSTALL", note="설치", expected_revision=1)
        self.assertEqual(self.store.get_at(self.project, item.thread_id, 1).status, "OPEN")

    def test_cannot_change_install_to_revisit(self):
        item = self.thread()
        install = self.store.history(self.project, item.thread_id)[0]
        with self.assertRaises(ForeshadowError):
            self.store.update_event(self.project, item.thread_id, install.event_id,
                episode=2, action="REVISIT", expected_revision=1)

    def test_cannot_change_revisit_to_install(self):
        item = self.thread()
        revisit = self.add(item, 3, "REVISIT")
        with self.assertRaises(ForeshadowError):
            self.store.update_event(self.project, item.thread_id, revisit.event_id,
                episode=3, action="INSTALL", expected_revision=2)

    def test_update_event_stale(self):
        item = self.thread()
        event = self.add(item, 3, "REVISIT")
        with self.assertRaises(ForeshadowError):
            self.store.update_event(self.project, item.thread_id, event.event_id,
                episode=4, action="REVISIT", expected_revision=1)

    def test_delete_revisit(self):
        item = self.thread()
        event = self.add(item, 3, "REVISIT")
        self.store.delete_event(self.project, item.thread_id, event.event_id,
                                expected_revision=2)
        self.assertEqual(self.store.get_at(self.project, item.thread_id, 10).status, "OPEN")

    def test_delete_resolve(self):
        item = self.thread()
        event = self.add(item, 3, "RESOLVE")
        self.store.delete_event(self.project, item.thread_id, event.event_id,
                                expected_revision=2)
        self.assertEqual(self.store.get_at(self.project, item.thread_id, 10).status, "OPEN")

    def test_delete_install_rejected(self):
        item = self.thread()
        install = self.store.history(self.project, item.thread_id)[0]
        with self.assertRaises(ForeshadowError):
            self.store.delete_event(self.project, item.thread_id, install.event_id,
                                    expected_revision=1)

    def test_delete_event_stale(self):
        item = self.thread()
        event = self.add(item, 3, "REVISIT")
        with self.assertRaises(ForeshadowError):
            self.store.delete_event(self.project, item.thread_id, event.event_id,
                                    expected_revision=1)

    def test_delete_thread(self):
        item = self.thread()
        self.add(item, 3, "REVISIT")
        self.store.delete_thread(self.project, item.thread_id, expected_revision=2)
        self.assertEqual(self.store.audit(self.project).event_count, 0)
        with self.assertRaises(ForeshadowError):
            self.store.get_thread(self.project, item.thread_id)

    def test_delete_thread_stale(self):
        item = self.thread()
        with self.assertRaises(ForeshadowError):
            self.store.delete_thread(self.project, item.thread_id, expected_revision=2)

    def test_delete_project_cascades(self):
        item = self.thread()
        self.add(item, 3, "REVISIT")
        self.store.delete_project(self.project)
        self.assertEqual(self.store._db.execute("SELECT COUNT(*) FROM bible_foreshadow_events").fetchone()[0], 0)
        self.assertEqual(self.store._db.execute("SELECT COUNT(*) FROM bible_foreshadow_threads").fetchone()[0], 0)

    def test_reopen_database(self):
        item = self.thread()
        self.add(item, 3, "REVISIT")
        self.add(item, 5, "RESOLVE")
        with ForeshadowStore(self.path) as other:
            self.assertEqual(other.get_at(self.project, item.thread_id, 5).status, "RESOLVED")
            self.assertEqual(len(other.history(self.project, item.thread_id)), 3)

    def test_shared_novel_bible(self):
        item = self.thread()
        with NovelBibleStore(self.path) as bible:
            bible.save_rule(self.project, "setting", "내 설정")
            self.assertEqual(bible.get_rule(self.project, "setting").value, "내 설정")
        self.assertEqual(self.store.get_thread(self.project, item.thread_id).title, "사용자 복선")

    def test_corrupt_action_detected(self):
        item = self.thread()
        self.store._db.execute("PRAGMA ignore_check_constraints=ON")
        self.store._db.execute("UPDATE bible_foreshadow_events SET action='WRONG'")
        self.store._db.commit()
        with self.assertRaises(ForeshadowError):
            self.store.audit(self.project)

    def test_corrupt_sequence_detected(self):
        self.thread()
        self.store._db.execute("PRAGMA ignore_check_constraints=ON")
        self.store._db.execute("UPDATE bible_foreshadow_events SET sequence=0")
        self.store._db.commit()
        with self.assertRaises(ForeshadowError):
            self.store.audit(self.project)

    def test_corrupt_history_detected(self):
        item = self.thread()
        self.store._db.execute("DELETE FROM bible_foreshadow_events")
        self.store._db.commit()
        with self.assertRaises(ForeshadowError):
            self.store.get_at(self.project, item.thread_id, 4)

    def test_invalid_episode(self):
        for episode in (0, -1, 1000001, 1.0, True, None, "1"):
            with self.subTest(episode=episode), self.assertRaises(ForeshadowError):
                _episode(episode)

    def test_invalid_action(self):
        for action in ("install", "OPEN", "DEVELOPING", "RESOLVED", "ABANDONED",
                       "", None, 1, True):
            with self.subTest(action=action), self.assertRaises(ForeshadowError):
                _action(action)

    def test_valid_actions(self):
        self.assertEqual(ACTIONS, {"INSTALL", "REVISIT", "RESOLVE", "ABANDON"})

    def test_valid_statuses(self):
        self.assertEqual(STATUSES, {"OPEN", "DEVELOPING", "RESOLVED", "ABANDONED"})
        self.assertEqual(FINAL, {"RESOLVED", "ABANDONED"})

    def test_invalid_titles(self):
        for title in ("", "  ", "x" * 121, "a\nline", "\x00", None, 1):
            with self.subTest(title=str(title)[:8]), self.assertRaises(ForeshadowError):
                _title(title)

    def test_invalid_notes(self):
        for note in (None, "x" * 4001, "\x00", "\x1b", True, 1):
            with self.subTest(note=str(note)[:8]), self.assertRaises(ForeshadowError):
                _note(note)

    def test_empty_note_allowed(self):
        self.assertEqual(_note(""), "")

    def test_unicode_text(self):
        item = self.thread(title="등장인물의 비밀 🔍", note="비밀 장치 🗝️")
        self.assertEqual(self.store.get_thread(self.project, item.thread_id).title,
                         "등장인물의 비밀 🔍")

    def test_state_machine_install_only_initial(self):
        self.assertEqual(_status_after(None, "INSTALL"), "OPEN")
        with self.assertRaises(ForeshadowError):
            _status_after("OPEN", "INSTALL")

    def test_state_machine_no_missing_install(self):
        for action in ("REVISIT", "RESOLVE", "ABANDON"):
            with self.subTest(action=action), self.assertRaises(ForeshadowError):
                _status_after(None, action)

    def test_state_machine_no_reopening(self):
        for status in FINAL:
            for action in ACTIONS:
                with self.subTest(status=status, action=action), self.assertRaises(ForeshadowError):
                    _status_after(status, action)

    def test_id_validation(self):
        with self.assertRaises(NovelBibleError):
            self.store.get_thread("bad", "bad")

    def test_missing_thread(self):
        with self.assertRaises(ForeshadowError):
            self.store.get_thread(self.project, "a" * 32)

    def test_missing_event(self):
        item = self.thread()
        with self.assertRaises(ForeshadowError):
            self.store.get_event(self.project, item.thread_id, "a" * 32)

    def test_max_threads_audit_fails_closed(self):
        # Direct fixture insertion avoids 512 repeated audits.
        now = self.store.get_thread(self.project, self.thread().thread_id).created_at
        with self.store._db:
            for i in range(512):
                uid = f"{i+1000:032x}"
                eid = f"{i+3000:032x}"
                self.store._db.execute("INSERT INTO bible_foreshadow_threads VALUES (?,?,?,1,?,?)",
                    (self.project, uid, "fixture", now, now))
                self.store._db.execute("""INSERT INTO bible_foreshadow_events VALUES
                    (?,?,?,?,1,'INSTALL','',?)""", (self.project, uid, eid, 1, now))
        with self.assertRaises(ForeshadowError):
            self.store.audit(self.project)

    def test_failed_creation_no_partial_rows(self):
        before = self.store.audit(self.project)
        with self.assertRaises(ForeshadowError):
            self.store.create_thread(self.project, title="", episode=1)
        self.assertEqual(self.store.audit(self.project), before)

    def test_finite_state_machine_exhaustive(self):
        self.assertEqual(_status_after("OPEN", "REVISIT"), "DEVELOPING")
        self.assertEqual(_status_after("DEVELOPING", "REVISIT"), "DEVELOPING")
        for source in ("OPEN", "DEVELOPING"):
            self.assertEqual(_status_after(source, "RESOLVE"), "RESOLVED")
            self.assertEqual(_status_after(source, "ABANDON"), "ABANDONED")


class ForeshadowCLITests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.db = self.folder / "canon.db"
        with ForeshadowStore(self.db) as store:
            self.project = store.create_project("작품").project_id
        self.title_file = self.folder / "title.txt"
        self.title_file.write_text("은밀한 실마리\n", encoding="utf-8")
        self.note_file = self.folder / "note.txt"
        self.note_file.write_text("사용자만 아는 비밀 메모", encoding="utf-8")

    def run_cli(self, *args):
        out = StringIO()
        with redirect_stdout(out):
            code = cli(["--database", str(self.db), *args])
        return code, out.getvalue()

    def create(self):
        code, out = self.run_cli("thread-create", self.project,
            "--episode", "2", "--title-file", str(self.title_file),
            "--note-file", str(self.note_file))
        self.assertEqual(code, 0)
        return out.split()[1]

    def test_cli_create(self):
        self.assertEqual(len(self.create()), 32)

    def test_cli_create_no_title_leak(self):
        code, out = self.run_cli("thread-create", self.project, "--episode", "2",
                                 "--title-file", str(self.title_file))
        self.assertEqual(code, 0)
        self.assertNotIn("은밀한", out)

    def test_cli_list_redacted(self):
        self.create()
        code, out = self.run_cli("thread-list", self.project)
        self.assertEqual(code, 0)
        self.assertNotIn("은밀한", out)

    def test_cli_show_redacted(self):
        uid = self.create()
        code, out = self.run_cli("thread-show", self.project, uid)
        self.assertEqual(code, 0)
        self.assertNotIn("은밀한", out)

    def test_cli_show_reveal(self):
        uid = self.create()
        code, out = self.run_cli("thread-show", self.project, uid, "--reveal")
        self.assertEqual(code, 0)
        self.assertIn("은밀한", out)

    def test_cli_history_redacted(self):
        uid = self.create()
        code, out = self.run_cli("thread-history", self.project, uid)
        self.assertEqual(code, 0)
        self.assertIn("INSTALL", out)
        self.assertNotIn("비밀 메모", out)

    def test_cli_history_reveal(self):
        uid = self.create()
        code, out = self.run_cli("thread-history", self.project, uid, "--reveal")
        self.assertEqual(code, 0)
        self.assertIn("비밀 메모", out)

    def test_cli_status(self):
        uid = self.create()
        code, out = self.run_cli("thread-status", self.project, uid, "--episode", "2")
        self.assertEqual(code, 0)
        self.assertIn("OPEN", out)

    def test_cli_event_add(self):
        uid = self.create()
        code, out = self.run_cli("event-add", self.project, uid, "--episode", "3",
                                 "--event-action", "REVISIT", "--revision", "1")
        self.assertEqual(code, 0)
        self.assertIn("saved", out)

    def test_cli_event_update(self):
        uid = self.create()
        with ForeshadowStore(self.db) as store:
            event = store.add_event(self.project, uid, episode=3,
                                    action="REVISIT", expected_revision=1)
        code, out = self.run_cli("event-update", self.project, uid, event.event_id,
                                 "--episode", "4", "--event-action", "RESOLVE",
                                 "--revision", "2")
        self.assertEqual(code, 0)
        self.assertIn("saved", out)

    def test_cli_event_delete(self):
        uid = self.create()
        with ForeshadowStore(self.db) as store:
            event = store.add_event(self.project, uid, episode=3,
                                    action="REVISIT", expected_revision=1)
        code, out = self.run_cli("event-delete", self.project, uid, event.event_id,
                                 "--revision", "2")
        self.assertEqual(code, 0)
        self.assertIn("deleted", out)

    def test_cli_thread_update(self):
        uid = self.create()
        code, out = self.run_cli("thread-update", self.project, uid,
            "--title-file", str(self.title_file), "--revision", "1")
        self.assertEqual(code, 0)
        self.assertIn("revision 2", out)

    def test_cli_thread_delete(self):
        uid = self.create()
        code, out = self.run_cli("thread-delete", self.project, uid, "--revision", "1")
        self.assertEqual(code, 0)
        self.assertIn("deleted", out)

    def test_cli_audit(self):
        self.create()
        code, out = self.run_cli("foreshadow-audit", self.project)
        self.assertEqual(code, 0)
        self.assertIn("OPEN 1", out)

    def test_cli_stale_revision_error_redacted(self):
        uid = self.create()
        code, out = self.run_cli("thread-delete", self.project, uid, "--revision", "2")
        self.assertEqual(code, 1)
        self.assertNotIn("은밀한", out)
        self.assertNotIn("비밀 메모", out)

    def test_cli_missing_file_error(self):
        code, out = self.run_cli("thread-create", self.project, "--episode", "1",
                                 "--title-file", str(self.folder / "missing.txt"))
        self.assertEqual(code, 1)
        self.assertIn("ERROR", out)

    def test_cli_subprocess_offline(self):
        import os
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        result = subprocess.run([sys.executable, "-m",
            "ai_novel_factory.database.foreshadow_cli", "--database", str(self.db),
            "foreshadow-audit", self.project], capture_output=True, text=True,
            encoding="utf-8", env=env, timeout=15)
        self.assertEqual(result.returncode, 0)
        self.assertIn("PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
