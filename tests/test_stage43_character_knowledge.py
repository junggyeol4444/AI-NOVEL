"""ANF-REQ-033: episode knowledge, false-knowledge blocking and offline isolation."""
from __future__ import annotations

from contextlib import closing, redirect_stdout
from io import StringIO
from pathlib import Path
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory.database.character_knowledge import (
    CharacterKnowledgeStore, KnowledgeError, _episode,
)
from ai_novel_factory.database.knowledge_cli import main as cli
from ai_novel_factory.database.characters import CharacterError, CharacterStore
from ai_novel_factory.database.novel_bible import NovelBibleError, NovelBibleStore
from ai_novel_factory.references.element_selection import FEATURE_KEYS


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "novel.db"
        self.store = CharacterKnowledgeStore(self.db)
        self.addCleanup(self.store.close)
        self.project = self.store.create_project("직접 창작한 작품").project_id
        self.character = self.store.create_character(
            self.project, name="주인공", personality="침착함", goal="진실 찾기",
            speech_style="존댓말", secret="아무도 모르는 비밀").character_id
        self.other = self.store.create_character(
            self.project, name="동료", personality="활달함", goal="친구 돕기",
            speech_style="반말").character_id
        self.fact = self.store.create_fact(self.project, "봉인된 문은 북쪽에 있다").fact_id

    def learn(self, episode=3, *, character=None, fact=None, knows=True, revision=None):
        return self.store.save_event(self.project, character or self.character,
                                     fact or self.fact, episode, knows=knows,
                                     expected_revision=revision)

    def state(self, episode, *, character=None, fact=None):
        return self.store.knowledge_at(self.project, character or self.character,
                                       fact or self.fact, episode)

    def test_fact_create_and_read(self):
        f = self.store.get_fact(self.project, self.fact)
        self.assertEqual(f.description, "봉인된 문은 북쪽에 있다")
        self.assertEqual(f.revision, 1)
        self.assertEqual(len(f.fact_id), 32)

    def test_fact_list(self):
        self.assertEqual(len(self.store.list_facts(self.project)), 1)

    def test_fact_multiline(self):
        f = self.store.create_fact(self.project, "첫째 줄\n둘째 줄")
        self.assertIn("\n", f.description)

    def test_fact_immutable_no_update_method(self):
        self.assertFalse(hasattr(self.store, "update_fact"))

    def test_episode_1_before_learning(self):
        self.learn(3)
        s = self.state(1)
        self.assertFalse(s.knows)
        self.assertEqual(s.status, "not_yet_learned")

    def test_episode_2_before_learning(self):
        self.learn(3)
        self.assertEqual(self.state(2).status, "not_yet_learned")

    def test_learning_episode_inclusive(self):
        self.learn(3)
        self.assertTrue(self.state(3).knows)
        self.assertEqual(self.state(3).effective_episode, 3)

    def test_after_learning_persists(self):
        self.learn(3)
        self.assertTrue(self.state(99).knows)

    def test_unknown_without_any_event(self):
        self.assertEqual(self.state(9).status, "not_recorded")
        self.assertFalse(self.state(9).knows)

    def test_explicit_not_knowing(self):
        self.learn(1, knows=False)
        self.assertEqual(self.state(3).status, "not_known")

    def test_forget_then_relearn(self):
        self.learn(2)
        self.learn(5, knows=False)
        self.learn(8)
        self.assertEqual([self.state(n).knows for n in (1, 2, 4, 5, 7, 8, 20)],
                         [False, True, True, False, False, True, True])

    def test_out_of_order_insertion(self):
        self.learn(10)
        self.learn(2, knows=False)
        self.learn(6)
        self.assertEqual(self.state(5).status, "not_known")
        self.assertTrue(self.state(7).knows)
        self.assertTrue(self.state(11).knows)

    def test_two_characters_separate_knowledge(self):
        self.learn(1)
        self.assertFalse(self.state(3, character=self.other).knows)
        self.assertEqual(self.state(3, character=self.other).status, "not_recorded")

    def test_two_facts_separate_knowledge(self):
        f2 = self.store.create_fact(self.project, "서쪽 통로는 함정").fact_id
        self.learn(1)
        self.assertFalse(self.state(2, fact=f2).knows)

    def test_knowledge_check_unknown_flagged(self):
        result = self.store.check_uses(self.project, self.character, 1, [self.fact])
        self.assertFalse(result.allowed)
        self.assertEqual(result.violations[0].reason, "not_recorded")

    def test_knowledge_check_future_flagged(self):
        self.learn(7)
        result = self.store.check_uses(self.project, self.character, 6, [self.fact])
        self.assertFalse(result.allowed)
        self.assertEqual(result.violations[0].reason, "not_yet_learned")

    def test_knowledge_check_known_passes(self):
        self.learn(7)
        result = self.store.check_uses(self.project, self.character, 7, [self.fact])
        self.assertTrue(result.allowed)
        self.assertEqual(result.violations, ())

    def test_knowledge_check_forgotten_flagged(self):
        self.learn(1)
        self.learn(3, knows=False)
        result = self.store.check_uses(self.project, self.character, 4, [self.fact])
        self.assertEqual(result.violations[0].reason, "not_known")

    def test_multi_fact_partial_unknown(self):
        second = self.store.create_fact(self.project, "동굴에 열쇠가 있다").fact_id
        self.learn(1)
        check = self.store.check_uses(self.project, self.character, 2, [self.fact, second])
        self.assertFalse(check.allowed)
        self.assertEqual([v.fact_id for v in check.violations], [second])

    def test_multi_fact_all_known(self):
        second = self.store.create_fact(self.project, "동굴에 열쇠가 있다").fact_id
        self.learn(1)
        self.learn(2, fact=second)
        self.assertTrue(self.store.check_uses(self.project, self.character, 2,
                                               [self.fact, second]).allowed)

    def test_require_known_blocks_unknown(self):
        with self.assertRaises(KnowledgeError) as error:
            self.store.require_known(self.project, self.character, 1, [self.fact])
        self.assertNotIn("봉인된", str(error.exception))

    def test_require_known_allows_known(self):
        self.learn(1)
        self.assertIsNone(self.store.require_known(self.project, self.character, 1, [self.fact]))

    def test_empty_fact_list_fails_closed(self):
        with self.assertRaises(KnowledgeError):
            self.store.check_uses(self.project, self.character, 2, [])

    def test_duplicate_fact_list_rejected(self):
        with self.assertRaises(KnowledgeError):
            self.store.check_uses(self.project, self.character, 2, [self.fact, self.fact])

    def test_over_100_fact_ids_rejected(self):
        with self.assertRaises(KnowledgeError):
            self.store.check_uses(self.project, self.character, 2, [str(i) for i in range(101)])

    def test_invalid_fact_ids_rejected(self):
        for value in (None, 1, "../../x", "z" * 32):
            with self.subTest(value=value), self.assertRaises(NovelBibleError):
                self.store.check_uses(self.project, self.character, 2, [value])

    def test_invalid_episode_values(self):
        for value in (True, False, 0, -1, 1_000_001, 1.0, "1", None):
            with self.subTest(value=value), self.assertRaises(KnowledgeError):
                _episode(value)

    def test_episode_limit_accepted(self):
        self.learn(1_000_000)
        self.assertTrue(self.state(1_000_000).knows)

    def test_knows_must_be_bool(self):
        for value in (0, 1, "yes", None):
            with self.subTest(value=value), self.assertRaises(KnowledgeError):
                self.learn(2, knows=value)

    def test_event_retrieve(self):
        event = self.learn(2)
        self.assertEqual(event.revision, 1)
        self.assertEqual(self.store.get_event(self.project, self.character, self.fact, 2), event)

    def test_event_list_order(self):
        self.learn(9)
        self.learn(1)
        self.learn(5, knows=False)
        self.assertEqual([e.episode for e in self.store.list_events(self.project, self.character)],
                         [1, 5, 9])

    def test_event_list_fact_filter(self):
        f2 = self.store.create_fact(self.project, "다른 지식").fact_id
        self.learn(1)
        self.learn(3, fact=f2)
        self.assertEqual(len(self.store.list_events(self.project, self.character,
                                                    fact_id=self.fact)), 1)

    def test_event_update_with_revision(self):
        self.learn(2)
        event = self.learn(2, knows=False, revision=1)
        self.assertEqual(event.revision, 2)
        self.assertFalse(event.knows)

    def test_event_update_requires_revision(self):
        self.learn(2)
        with self.assertRaises(KnowledgeError):
            self.learn(2, knows=False)
        self.assertTrue(self.state(2).knows)

    def test_event_create_rejects_revision(self):
        with self.assertRaises(KnowledgeError):
            self.learn(2, revision=1)

    def test_stale_revision_no_write(self):
        self.learn(2)
        self.learn(2, knows=False, revision=1)
        with self.assertRaises(KnowledgeError):
            self.learn(2, revision=1)
        self.assertFalse(self.state(2).knows)

    def test_stale_revision_two_connections(self):
        self.learn(2)
        with CharacterKnowledgeStore(self.db) as other:
            other.save_event(self.project, self.character, self.fact, 2,
                             knows=False, expected_revision=1)
            with self.assertRaises(KnowledgeError):
                self.learn(2, revision=1)

    def test_delete_event_reverts_timeline(self):
        self.learn(2)
        self.learn(4, knows=False)
        self.store.delete_event(self.project, self.character, self.fact, 4,
                                expected_revision=1)
        self.assertTrue(self.state(6).knows)

    def test_delete_event_wrong_revision(self):
        self.learn(2)
        with self.assertRaises(KnowledgeError):
            self.store.delete_event(self.project, self.character, self.fact, 2,
                                    expected_revision=2)
        self.assertTrue(self.state(3).knows)

    def test_delete_fact_cascades_events(self):
        self.learn(2)
        self.store.delete_fact(self.project, self.fact, expected_revision=1)
        self.assertEqual(self.store.list_facts(self.project), ())
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM bible_knowledge_events").fetchone()[0], 0)

    def test_delete_fact_wrong_revision(self):
        with self.assertRaises(KnowledgeError):
            self.store.delete_fact(self.project, self.fact, expected_revision=2)
        self.assertEqual(len(self.store.list_facts(self.project)), 1)

    def test_delete_character_cascades_events(self):
        self.learn(2)
        self.store.delete_character(self.project, self.character, expected_revision=1)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM bible_knowledge_events").fetchone()[0], 0)
        self.assertEqual(len(self.store.list_facts(self.project)), 1)

    def test_delete_project_cascades_everything(self):
        self.learn(2)
        self.store.delete_project(self.project)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM bible_knowledge_facts").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT count(*) FROM bible_knowledge_events").fetchone()[0], 0)

    def test_reopen_persists_timeline(self):
        self.learn(2)
        self.learn(4, knows=False)
        with CharacterKnowledgeStore(self.db) as reopened:
            self.assertTrue(reopened.knowledge_at(self.project, self.character, self.fact, 3).knows)
            self.assertFalse(reopened.knowledge_at(self.project, self.character, self.fact, 4).knows)

    def test_works_with_existing_character_store(self):
        self.learn(2)
        with CharacterStore(self.db) as old:
            self.assertEqual(old.get_character(self.project, self.character).name, "주인공")
        with NovelBibleStore(self.db) as old:
            self.assertEqual(old.get_project(self.project).project_id, self.project)

    def test_project_revision_bumped(self):
        rev = self.store.get_project(self.project).revision
        self.learn(2)
        self.assertEqual(self.store.get_project(self.project).revision, rev + 1)
        self.learn(2, knows=False, revision=1)
        self.assertEqual(self.store.get_project(self.project).revision, rev + 2)
        self.store.delete_event(self.project, self.character, self.fact, 2,
                                expected_revision=2)
        self.assertEqual(self.store.get_project(self.project).revision, rev + 3)

    def test_failed_write_no_revision_bump(self):
        rev = self.store.get_project(self.project).revision
        with self.assertRaises(KnowledgeError):
            self.learn(2, revision=1)
        self.assertEqual(self.store.get_project(self.project).revision, rev)

    def test_unknown_project_rejected(self):
        with self.assertRaises(NovelBibleError):
            self.store.create_fact("f" * 32, "정보")

    def test_cross_project_fact_rejected(self):
        other = self.store.create_project("다른 작품").project_id
        f2 = self.store.create_fact(other, "다른 작품의 사실")
        with self.assertRaises(KnowledgeError):
            self.learn(2, fact=f2.fact_id)
        with self.assertRaises(KnowledgeError):
            self.store.check_uses(self.project, self.character, 2, [f2.fact_id])

    def test_cross_project_character_rejected(self):
        other = self.store.create_project("다른 작품").project_id
        c = self.store.create_character(other, name="타인", personality="성격",
                                        goal="목표", speech_style="말투")
        with self.assertRaises(CharacterError):
            self.learn(2, character=c.character_id)

    def test_raw_sql_cross_project_event_fk_rejected(self):
        other = self.store.create_project("다른 작품").project_id
        f2 = self.store.create_fact(other, "다른 작품의 사실")
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("PRAGMA foreign_keys=ON")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("""INSERT INTO bible_knowledge_events VALUES
                    (?, ?, ?, 2, 1, 1, ?)""",
                    (self.project, self.character, f2.fact_id, "2026-01-01T00:00:00+00:00"))

    def test_invalid_fact_empty(self):
        with self.assertRaises(KnowledgeError):
            self.store.create_fact(self.project, "")

    def test_invalid_fact_control(self):
        with self.assertRaises(KnowledgeError):
            self.store.create_fact(self.project, "비밀\x00문구")

    def test_invalid_fact_surrogate(self):
        with self.assertRaises(KnowledgeError):
            self.store.create_fact(self.project, "\ud800")

    def test_invalid_fact_utf8_length(self):
        with self.assertRaises(KnowledgeError):
            self.store.create_fact(self.project, "가" * 3000)

    def test_sql_metacharacters_treated_as_text(self):
        f = self.store.create_fact(self.project, "'); DROP TABLE bible_projects;--")
        self.assertEqual(self.store.get_fact(self.project, f.fact_id).description, f.description)

    def test_corrupt_fact_rejected_without_echo(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE bible_knowledge_facts SET description=? WHERE fact_id=?",
                         ("숨겨진비밀\x00", self.fact))
        with self.assertRaises(KnowledgeError) as cm:
            self.store.get_fact(self.project, self.fact)
        self.assertNotIn("숨겨진비밀", str(cm.exception))

    def test_corrupt_event_rejected(self):
        self.learn(2)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("PRAGMA ignore_check_constraints=ON")
            conn.execute("UPDATE bible_knowledge_events SET knows=5 WHERE fact_id=?",
                         (self.fact,))
        with self.assertRaises(KnowledgeError):
            self.state(2)

    def test_corrupt_future_event_rejected(self):
        self.learn(7)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE bible_knowledge_events SET updated_at='invalid' WHERE fact_id=?",
                         (self.fact,))
        with self.assertRaises(KnowledgeError):
            self.state(1)

    def test_canon_priority_unchanged(self):
        key = FEATURE_KEYS[0]
        self.store.save_rule(self.project, key, "작품 규칙이 최우선")
        self.learn(2)
        ctx = self.store.resolve_context(self.project, {key: 999.0})
        self.assertEqual(ctx.fields[0].source, "novel_bible")

    def test_no_auto_generation_context(self):
        self.learn(2)
        with self.assertRaises(NovelBibleError):
            self.store.resolve_context(self.project)

    def test_no_reference_text_automatic_import(self):
        self.learn(2)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM bible_rules").fetchone()[0], 0)

    def test_posix_db_permissions(self):
        if os.name == "posix":
            self.assertEqual(self.db.stat().st_mode & 0o777, 0o600)

    def test_no_network_needed(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            self.learn(2)
            self.assertTrue(self.state(3).knows)


class KnowledgeCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / "canon.db"
        with CharacterKnowledgeStore(self.db) as store:
            self.project = store.create_project("작품").project_id
            self.character = store.create_character(
                self.project, name="인물", personality="성격", goal="목표",
                speech_style="말투").character_id
        self.input = self.root / "fact.txt"
        self.input.write_text("사용자만 아는 숨겨진 사실", encoding="utf-8")

    def run_cli(self, *args):
        out = StringIO()
        with redirect_stdout(out):
            code = cli(["--database", str(self.db), *args])
        return code, out.getvalue()

    def create(self):
        code, output = self.run_cli("fact-create", self.project,
                                    "--text-file", str(self.input))
        self.assertEqual(code, 0, output)
        self.assertNotIn("숨겨진", output)
        return output.split()[1]

    def test_cli_fact_create_redacted(self):
        self.create()

    def test_cli_fact_list_redacted(self):
        fact = self.create()
        code, output = self.run_cli("fact-list", self.project)
        self.assertEqual(code, 0)
        self.assertIn(fact, output)
        self.assertNotIn("숨겨진", output)

    def test_cli_fact_show_default_redacted(self):
        fact = self.create()
        code, output = self.run_cli("fact-show", self.project, fact)
        self.assertEqual(code, 0)
        self.assertIn("[redacted", output)
        self.assertNotIn("숨겨진", output)

    def test_cli_fact_show_reveal_explicit(self):
        fact = self.create()
        code, output = self.run_cli("fact-show", self.project, fact, "--reveal")
        self.assertEqual(code, 0)
        self.assertIn("숨겨진 사실", output)

    def test_cli_event_set_and_list(self):
        fact = self.create()
        code, output = self.run_cli("event-set", self.project, self.character,
                                    fact, "3", "--knows")
        self.assertEqual(code, 0, output)
        self.assertIn("revision 1", output)
        code, output = self.run_cli("event-list", self.project, self.character)
        self.assertEqual(code, 0)
        self.assertIn("episode 3", output)
        self.assertNotIn("숨겨진", output)

    def test_cli_unknown_check_returns_2(self):
        fact = self.create()
        code, output = self.run_cli("knowledge-check", self.project,
                                    self.character, "1", "--fact-id", fact)
        self.assertEqual(code, 2)
        self.assertIn("ERROR", output)
        self.assertNotIn("숨겨진", output)

    def test_cli_future_knowledge_flagged(self):
        fact = self.create()
        self.run_cli("event-set", self.project, self.character, fact, "3", "--knows")
        code, output = self.run_cli("knowledge-check", self.project,
                                    self.character, "2", "--fact-id", fact)
        self.assertEqual(code, 2)
        self.assertIn("not_yet_learned", output)

    def test_cli_known_check_passes(self):
        fact = self.create()
        self.run_cli("event-set", self.project, self.character, fact, "3", "--knows")
        code, output = self.run_cli("knowledge-check", self.project,
                                    self.character, "3", "--fact-id", fact)
        self.assertEqual(code, 0)
        self.assertIn("PASS", output)

    def test_cli_knowledge_at(self):
        fact = self.create()
        code, output = self.run_cli("knowledge-at", self.project,
                                    self.character, fact, "1")
        self.assertEqual(code, 0)
        self.assertIn("not_recorded", output)

    def test_cli_event_update_revision(self):
        fact = self.create()
        self.run_cli("event-set", self.project, self.character, fact, "3", "--knows")
        code, output = self.run_cli("event-set", self.project, self.character, fact,
                                    "3", "--does-not-know", "--revision", "1")
        self.assertEqual(code, 0, output)
        self.assertIn("revision 2", output)

    def test_cli_event_delete(self):
        fact = self.create()
        self.run_cli("event-set", self.project, self.character, fact, "3", "--knows")
        code, output = self.run_cli("event-delete", self.project, self.character,
                                    fact, "3", "--revision", "1")
        self.assertEqual(code, 0, output)
        code, output = self.run_cli("knowledge-at", self.project, self.character, fact, "3")
        self.assertIn("not_recorded", output)

    def test_cli_fact_delete(self):
        fact = self.create()
        code, output = self.run_cli("fact-delete", self.project, fact, "--revision", "1")
        self.assertEqual(code, 0, output)
        self.assertEqual(self.run_cli("fact-list", self.project)[1], "")

    def test_cli_missing_revision_fails(self):
        fact = self.create()
        code, output = self.run_cli("fact-delete", self.project, fact)
        self.assertEqual(code, 1)
        self.assertNotIn("숨겨진", output)

    def test_cli_missing_file_fails_no_path(self):
        code, output = self.run_cli("fact-create", self.project, "--text-file",
                                    str(self.root / "SECRET-NAME.txt"))
        self.assertEqual(code, 1)
        self.assertNotIn("SECRET-NAME", output)

    def test_cli_symlink_file_fails(self):
        link = self.root / "link.txt"
        try:
            link.symlink_to(self.input)
        except (OSError, NotImplementedError):
            self.skipTest("symlink unsupported")
        self.assertEqual(self.run_cli("fact-create", self.project,
                                      "--text-file", str(link))[0], 1)

    def test_cli_module_entrypoint(self):
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
        result = subprocess.run([sys.executable, "-m", "ai_novel_factory.database.knowledge_cli",
                                 "--database", str(self.db), "fact-list", self.project],
                                cwd=Path(__file__).resolve().parents[1], env=env,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_no_network(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            self.create()
