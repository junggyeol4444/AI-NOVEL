"""ANF-REQ-032: real local SQLite persistence, isolation, concurrency and CLI."""
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

from ai_novel_factory.database.characters import CharacterError, CharacterStore
from ai_novel_factory.database.character_cli import main as character_cli
from ai_novel_factory.database.novel_bible import NovelBibleError, NovelBibleStore
from ai_novel_factory.references.element_selection import FEATURE_KEYS


class CharacterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "canon.db"
        self.store = CharacterStore(self.db)
        self.addCleanup(self.store.close)
        self.project = self.store.create_project("소설 하나").project_id
        self.data = dict(name="주인공", personality="신중하지만 용감하다", goal="친구를 구한다",
                         speech_style="짧고 정확하게 말한다", secret="고향을 숨기고 있다")

    def add(self, **updates):
        return self.store.create_character(self.project, **(self.data | updates))

    def test_create_and_read_all_fields(self):
        c = self.add()
        self.assertEqual(c.name, self.data["name"])
        self.assertEqual(c.personality, self.data["personality"])
        self.assertEqual(c.goal, self.data["goal"])
        self.assertEqual(c.speech_style, self.data["speech_style"])
        self.assertEqual(c.secret, self.data["secret"])
        self.assertEqual(c.revision, 1)
        self.assertEqual(len(c.character_id), 32)
        self.assertEqual(self.store.get_character(self.project, c.character_id), c)

    def test_reopen_sqlite_persists(self):
        c = self.add()
        with CharacterStore(self.db) as reopened:
            self.assertEqual(reopened.get_character(self.project, c.character_id), c)

    def test_can_use_existing_stage41_project(self):
        with NovelBibleStore(self.db) as old:
            old.save_rule(self.project, "canon", "직접 입력한 세계관")
        c = self.add()
        with NovelBibleStore(self.db) as old:
            self.assertEqual(old.get_rule(self.project, "canon").value, "직접 입력한 세계관")
        self.assertEqual(self.store.get_character(self.project, c.character_id).name, "주인공")

    def test_no_reference_text_auto_imported(self):
        self.add()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM bible_rules").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT count(*) FROM bible_characters").fetchone()[0], 1)

    def test_canon_priority_unaffected(self):
        key = FEATURE_KEYS[0]
        self.store.save_rule(self.project, key, "참고 통계보다 우선하는 규칙")
        self.add()
        context = self.store.resolve_context(self.project, {key: 99.0})
        self.assertEqual(context.overridden_reference_keys, (key,))
        self.assertEqual(context.fields[0].source, "novel_bible")
        self.assertEqual(context.fields[0].value, "참고 통계보다 우선하는 규칙")

    def test_no_rule_means_no_generation_context_even_with_characters(self):
        self.add()
        with self.assertRaises(NovelBibleError):
            self.store.resolve_context(self.project)

    def test_create_bumps_project_revision(self):
        self.assertEqual(self.store.get_project(self.project).revision, 0)
        self.add()
        self.assertEqual(self.store.get_project(self.project).revision, 1)

    def test_update_bumps_character_and_project_revision(self):
        c = self.add()
        revised = self.store.update_character(self.project, c.character_id,
                                              expected_revision=1, goal="새 목표")
        self.assertEqual(revised.revision, 2)
        self.assertEqual(revised.goal, "새 목표")
        self.assertEqual(self.store.get_project(self.project).revision, 2)

    def test_partial_update_preserves_other_fields(self):
        c = self.add()
        revised = self.store.update_character(self.project, c.character_id,
                                              expected_revision=1, personality="새 성격")
        self.assertEqual(revised.secret, c.secret)
        self.assertEqual(revised.speech_style, c.speech_style)
        self.assertEqual(revised.goal, c.goal)
        self.assertEqual(revised.name, c.name)

    def test_update_all_fields(self):
        c = self.add()
        revised = self.store.update_character(
            self.project, c.character_id, expected_revision=1, name="동료",
            personality="성격2", goal="목표2", speech_style="말투2", secret="비밀2")
        self.assertEqual((revised.name, revised.personality, revised.goal,
                          revised.speech_style, revised.secret),
                         ("동료", "성격2", "목표2", "말투2", "비밀2"))

    def test_optional_empty_secret(self):
        c = self.add(secret="")
        self.assertEqual(c.secret, "")

    def test_secret_can_be_cleared(self):
        c = self.add()
        self.assertEqual(self.store.update_character(self.project, c.character_id,
                         expected_revision=1, secret="").secret, "")

    def test_reopen_after_update(self):
        c = self.add()
        self.store.update_character(self.project, c.character_id,
                                    expected_revision=1, speech_style="새로운 말투")
        with CharacterStore(self.db) as reopened:
            self.assertEqual(reopened.get_character(self.project, c.character_id).speech_style,
                             "새로운 말투")

    def test_multiple_characters_sorted(self):
        self.add(name="나")
        self.add(name="가")
        self.assertEqual([c.name for c in self.store.list_characters(self.project)], ["가", "나"])

    def test_project_isolation(self):
        c = self.add()
        other = self.store.create_project("다른 작품").project_id
        self.assertEqual(self.store.list_characters(other), ())
        with self.assertRaises(CharacterError):
            self.store.get_character(other, c.character_id)
        with self.assertRaises(CharacterError):
            self.store.update_character(other, c.character_id, expected_revision=1, goal="탈취")
        with self.assertRaises(CharacterError):
            self.store.delete_character(other, c.character_id, expected_revision=1)
        self.assertEqual(self.store.get_character(self.project, c.character_id), c)

    def test_same_name_different_project_allowed(self):
        self.add()
        other = self.store.create_project("두번째").project_id
        self.assertEqual(self.store.create_character(other, **self.data).name, "주인공")

    def test_duplicate_name_same_project_rejected_atomically(self):
        self.add()
        with self.assertRaises(CharacterError):
            self.add()
        self.assertEqual(len(self.store.list_characters(self.project)), 1)
        self.assertEqual(self.store.get_project(self.project).revision, 1)

    def test_rename_to_duplicate_rolls_back(self):
        self.add()
        c = self.add(name="조연")
        with self.assertRaises(CharacterError):
            self.store.update_character(self.project, c.character_id,
                                        expected_revision=1, name="주인공")
        self.assertEqual(self.store.get_character(self.project, c.character_id).name, "조연")
        self.assertEqual(self.store.get_project(self.project).revision, 2)

    def test_stale_revision_rejected(self):
        c = self.add()
        self.store.update_character(self.project, c.character_id,
                                    expected_revision=1, goal="바뀐 목표")
        with self.assertRaises(CharacterError):
            self.store.update_character(self.project, c.character_id,
                                        expected_revision=1, secret="덮어쓰기")
        self.assertEqual(self.store.get_character(self.project, c.character_id).secret,
                         self.data["secret"])
        self.assertEqual(self.store.get_project(self.project).revision, 2)

    def test_stale_revision_two_connections(self):
        c = self.add()
        with CharacterStore(self.db) as other:
            other.update_character(self.project, c.character_id,
                                   expected_revision=1, goal="다른 창에서 수정")
            with self.assertRaises(CharacterError):
                self.store.update_character(self.project, c.character_id,
                                            expected_revision=1, goal="오래된 수정")

    def test_no_change_rejected(self):
        c = self.add()
        with self.assertRaises(CharacterError):
            self.store.update_character(self.project, c.character_id, expected_revision=1)
        self.assertEqual(self.store.get_project(self.project).revision, 1)

    def test_delete_requires_revision(self):
        c = self.add()
        with self.assertRaises(CharacterError):
            self.store.delete_character(self.project, c.character_id, expected_revision=2)
        self.assertEqual(self.store.get_project(self.project).revision, 1)
        self.store.delete_character(self.project, c.character_id, expected_revision=1)
        self.assertEqual(self.store.list_characters(self.project), ())
        self.assertEqual(self.store.get_project(self.project).revision, 2)

    def test_delete_reopen(self):
        c = self.add()
        self.store.delete_character(self.project, c.character_id, expected_revision=1)
        with CharacterStore(self.db) as reopened:
            self.assertEqual(reopened.list_characters(self.project), ())

    def test_project_delete_cascades_to_characters(self):
        self.add()
        self.store.delete_project(self.project)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM bible_characters").fetchone()[0], 0)

    def test_invalid_project_rejected(self):
        with self.assertRaises(NovelBibleError):
            self.store.create_character("not-id", **self.data)
        with self.assertRaises(NovelBibleError):
            self.store.list_characters("not-id")

    def test_unknown_project_rejected(self):
        with self.assertRaises(NovelBibleError):
            self.store.create_character("f" * 32, **self.data)

    def test_invalid_character_id_rejected(self):
        with self.assertRaises(NovelBibleError):
            self.store.get_character(self.project, "../../secret")

    def test_invalid_revision_bool_rejected(self):
        c = self.add()
        with self.assertRaises(NovelBibleError):
            self.store.update_character(self.project, c.character_id,
                                        expected_revision=True, goal="test")

    def test_invalid_revision_zero_rejected(self):
        c = self.add()
        with self.assertRaises(NovelBibleError):
            self.store.delete_character(self.project, c.character_id, expected_revision=0)

    def test_invalid_empty_required_fields(self):
        for key in ("name", "personality", "goal", "speech_style"):
            with self.subTest(key=key), self.assertRaises(CharacterError):
                self.add(**{key: ""})

    def test_invalid_only_whitespace(self):
        with self.assertRaises(CharacterError):
            self.add(personality="   ")

    def test_invalid_name_padding(self):
        for name in (" 이름", "이름 "):
            with self.subTest(name=name), self.assertRaises(CharacterError):
                self.add(name=name)

    def test_invalid_newline_name(self):
        with self.assertRaises(CharacterError):
            self.add(name="이름\n둘")

    def test_invalid_control_secret(self):
        with self.assertRaises(CharacterError):
            self.add(secret="비밀\x00내용")

    def test_invalid_surrogate(self):
        with self.assertRaises(CharacterError):
            self.add(goal="\ud800")

    def test_invalid_length(self):
        with self.assertRaises(CharacterError):
            self.add(personality="가" * 4001)

    def test_invalid_utf8_byte_limit(self):
        with self.assertRaises(CharacterError):
            self.add(secret="가" * 3000)

    def test_invalid_name_byte_limit(self):
        with self.assertRaises(CharacterError):
            self.add(name="가" * 121)

    def test_invalid_type(self):
        with self.assertRaises(CharacterError):
            self.add(goal=123)

    def test_failed_validation_does_not_write(self):
        with self.assertRaises(CharacterError):
            self.add(secret="\x00")
        self.assertEqual(self.store.list_characters(self.project), ())
        self.assertEqual(self.store.get_project(self.project).revision, 0)

    def test_sql_metacharacters_are_data_not_sql(self):
        c = self.add(name="이름'); DROP TABLE bible_projects;--")
        self.assertEqual(self.store.get_character(self.project, c.character_id).name, c.name)
        self.assertEqual(len(self.store.list_projects()), 1)

    def test_corrupt_secret_rejected_without_echo(self):
        c = self.add()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE bible_characters SET secret=? WHERE character_id=?",
                         ("금지\x00민감문구", c.character_id))
        with self.assertRaises(CharacterError) as cm:
            self.store.get_character(self.project, c.character_id)
        self.assertNotIn("민감문구", str(cm.exception))

    def test_corrupt_revision_rejected(self):
        c = self.add()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("PRAGMA ignore_check_constraints=ON")
            conn.execute("UPDATE bible_characters SET revision=0 WHERE character_id=?",
                         (c.character_id,))
        with self.assertRaises(CharacterError):
            self.store.get_character(self.project, c.character_id)

    def test_corrupt_timestamp_rejected(self):
        c = self.add()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE bible_characters SET updated_at=? WHERE character_id=?",
                         ("invalid", c.character_id))
        with self.assertRaises(CharacterError):
            self.store.get_character(self.project, c.character_id)

    def test_missing_timezone_rejected(self):
        c = self.add()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE bible_characters SET updated_at=? WHERE character_id=?",
                         ("2026-01-01T00:00:00", c.character_id))
        with self.assertRaises(CharacterError):
            self.store.get_character(self.project, c.character_id)

    def test_multiline_user_authored_secret_supported(self):
        c = self.add(secret="1장에 공개하지 않는다.\n2장 이후에 밝힌다.")
        self.assertIn("\n", self.store.get_character(self.project, c.character_id).secret)

    def test_invalid_update_rolls_back_without_revision_bump(self):
        c = self.add()
        with self.assertRaises(CharacterError):
            self.store.update_character(self.project, c.character_id,
                                        expected_revision=1, secret="invalid\x00secret")
        self.assertEqual(self.store.get_character(self.project, c.character_id), c)
        self.assertEqual(self.store.get_project(self.project).revision, 1)

    def test_maximum_revision_cannot_overflow(self):
        c = self.add()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE bible_characters SET revision=? WHERE character_id=?",
                         (2**31 - 1, c.character_id))
        with self.assertRaises(CharacterError):
            self.store.update_character(self.project, c.character_id,
                                        expected_revision=2**31 - 1, goal="overflow")
        self.assertEqual(self.store.get_project(self.project).revision, 1)

    def test_stage41_project_deletion_cascades_after_reopen(self):
        self.add()
        with NovelBibleStore(self.db) as old:
            old.delete_project(self.project)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM bible_characters").fetchone()[0], 0)

    def test_identical_secrets_allowed_in_different_characters(self):
        first = self.add()
        second = self.add(name="조연")
        self.assertEqual(first.secret, second.secret)

    def test_posix_permissions_private(self):
        if os.name == "posix":
            self.assertEqual(self.db.stat().st_mode & 0o777, 0o600)


class CharacterCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "local.db"
        with CharacterStore(self.db) as store:
            self.project = store.create_project("로컬 작품").project_id
        self.inputs = {}
        for field, value in (("name", "인물명비공개"), ("personality", "성격비공개"),
                             ("goal", "목표비공개"), ("speech", "말투비공개"),
                             ("secret", "최상위비밀비공개")):
            path = self.root / (field + ".txt")
            path.write_text(value, encoding="utf-8")
            self.inputs[field] = path

    def run_cli(self, *args):
        out = StringIO()
        with redirect_stdout(out):
            status = character_cli(["--database", str(self.db), *args])
        return status, out.getvalue()

    def create(self):
        args = ["character-create", self.project]
        for key in ("name", "personality", "goal", "speech", "secret"):
            args.extend(["--" + key + "-file", str(self.inputs[key])])
        status, output = self.run_cli(*args)
        self.assertEqual(status, 0)
        self.assertNotIn("비공개", output)
        return output.split()[1]

    def test_create_files_no_plaintext_output(self):
        self.create()

    def test_list_redacted(self):
        uid = self.create()
        status, output = self.run_cli("character-list", self.project)
        self.assertEqual(status, 0)
        self.assertIn(uid, output)
        self.assertNotIn("비공개", output)

    def test_show_default_redacted(self):
        uid = self.create()
        status, output = self.run_cli("character-show", self.project, uid)
        self.assertEqual(status, 0)
        self.assertIn("[redacted", output)
        self.assertNotIn("비공개", output)

    def test_show_explicit_reveal(self):
        uid = self.create()
        status, output = self.run_cli("character-show", self.project, uid, "--reveal")
        self.assertEqual(status, 0)
        self.assertIn("최상위비밀비공개", output)
        self.assertIn("인물명비공개", output)

    def test_update_partial_from_file(self):
        uid = self.create()
        self.inputs["goal"].write_text("새 목표", encoding="utf-8")
        status, output = self.run_cli("character-update", self.project, uid,
                                      "--revision", "1", "--goal-file", str(self.inputs["goal"]))
        self.assertEqual(status, 0)
        self.assertIn("revision 2", output)
        with CharacterStore(self.db) as store:
            self.assertEqual(store.get_character(self.project, uid).goal, "새 목표")

    def test_update_clear_secret_from_empty_file(self):
        uid = self.create()
        self.inputs["secret"].write_text("", encoding="utf-8")
        status, _ = self.run_cli("character-update", self.project, uid,
                                 "--revision", "1", "--secret-file", str(self.inputs["secret"]))
        self.assertEqual(status, 0)
        with CharacterStore(self.db) as store:
            self.assertEqual(store.get_character(self.project, uid).secret, "")

    def test_stale_update_redacts_errors(self):
        uid = self.create()
        status, output = self.run_cli("character-update", self.project, uid,
                                      "--revision", "3", "--goal-file", str(self.inputs["goal"]))
        self.assertEqual(status, 1)
        self.assertNotIn("비공개", output)
        self.assertNotIn(str(self.inputs["goal"]), output)

    def test_delete_from_cli(self):
        uid = self.create()
        status, _ = self.run_cli("character-delete", self.project, uid, "--revision", "1")
        self.assertEqual(status, 0)
        status, output = self.run_cli("character-list", self.project)
        self.assertEqual(status, 0)
        self.assertEqual(output, "")

    def test_missing_file_rejected_without_path(self):
        args = ["character-create", self.project]
        for key in ("name", "personality", "goal", "speech"):
            args.extend(["--" + key + "-file", str(self.inputs[key])])
        missing = self.root / "private-do-not-print.txt"
        args.extend(["--secret-file", str(missing)])
        status, output = self.run_cli(*args)
        self.assertEqual(status, 1)
        self.assertNotIn(str(missing), output)

    def test_oversize_input_rejected(self):
        self.inputs["goal"].write_text("가" * 3000, encoding="utf-8")
        args = ["character-create", self.project]
        for key in ("name", "personality", "goal", "speech"):
            args.extend(["--" + key + "-file", str(self.inputs[key])])
        status, output = self.run_cli(*args)
        self.assertEqual(status, 1)
        self.assertNotIn("가", output)

    def test_symlink_input_rejected(self):
        link = self.root / "link.txt"
        try:
            link.symlink_to(self.inputs["name"])
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not available")
        args = ["character-create", self.project, "--name-file", str(link)]
        for key in ("personality", "goal", "speech"):
            args.extend(["--" + key + "-file", str(self.inputs[key])])
        status, _ = self.run_cli(*args)
        self.assertEqual(status, 1)

    def test_reject_sqlite_uri_path(self):
        status, _ = self.run_cli("character-list", self.project)
        self.assertEqual(status, 0)
        with redirect_stdout(StringIO()):
            self.assertEqual(character_cli(["--database", "file:remote?mode=ro",
                                            "character-list", self.project]), 1)

    def test_module_entrypoint_in_separate_process(self):
        root = Path(__file__).resolve().parents[1]
        env = {**os.environ, "PYTHONPATH": str(root / "src")}
        result = subprocess.run(
            [sys.executable, "-m", "ai_novel_factory.database.character_cli",
             "--database", str(self.db), "character-list", self.project],
            cwd=root, env=env, capture_output=True, text=True, timeout=15,
            check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_no_external_network_called(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            self.create()
            self.run_cli("character-list", self.project)
