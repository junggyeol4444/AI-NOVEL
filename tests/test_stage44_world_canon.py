"""ANF-REQ-034: five worldbuilding kinds, stable ID lookup, offline Novel Bible CRUD."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory.database.world_canon import (
    WORLD_CATEGORIES, WorldCanonError, WorldCanonStore, _category, _description, _name,
)
from ai_novel_factory.database.world_cli import main as world_cli
from ai_novel_factory.database.novel_bible import NovelBibleError, NovelBibleStore
from ai_novel_factory.database.characters import CharacterStore
from ai_novel_factory.database.character_knowledge import CharacterKnowledgeStore


class WorldCanonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "novel.db"
        self.store = WorldCanonStore(self.db)
        self.addCleanup(self.store.close)
        self.project = self.store.create_project("창작 세계").project_id
        self.item = self.store.create_entry(self.project, category="item", name="달의 검",
                                            description="빛나는 칼날을 지닌 무기")

    def new(self, *, category="region", name="북쪽 도시", description="눈 덮인 도시"):
        return self.store.create_entry(self.project, category=category,
                                       name=name, description=description)

    def test_all_five_categories(self):
        self.assertEqual(WORLD_CATEGORIES, {"worldview", "organization", "region", "ability", "item"})

    def test_all_categories_roundtrip(self):
        for kind in sorted(WORLD_CATEGORIES - {"item"}):
            with self.subTest(kind=kind):
                obj = self.new(category=kind, name=f"고유 {kind}")
                self.assertEqual(self.store.get_entry(self.project, obj.entry_id).category, kind)

    def test_identifier_is_32_hex(self):
        self.assertRegex(self.item.entry_id, r"\A[0-9a-f]{32}\Z")

    def test_identifier_lookup_returns_content(self):
        obj = self.store.get_entry(self.project, self.item.entry_id)
        self.assertEqual((obj.name, obj.description), ("달의 검", "빛나는 칼날을 지닌 무기"))

    def test_project_identifier_stored(self):
        self.assertEqual(self.item.project_id, self.project)

    def test_revision_starts_one(self):
        self.assertEqual(self.item.revision, 1)

    def test_timestamps_timezone_aware(self):
        from datetime import datetime
        for stamp in (self.item.created_at, self.item.updated_at):
            self.assertIsNotNone(datetime.fromisoformat(stamp).utcoffset())

    def test_category_filter(self):
        self.new(category="region")
        self.new(category="ability", name="방벽술")
        self.assertEqual([e.category for e in self.store.list_entries(self.project, category="item")],
                         ["item"])

    def test_category_filter_empty(self):
        self.assertEqual(self.store.list_entries(self.project, category="organization"), ())

    def test_all_categories_sorted(self):
        self.new(category="region")
        self.new(category="ability", name="방벽술")
        self.assertEqual([e.category for e in self.store.list_entries(self.project)],
                         ["ability", "item", "region"])

    def test_same_category_names_sorted(self):
        self.new(name="Z 구역")
        self.new(name="A 구역")
        self.assertEqual([e.name for e in self.store.list_entries(self.project, category="region")],
                         ["A 구역", "Z 구역"])

    def test_same_name_different_category_allowed(self):
        obj = self.new(category="region", name="달의 검")
        self.assertNotEqual(obj.entry_id, self.item.entry_id)

    def test_duplicate_same_category_rejected(self):
        with self.assertRaises(WorldCanonError):
            self.new(category="item", name="달의 검")

    def test_duplicate_rejected_without_project_bump(self):
        old = self.store.get_project(self.project).revision
        with self.assertRaises(WorldCanonError):
            self.new(category="item", name="달의 검")
        self.assertEqual(self.store.get_project(self.project).revision, old)

    def test_two_projects_same_name_allowed(self):
        other = self.store.create_project("다른 작품").project_id
        obj = self.store.create_entry(other, category="item", name="달의 검", description="다른 규칙")
        self.assertNotEqual(obj.entry_id, self.item.entry_id)

    def test_other_project_id_cannot_read(self):
        other = self.store.create_project("다른 작품").project_id
        with self.assertRaises(WorldCanonError):
            self.store.get_entry(other, self.item.entry_id)

    def test_other_project_list_empty(self):
        other = self.store.create_project("다른 작품").project_id
        self.assertEqual(self.store.list_entries(other), ())

    def test_other_project_cannot_update(self):
        other = self.store.create_project("다른 작품").project_id
        with self.assertRaises(WorldCanonError):
            self.store.update_entry(other, self.item.entry_id, expected_revision=1, name="다른 검")
        self.assertEqual(self.store.get_entry(self.project, self.item.entry_id).name, "달의 검")

    def test_other_project_cannot_delete(self):
        other = self.store.create_project("다른 작품").project_id
        with self.assertRaises(WorldCanonError):
            self.store.delete_entry(other, self.item.entry_id, expected_revision=1)
        self.store.get_entry(self.project, self.item.entry_id)

    def test_missing_entry_rejected(self):
        with self.assertRaises(WorldCanonError):
            self.store.get_entry(self.project, "0" * 32)

    def test_missing_project_rejected(self):
        with self.assertRaises(NovelBibleError):
            self.store.list_entries("0" * 32)

    def test_invalid_category_values(self):
        for value in ("", "world", "items", "ITEM", "organization ", None, 2, True, b"item"):
            with self.subTest(value=value), self.assertRaises(WorldCanonError):
                _category(value)

    def test_invalid_name_values(self):
        for value in ("", "   ", " x", "x ", "x\n", "x\t", "x" * 121, None, 5, True):
            with self.subTest(value=value), self.assertRaises(WorldCanonError):
                _name(value)

    def test_invalid_description_values(self):
        for value in ("", "  ", "x" * 4001, None, 1, True, "\x00", "x\x7f"):
            with self.subTest(value=value), self.assertRaises(WorldCanonError):
                _description(value)

    def test_utf8_byte_limit(self):
        with self.assertRaises(WorldCanonError):
            _description("가" * 2800)

    def test_multiline_description_accepted(self):
        obj = self.new(description="첫째 규칙\n둘째 규칙")
        self.assertIn("\n", self.store.get_entry(self.project, obj.entry_id).description)

    def test_unicode_name_accepted(self):
        obj = self.new(name="태양의 궁전 ✨")
        self.assertIn("✨", obj.name)

    def test_invalid_create_does_not_write(self):
        before = self.store.get_project(self.project).revision
        with self.assertRaises(WorldCanonError):
            self.new(description="")
        self.assertEqual(self.store.get_project(self.project).revision, before)

    def test_create_bumps_parent_revision(self):
        before = self.store.get_project(self.project).revision
        self.new()
        self.assertEqual(self.store.get_project(self.project).revision, before + 1)

    def test_update_name(self):
        obj = self.store.update_entry(self.project, self.item.entry_id,
                                      expected_revision=1, name="은빛 검")
        self.assertEqual((obj.name, obj.revision, obj.entry_id), ("은빛 검", 2, self.item.entry_id))

    def test_update_description(self):
        obj = self.store.update_entry(self.project, self.item.entry_id,
                                      expected_revision=1, description="새로운 규칙")
        self.assertEqual(obj.description, "새로운 규칙")

    def test_update_category(self):
        obj = self.store.update_entry(self.project, self.item.entry_id,
                                      expected_revision=1, category="ability")
        self.assertEqual(obj.category, "ability")
        self.assertEqual(len(self.store.list_entries(self.project, category="item")), 0)

    def test_update_multiple_fields(self):
        obj = self.store.update_entry(self.project, self.item.entry_id, expected_revision=1,
                                      category="worldview", name="마력 법칙", description="마력은 유한하다")
        self.assertEqual((obj.category, obj.name, obj.description),
                         ("worldview", "마력 법칙", "마력은 유한하다"))

    def test_update_bumps_parent_revision(self):
        before = self.store.get_project(self.project).revision
        self.store.update_entry(self.project, self.item.entry_id,
                                expected_revision=1, description="새로운 규칙")
        self.assertEqual(self.store.get_project(self.project).revision, before + 1)

    def test_update_requires_revision(self):
        with self.assertRaises(NovelBibleError):
            self.store.update_entry(self.project, self.item.entry_id,
                                    expected_revision=None, description="수정")

    def test_update_stale_revision_rejected(self):
        self.store.update_entry(self.project, self.item.entry_id,
                                expected_revision=1, name="검 A")
        with self.assertRaises(WorldCanonError):
            self.store.update_entry(self.project, self.item.entry_id,
                                    expected_revision=1, name="검 B")
        self.assertEqual(self.store.get_entry(self.project, self.item.entry_id).name, "검 A")

    def test_update_no_changes_rejected(self):
        with self.assertRaises(WorldCanonError):
            self.store.update_entry(self.project, self.item.entry_id, expected_revision=1)

    def test_update_invalid_value_rolls_back(self):
        before = self.store.get_project(self.project).revision
        with self.assertRaises(WorldCanonError):
            self.store.update_entry(self.project, self.item.entry_id,
                                    expected_revision=1, name="invalid ")
        self.assertEqual(self.store.get_project(self.project).revision, before)

    def test_update_collision_rolls_back(self):
        self.new(category="item", name="별의 검")
        before = self.store.get_project(self.project).revision
        with self.assertRaises(WorldCanonError):
            self.store.update_entry(self.project, self.item.entry_id,
                                    expected_revision=1, name="별의 검")
        self.assertEqual(self.store.get_project(self.project).revision, before)
        self.assertEqual(self.store.get_entry(self.project, self.item.entry_id).revision, 1)

    def test_category_change_collision_rolls_back(self):
        self.new(category="region", name="달의 검")
        with self.assertRaises(WorldCanonError):
            self.store.update_entry(self.project, self.item.entry_id,
                                    expected_revision=1, category="region")
        self.assertEqual(self.store.get_entry(self.project, self.item.entry_id).category, "item")

    def test_revision_limit(self):
        with self.assertRaises(WorldCanonError):
            self.store.update_entry(self.project, self.item.entry_id,
                                    expected_revision=2**31 - 1, name="X")

    def test_delete_existing(self):
        self.store.delete_entry(self.project, self.item.entry_id, expected_revision=1)
        self.assertEqual(self.store.list_entries(self.project), ())

    def test_delete_bumps_parent_revision(self):
        before = self.store.get_project(self.project).revision
        self.store.delete_entry(self.project, self.item.entry_id, expected_revision=1)
        self.assertEqual(self.store.get_project(self.project).revision, before + 1)

    def test_delete_wrong_revision_fails(self):
        with self.assertRaises(WorldCanonError):
            self.store.delete_entry(self.project, self.item.entry_id, expected_revision=2)
        self.store.get_entry(self.project, self.item.entry_id)

    def test_delete_missing_fails(self):
        with self.assertRaises(WorldCanonError):
            self.store.delete_entry(self.project, "0" * 32, expected_revision=1)

    def test_delete_project_cascades(self):
        self.store.delete_project(self.project)
        count = self.store._db.execute("SELECT count(*) FROM bible_world_entries").fetchone()[0]
        self.assertEqual(count, 0)

    def test_reopen_persists(self):
        with WorldCanonStore(self.db) as reopened:
            self.assertEqual(reopened.get_entry(self.project, self.item.entry_id), self.item)

    def test_reopen_after_update_persists(self):
        self.store.update_entry(self.project, self.item.entry_id,
                                expected_revision=1, description="고쳐 쓴 규칙")
        with WorldCanonStore(self.db) as reopened:
            self.assertEqual(reopened.get_entry(self.project, self.item.entry_id).revision, 2)

    def test_old_novel_bible_store_can_see_project(self):
        with NovelBibleStore(self.db) as reopened:
            self.assertEqual(reopened.get_project(self.project).revision, 1)

    def test_character_store_compatibility(self):
        with CharacterStore(self.db) as chars:
            c = chars.create_character(self.project, name="검사", personality="성실",
                                       goal="탐험", speech_style="정중")
            self.assertEqual(chars.get_character(self.project, c.character_id).name, "검사")
        self.assertEqual(len(self.store.list_entries(self.project)), 1)

    def test_knowledge_store_compatibility(self):
        with CharacterKnowledgeStore(self.db) as knowledge:
            fact = knowledge.create_fact(self.project, "세상의 비밀")
            self.assertEqual(knowledge.get_fact(self.project, fact.fact_id).description, "세상의 비밀")
        self.store.get_entry(self.project, self.item.entry_id)

    def test_rule_priority_unchanged(self):
        self.store.save_rule(self.project, "dialogue_ratio", "사용자 기준")
        result = self.store.resolve_context(self.project, {"dialogue_ratio": 0.5})
        self.assertEqual(next(x for x in result.fields if x.key == "dialogue_ratio").value,
                         "사용자 기준")

    def test_raw_sql_fk_prevents_orphan(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store._db:
                self.store._db.execute("""INSERT INTO bible_world_entries
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
                    ("1" * 32, "2" * 32, "item", "가짜", "설명", "2026-01-01T00:00:00+00:00",
                     "2026-01-01T00:00:00+00:00"))

    def test_raw_sql_category_check(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store._db:
                self.store._db.execute("UPDATE bible_world_entries SET category='unknown'")

    def test_raw_sql_unique_constraint(self):
        self.new(category="item", name="다른 검")
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store._db:
                self.store._db.execute("UPDATE bible_world_entries SET name='달의 검' WHERE name='다른 검'")

    def test_corrupt_timestamp_read_fails_closed(self):
        with self.store._db:
            self.store._db.execute("UPDATE bible_world_entries SET updated_at='bad' WHERE entry_id=?",
                                   (self.item.entry_id,))
        with self.assertRaises(WorldCanonError):
            self.store.get_entry(self.project, self.item.entry_id)

    def test_corrupt_revision_read_fails_closed(self):
        with self.store._db:
            self.store._db.execute("PRAGMA ignore_check_constraints=ON")
            self.store._db.execute("UPDATE bible_world_entries SET revision=0 WHERE entry_id=?",
                                   (self.item.entry_id,))
            self.store._db.execute("PRAGMA ignore_check_constraints=OFF")
        with self.assertRaises(WorldCanonError):
            self.store.get_entry(self.project, self.item.entry_id)

    def test_invalid_id_input(self):
        for value in ("abc", "z" * 32, None, True):
            with self.subTest(value=value), self.assertRaises(NovelBibleError):
                self.store.get_entry(self.project, value)

    def test_invalid_filter_category(self):
        with self.assertRaises(WorldCanonError):
            self.store.list_entries(self.project, category="character")

    def test_error_never_leaks_description(self):
        with self.assertRaises(WorldCanonError) as error:
            self.store.update_entry(self.project, self.item.entry_id,
                                    expected_revision=2, description="민감한 직접 창작 내용")
        self.assertNotIn("민감한", str(error.exception))

    def test_operations_do_not_need_network(self):
        with patch("socket.socket", side_effect=AssertionError("network access")):
            obj = self.new(category="worldview", name="법칙")
            self.store.get_entry(self.project, obj.entry_id)
            self.store.list_entries(self.project)
            self.store.update_entry(self.project, obj.entry_id, expected_revision=1,
                                    description="새 법칙")
            self.store.delete_entry(self.project, obj.entry_id, expected_revision=2)

    def test_no_publication_or_generation_api(self):
        for action in ("publish", "generate", "send_to_server", "upload", "import_reference"):
            self.assertFalse(hasattr(self.store, action))


class WorldCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "novel.db"
        with WorldCanonStore(self.db) as store:
            self.project = store.create_project("내 창작 세계").project_id
        self.name = Path(self.tmp.name) / "name.txt"
        self.description = Path(self.tmp.name) / "description.txt"
        self.name.write_text("금지된 탑", encoding="utf-8")
        self.description.write_text("비밀의 문이 있는 탑", encoding="utf-8")

    def cli(self, *args):
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = world_cli(["--database", str(self.db), *args])
        return code, buffer.getvalue()

    def create(self):
        code, output = self.cli("world-create", self.project, "--category", "region",
                                "--name-file", str(self.name),
                                "--description-file", str(self.description))
        self.assertEqual(code, 0)
        return output.split()[1]

    def test_create_output_redacted(self):
        entry_id = self.create()
        self.assertEqual(len(entry_id), 32)

    def test_list_output_redacted(self):
        entry_id = self.create()
        code, output = self.cli("world-list", self.project)
        self.assertEqual(code, 0)
        self.assertIn(entry_id, output)
        self.assertNotIn("금지된 탑", output)

    def test_show_redacted_by_default(self):
        entry_id = self.create()
        code, output = self.cli("world-show", self.project, entry_id)
        self.assertEqual(code, 0)
        self.assertNotIn("비밀의 문", output)
        self.assertIn("redacted", output)

    def test_show_reveal_explicit(self):
        entry_id = self.create()
        code, output = self.cli("world-show", self.project, entry_id, "--reveal")
        self.assertEqual(code, 0)
        self.assertIn("금지된 탑", output)
        self.assertIn("비밀의 문", output)

    def test_filter_list(self):
        self.create()
        code, output = self.cli("world-list", self.project, "--category", "item")
        self.assertEqual((code, output), (0, ""))

    def test_update_description(self):
        entry_id = self.create()
        self.description.write_text("수정된 장소", encoding="utf-8")
        code, output = self.cli("world-update", self.project, entry_id, "--revision", "1",
                                "--description-file", str(self.description))
        self.assertEqual(code, 0)
        self.assertIn("revision 2", output)
        self.assertNotIn("수정된 장소", output)

    def test_update_category(self):
        entry_id = self.create()
        code, output = self.cli("world-update", self.project, entry_id, "--revision", "1",
                                "--category", "worldview")
        self.assertEqual(code, 0)
        self.assertIn("worldview", output)

    def test_delete(self):
        entry_id = self.create()
        code, output = self.cli("world-delete", self.project, entry_id, "--revision", "1")
        self.assertEqual((code, output.strip()), (0, "deleted"))

    def test_wrong_revision_error_redacted(self):
        entry_id = self.create()
        code, output = self.cli("world-delete", self.project, entry_id, "--revision", "2")
        self.assertEqual(code, 1)
        self.assertNotIn("금지된 탑", output)

    def test_missing_file_error_redacted(self):
        code, output = self.cli("world-create", self.project, "--category", "item",
                                "--name-file", str(Path(self.tmp.name) / "missing.txt"),
                                "--description-file", str(self.description))
        self.assertEqual(code, 1)
        self.assertNotIn(self.tmp.name, output)

    def test_oversize_file_rejected(self):
        self.description.write_text("가" * 3000, encoding="utf-8")
        code, output = self.cli("world-create", self.project, "--category", "item",
                                "--name-file", str(self.name),
                                "--description-file", str(self.description))
        self.assertEqual(code, 1)
        self.assertIn("ERROR", output)

    def test_invalid_utf8_rejected(self):
        self.name.write_bytes(b"\xff\xfe")
        code, output = self.cli("world-create", self.project, "--category", "item",
                                "--name-file", str(self.name),
                                "--description-file", str(self.description))
        self.assertEqual(code, 1)
        self.assertNotIn(self.name.name, output)

    def test_symlink_input_rejected(self):
        link = Path(self.tmp.name) / "link.txt"
        try:
            link.symlink_to(self.name)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation not supported")
        code, output = self.cli("world-create", self.project, "--category", "item",
                                "--name-file", str(link),
                                "--description-file", str(self.description))
        self.assertEqual(code, 1)
        self.assertIn("ERROR", output)

    def test_unc_input_rejected_without_file_access(self):
        from ai_novel_factory.database.world_cli import _read
        for remote in (r"\\server\share\secret.txt", "//server/share/secret.txt", "file:remote.txt"):
            with self.subTest(remote=remote), patch(
                "ai_novel_factory.database.world_cli._local_text_file",
                side_effect=AssertionError("must not access remote path"),
            ), self.assertRaises(NovelBibleError):
                _read(Path(remote))

    def test_subprocess_offline(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        proc = subprocess.run([sys.executable, "-m", "ai_novel_factory.database.world_cli",
                               "--database", str(self.db), "world-list", self.project],
                              env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_cli_does_not_use_network(self):
        with patch("socket.socket", side_effect=AssertionError("network access")):
            self.create()


if __name__ == "__main__":
    unittest.main()
