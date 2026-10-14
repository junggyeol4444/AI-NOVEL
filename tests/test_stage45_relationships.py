"""ANF-REQ-035: relationships change across episodes without reference text leakage."""
from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from pathlib import Path
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory.database.relationships import (
    RelationshipError, RelationshipStore, _episode, _pair, _relationship, _notes,
)
from ai_novel_factory.database.relationship_cli import main as relationship_cli
from ai_novel_factory.database.characters import CharacterStore
from ai_novel_factory.database.novel_bible import NovelBibleError


class RelationshipTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "bible.db"
        self.store = RelationshipStore(self.db)
        self.addCleanup(self.store.close)
        self.project = self.store.create_project("새 소설").project_id
        self.a = self.character("첫 인물")
        self.b = self.character("둘째 인물")
        self.c = self.character("셋째 인물")

    def character(self, name, project=None):
        return self.store.create_character(project or self.project, name=name,
            personality="침착", goal="목표", speech_style="정중", secret="비밀").character_id

    def save(self, episode=1, relationship="동료", *, a=None, b=None, **kw):
        return self.store.save_relation(self.project, a or self.a, b or self.b,
                                        episode, relationship=relationship, **kw)

    def test_initially_unrecorded(self):
        state = self.store.get_at(self.project, self.a, self.b, 1)
        self.assertEqual(state.status, "not_recorded")
        self.assertIsNone(state.relationship)

    def test_first_record(self):
        self.assertEqual(self.save().relationship, "동료")

    def test_first_episode(self):
        self.assertEqual(self.save().episode, 1)

    def test_episode_two_still_same(self):
        self.save()
        self.assertEqual(self.store.get_at(self.project, self.a, self.b, 2).relationship, "동료")

    def test_future_change_not_visible(self):
        self.save(3, "적")
        self.assertEqual(self.store.get_at(self.project, self.a, self.b, 2).status, "not_recorded")

    def test_changes_at_boundary(self):
        self.save(1, "동료")
        self.save(3, "적")
        self.assertEqual(self.store.get_at(self.project, self.a, self.b, 3).relationship, "적")

    def test_previous_relation_preserved(self):
        self.save(1, "동료")
        self.save(3, "적")
        self.assertEqual(self.store.get_at(self.project, self.a, self.b, 2).relationship, "동료")

    def test_later_relation_persists(self):
        self.save(1, "동료")
        self.save(3, "적")
        self.assertEqual(self.store.get_at(self.project, self.a, self.b, 999).relationship, "적")

    def test_same_pair_reverse_lookup(self):
        self.save()
        self.assertEqual(self.store.get_at(self.project, self.b, self.a, 1).relationship, "동료")

    def test_reverse_order_same_event(self):
        self.save()
        with self.assertRaises(RelationshipError):
            self.save(a=self.b, b=self.a)

    def test_reverse_order_update(self):
        old = self.save()
        updated = self.save(a=self.b, b=self.a, relationship="원수", expected_revision=old.revision)
        self.assertEqual(updated.relationship, "원수")

    def test_canonical_pair_order(self):
        item = self.save(a=self.b, b=self.a)
        self.assertLess(item.first_character_id, item.second_character_id)

    def test_self_relation_rejected(self):
        with self.assertRaises(RelationshipError):
            self.save(b=self.a)

    def test_pair_rejects_non_ids(self):
        for val in ("", "abc", "0" * 31, "G" * 32, None, 2, True):
            with self.subTest(val=val), self.assertRaises(RelationshipError):
                _pair(val, self.a)

    def test_episode_rejects_bool(self):
        with self.assertRaises(RelationshipError):
            _episode(True)

    def test_episode_rejects_float(self):
        with self.assertRaises(RelationshipError):
            _episode(2.0)

    def test_episode_rejects_string(self):
        with self.assertRaises(RelationshipError):
            _episode("2")

    def test_episode_rejects_zero(self):
        with self.assertRaises(RelationshipError):
            _episode(0)

    def test_episode_rejects_negative(self):
        with self.assertRaises(RelationshipError):
            _episode(-1)

    def test_episode_rejects_too_large(self):
        with self.assertRaises(RelationshipError):
            _episode(1000001)

    def test_max_episode_valid(self):
        self.assertEqual(self.save(1000000).episode, 1000000)

    def test_description_invalid(self):
        for val in ("", "  ", "x" * 4001, "\x00", "\x7f", None, 1, True):
            with self.subTest(val=str(val)[:20]), self.assertRaises(RelationshipError):
                _relationship(val)

    def test_notes_empty_valid(self):
        self.assertEqual(_notes(""), "")

    def test_notes_invalid(self):
        for val in (" " * 2, "x" * 4001, "\x00", None, 1, True):
            with self.subTest(val=str(val)[:20]), self.assertRaises(RelationshipError):
                _notes(val)

    def test_unicode_relationship(self):
        self.assertEqual(self.save(relationship="서로를 신뢰함 🌙").relationship, "서로를 신뢰함 🌙")

    def test_notes_roundtrip(self):
        self.assertEqual(self.save(notes="서로의 과거를 안다").notes, "서로의 과거를 안다")

    def test_utf8_byte_limit(self):
        with self.assertRaises(RelationshipError):
            self.save(relationship="한" * 3000)

    def test_revision_initial(self):
        self.assertEqual(self.save().revision, 1)

    def test_revision_increases(self):
        old = self.save()
        self.assertEqual(self.save(expected_revision=old.revision).revision, 2)

    def test_update_replaces_notes(self):
        old = self.save(notes="옛 기록")
        self.assertEqual(self.save(notes="새 기록", expected_revision=old.revision).notes, "새 기록")

    def test_update_requires_revision(self):
        self.save()
        with self.assertRaises(RelationshipError):
            self.save(relationship="덮어쓰기")

    def test_stale_update_rejected(self):
        old = self.save()
        self.save(expected_revision=old.revision)
        with self.assertRaises(RelationshipError):
            self.save(expected_revision=old.revision, relationship="오류")

    def test_stale_update_preserves_value(self):
        old = self.save()
        self.save(expected_revision=old.revision, relationship="유지")
        with self.assertRaises(RelationshipError):
            self.save(expected_revision=old.revision, relationship="오류")
        self.assertEqual(self.store.get_at(self.project, self.a, self.b, 1).relationship, "유지")

    def test_create_with_expected_revision_rejected(self):
        with self.assertRaises(RelationshipError):
            self.save(expected_revision=1)

    def test_invalid_revision_bool(self):
        with self.assertRaises(NovelBibleError):
            self.save(expected_revision=True)

    def test_invalid_revision_zero(self):
        with self.assertRaises(NovelBibleError):
            self.save(expected_revision=0)

    def test_revision_overflow_rejected(self):
        self.save()
        self.store._db.execute("UPDATE bible_relationship_events SET revision=2147483647")
        self.store._db.commit()
        with self.assertRaises(RelationshipError):
            self.save(expected_revision=2147483647)

    def test_revision_overflow_does_not_bump_project(self):
        self.save()
        self.store._db.execute("UPDATE bible_relationship_events SET revision=2147483647")
        self.store._db.commit()
        before = self.store.get_project(self.project).revision
        with self.assertRaises(RelationshipError):
            self.save(expected_revision=2147483647)
        self.assertEqual(self.store.get_project(self.project).revision, before)

    def test_project_revision_bumps_on_create(self):
        before = self.store.get_project(self.project).revision
        self.save()
        self.assertEqual(self.store.get_project(self.project).revision, before + 1)

    def test_project_revision_bumps_on_update(self):
        old = self.save()
        before = self.store.get_project(self.project).revision
        self.save(expected_revision=old.revision)
        self.assertEqual(self.store.get_project(self.project).revision, before + 1)

    def test_failed_create_does_not_bump_project(self):
        self.save()
        before = self.store.get_project(self.project).revision
        with self.assertRaises(RelationshipError):
            self.save()
        self.assertEqual(self.store.get_project(self.project).revision, before)

    def test_history_sorted(self):
        self.save(5, "원수")
        self.save(1, "동료")
        self.save(3, "친구")
        self.assertEqual([x.episode for x in self.store.history(self.project, self.a, self.b)], [1, 3, 5])

    def test_history_reverse_pair(self):
        self.save(2)
        self.assertEqual(len(self.store.history(self.project, self.b, self.a)), 1)

    def test_history_empty(self):
        self.assertEqual(self.store.history(self.project, self.a, self.b), ())

    def test_get_event_exact(self):
        self.save(5)
        self.assertEqual(self.store.get_event(self.project, self.a, self.b, 5).episode, 5)

    def test_get_event_not_effective_lookup(self):
        self.save(5)
        with self.assertRaises(RelationshipError):
            self.store.get_event(self.project, self.a, self.b, 6)

    def test_state_effective_episode(self):
        self.save(2)
        self.assertEqual(self.store.get_at(self.project, self.a, self.b, 9).effective_episode, 2)

    def test_state_requested_episode(self):
        self.save(2)
        self.assertEqual(self.store.get_at(self.project, self.a, self.b, 9).requested_episode, 9)

    def test_list_at_initially_empty(self):
        self.assertEqual(self.store.list_at(self.project, 1), ())

    def test_list_at_one_per_pair(self):
        self.save(1, "동료")
        self.save(2, "적")
        self.save(1, "친구", a=self.a, b=self.c)
        self.assertEqual(len(self.store.list_at(self.project, 2)), 2)

    def test_list_at_effective_latest(self):
        self.save(1, "동료")
        self.save(3, "적")
        self.assertEqual(self.store.list_at(self.project, 2)[0].relationship, "동료")
        self.assertEqual(self.store.list_at(self.project, 3)[0].relationship, "적")

    def test_list_at_future_not_visible(self):
        self.save(9)
        self.assertEqual(self.store.list_at(self.project, 8), ())

    def test_list_at_sorted(self):
        self.save(a=self.b, b=self.c)
        self.save(a=self.a, b=self.c)
        self.save(a=self.a, b=self.b)
        pairs = [(s.first_character_id, s.second_character_id) for s in self.store.list_at(self.project, 1)]
        self.assertEqual(pairs, sorted(pairs))

    def test_delete_event(self):
        item = self.save()
        self.store.delete_event(self.project, self.a, self.b, 1, expected_revision=item.revision)
        self.assertEqual(self.store.get_at(self.project, self.a, self.b, 1).status, "not_recorded")

    def test_delete_latest_falls_back(self):
        self.save(1, "동료")
        latest = self.save(3, "적")
        self.store.delete_event(self.project, self.b, self.a, 3, expected_revision=latest.revision)
        self.assertEqual(self.store.get_at(self.project, self.a, self.b, 9).relationship, "동료")

    def test_delete_stale_revision_rejected(self):
        item = self.save()
        item = self.save(expected_revision=item.revision)
        with self.assertRaises(RelationshipError):
            self.store.delete_event(self.project, self.a, self.b, 1, expected_revision=1)
        self.assertEqual(self.store.get_event(self.project, self.a, self.b, 1).revision, 2)

    def test_delete_missing_rejected(self):
        with self.assertRaises(RelationshipError):
            self.store.delete_event(self.project, self.a, self.b, 1, expected_revision=1)

    def test_delete_bumps_project_revision(self):
        item = self.save()
        before = self.store.get_project(self.project).revision
        self.store.delete_event(self.project, self.a, self.b, 1, expected_revision=item.revision)
        self.assertEqual(self.store.get_project(self.project).revision, before + 1)

    def test_delete_failure_no_bump(self):
        self.save()
        before = self.store.get_project(self.project).revision
        with self.assertRaises(RelationshipError):
            self.store.delete_event(self.project, self.a, self.b, 1, expected_revision=5)
        self.assertEqual(self.store.get_project(self.project).revision, before)

    def test_other_project_no_read(self):
        self.save()
        other = self.store.create_project("다른 작품").project_id
        x, y = self.character("다른 인물", other), self.character("다른 두번째", other)
        with self.assertRaises((RelationshipError, NovelBibleError)):
            self.store.get_at(other, self.a, self.b, 1)
        self.assertEqual(self.store.get_at(other, x, y, 1).status, "not_recorded")

    def test_other_project_no_write(self):
        other = self.store.create_project("다른 작품").project_id
        with self.assertRaises((RelationshipError, NovelBibleError)):
            self.store.save_relation(other, self.a, self.b, 1, relationship="침입")

    def test_other_project_no_delete(self):
        self.save()
        other = self.store.create_project("다른 작품").project_id
        with self.assertRaises((RelationshipError, NovelBibleError)):
            self.store.delete_event(other, self.a, self.b, 1, expected_revision=1)
        self.assertEqual(len(self.store.history(self.project, self.a, self.b)), 1)

    def test_other_project_list_empty(self):
        self.save()
        other = self.store.create_project("다른 작품").project_id
        self.assertEqual(self.store.list_at(other, 1), ())

    def test_missing_character_rejected(self):
        with self.assertRaises((RelationshipError, NovelBibleError)):
            self.save(b="0" * 32)

    def test_missing_project_rejected(self):
        with self.assertRaises(NovelBibleError):
            self.store.list_at("0" * 32, 1)

    def test_delete_character_cascades(self):
        self.save()
        self.store.delete_character(self.project, self.a,
                                    expected_revision=self.store.get_character(self.project, self.a).revision)
        self.assertEqual(self.store._db.execute("SELECT COUNT(*) FROM bible_relationship_events").fetchone()[0], 0)

    def test_delete_project_cascades(self):
        self.save()
        self.store.delete_project(self.project)
        self.assertEqual(self.store._db.execute("SELECT COUNT(*) FROM bible_relationship_events").fetchone()[0], 0)

    def test_raw_sql_wrong_project_fk_rejected(self):
        other = self.store.create_project("다른 작품").project_id
        with self.assertRaises(sqlite3.IntegrityError):
            self.store._db.execute("""INSERT INTO bible_relationship_events VALUES
                (?, ?, ?, 1, '관계', '', 1, '2026-01-01T00:00:00+00:00')""",
                (other, *_pair(self.a, self.b)))

    def test_raw_sql_reverse_pair_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.store._db.execute("""INSERT INTO bible_relationship_events VALUES
                (?, ?, ?, 1, '관계', '', 1, '2026-01-01T00:00:00+00:00')""",
                (self.project, *_pair(self.b, self.a)[::-1]))

    def test_raw_sql_duplicate_pair_episode_rejected(self):
        self.save()
        with self.assertRaises(sqlite3.IntegrityError):
            self.store._db.execute("""INSERT INTO bible_relationship_events VALUES
                (?, ?, ?, 1, '관계', '', 1, '2026-01-01T00:00:00+00:00')""",
                (self.project, *_pair(self.a, self.b)))

    def test_raw_sql_invalid_episode_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.store._db.execute("""INSERT INTO bible_relationship_events VALUES
                (?, ?, ?, 0, '관계', '', 1, '2026-01-01T00:00:00+00:00')""",
                (self.project, *_pair(self.a, self.b)))

    def test_raw_sql_self_pair_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.store._db.execute("""INSERT INTO bible_relationship_events VALUES
                (?, ?, ?, 1, '관계', '', 1, '2026-01-01T00:00:00+00:00')""",
                (self.project, self.a, self.a))

    def test_timestamp_aware(self):
        self.assertIsNotNone(datetime.fromisoformat(self.save().updated_at).utcoffset())

    def test_corrupt_timestamp_fail_closed(self):
        self.save()
        self.store._db.execute("UPDATE bible_relationship_events SET updated_at='bad'")
        with self.assertRaises(RelationshipError):
            self.store.get_at(self.project, self.a, self.b, 1)

    def test_corrupt_revision_fail_closed(self):
        self.save()
        self.store._db.execute("PRAGMA ignore_check_constraints=ON")
        self.store._db.execute("UPDATE bible_relationship_events SET revision=0")
        with self.assertRaises(RelationshipError):
            self.store.get_event(self.project, self.a, self.b, 1)

    def test_corrupt_content_fail_closed(self):
        self.save()
        self.store._db.execute("PRAGMA ignore_check_constraints=ON")
        self.store._db.execute("UPDATE bible_relationship_events SET relationship='' ")
        with self.assertRaises(RelationshipError):
            self.store.list_at(self.project, 1)

    def test_error_never_echoes_private_text(self):
        self.save(relationship="매우비밀스러운문구")
        with self.assertRaises(RelationshipError) as cm:
            self.save(relationship="매우비밀스러운문구")
        self.assertNotIn("매우비밀스러운문구", str(cm.exception))

    def test_persists_after_reopen(self):
        self.save(1, "친구")
        self.save(8, "원수")
        with RelationshipStore(self.db) as other:
            self.assertEqual(other.get_at(self.project, self.a, self.b, 1).relationship, "친구")
            self.assertEqual(other.get_at(self.project, self.a, self.b, 8).relationship, "원수")

    def test_base_character_store_sees_characters(self):
        self.save()
        with CharacterStore(self.db) as other:
            self.assertEqual(len(other.list_characters(self.project)), 3)

    def test_novel_bible_rule_unchanged(self):
        self.store.save_rule(self.project, "theme", "희망")
        self.save()
        self.assertEqual(self.store.get_rule(self.project, "theme").value, "희망")

    def test_cli_create_redacted(self):
        content = Path(self.db.parent) / "relation.txt"
        content.write_text("비밀의 동맹", encoding="utf-8")
        output = StringIO()
        with redirect_stdout(output):
            code = relationship_cli(["--database", str(self.db), "relationship-set",
                self.project, self.a, self.b, "--episode", "2", "--relationship-file", str(content)])
        self.assertEqual(code, 0)
        self.assertNotIn("비밀의 동맹", output.getvalue())
        self.assertEqual(self.store.get_at(self.project, self.a, self.b, 2).relationship, "비밀의 동맹")

    def test_cli_show_redacted(self):
        self.save(relationship="숨겨진 동맹")
        output = StringIO()
        with redirect_stdout(output):
            code = relationship_cli(["--database", str(self.db), "relationship-show",
                self.project, self.a, self.b, "--episode", "1"])
        self.assertEqual(code, 0)
        self.assertNotIn("숨겨진 동맹", output.getvalue())
        self.assertIn("redacted", output.getvalue())

    def test_cli_show_reveal(self):
        self.save(relationship="숨겨진 동맹")
        output = StringIO()
        with redirect_stdout(output):
            code = relationship_cli(["--database", str(self.db), "relationship-show",
                self.project, self.a, self.b, "--episode", "1", "--reveal"])
        self.assertEqual(code, 0)
        self.assertIn("숨겨진 동맹", output.getvalue())

    def test_cli_history_redacted(self):
        self.save(relationship="비밀 친구")
        output = StringIO()
        with redirect_stdout(output):
            code = relationship_cli(["--database", str(self.db), "relationship-history",
                self.project, self.a, self.b])
        self.assertEqual(code, 0)
        self.assertNotIn("비밀 친구", output.getvalue())

    def test_cli_list_redacted(self):
        self.save(relationship="비밀 친구")
        output = StringIO()
        with redirect_stdout(output):
            code = relationship_cli(["--database", str(self.db), "relationship-list",
                self.project, "--episode", "1"])
        self.assertEqual(code, 0)
        self.assertNotIn("비밀 친구", output.getvalue())

    def test_cli_update_with_revision(self):
        self.save()
        content = Path(self.db.parent) / "relation.txt"
        content.write_text("원수", encoding="utf-8")
        with redirect_stdout(StringIO()):
            code = relationship_cli(["--database", str(self.db), "relationship-set",
                self.project, self.a, self.b, "--episode", "1", "--revision", "1",
                "--relationship-file", str(content)])
        self.assertEqual(code, 0)
        self.assertEqual(self.store.get_at(self.project, self.a, self.b, 1).relationship, "원수")

    def test_cli_delete_with_revision(self):
        self.save()
        with redirect_stdout(StringIO()):
            code = relationship_cli(["--database", str(self.db), "relationship-delete",
                self.project, self.a, self.b, "--episode", "1", "--revision", "1"])
        self.assertEqual(code, 0)
        self.assertEqual(self.store.get_at(self.project, self.a, self.b, 1).status, "not_recorded")

    def test_cli_invalid_episode_returns_one(self):
        output = StringIO()
        with redirect_stdout(output):
            code = relationship_cli(["--database", str(self.db), "relationship-show",
                self.project, self.a, self.b, "--episode", "0"])
        self.assertEqual(code, 1)
        self.assertIn("ERROR", output.getvalue())

    def test_cli_no_remote_text_file(self):
        output = StringIO()
        with redirect_stdout(output):
            code = relationship_cli(["--database", str(self.db), "relationship-set",
                self.project, self.a, self.b, "--episode", "1",
                "--relationship-file", "file:/remote"])
        self.assertEqual(code, 1)

    def test_cli_no_secret_in_failure(self):
        content = Path(self.db.parent) / "relation.txt"
        content.write_text("비밀값", encoding="utf-8")
        self.save(relationship="다른 비밀값")
        output = StringIO()
        with redirect_stdout(output):
            code = relationship_cli(["--database", str(self.db), "relationship-set",
                self.project, self.a, self.b, "--episode", "1",
                "--relationship-file", str(content)])
        self.assertEqual(code, 1)
        self.assertNotIn("비밀값", output.getvalue())

    def test_cli_subprocess_offline(self):
        self.save(relationship="연결된 관계")
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        result = subprocess.run([sys.executable, "-m", "ai_novel_factory.database.relationship_cli",
            "--database", str(self.db), "relationship-show", self.project, self.a,
            self.b, "--episode", "1"], capture_output=True, text=True, env=env,
            timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("연결된 관계", result.stdout)


if __name__ == "__main__":
    unittest.main()
