"""Stage 41: real offline SQLite canon persistence and precedence tests."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory.database.novel_bible import (
    NovelBibleError, NovelBibleStore, _safe_statistics,
)
from ai_novel_factory.database.novel_bible_cli import main
from ai_novel_factory.references.element_selection import FEATURE_KEYS


class BibleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "bible.sqlite"
        self.store = NovelBibleStore(self.path)
        self.addCleanup(self.store.close)
        self.project = self.store.create_project("새로운 세계")

    def test_new_project(self):
        self.assertEqual(self.project.revision, 0)
        self.assertEqual(len(self.project.project_id), 32)
        self.assertEqual(self.store.get_project(self.project.project_id), self.project)

    def test_local_persistence_after_restart(self):
        self.store.save_rule(self.project.project_id, "premise", "바다는 하늘에 떠 있다")
        with NovelBibleStore(self.path) as reopened:
            self.assertEqual(reopened.get_rule(self.project.project_id, "premise").value,
                             "바다는 하늘에 떠 있다")
            self.assertEqual(reopened.get_project(self.project.project_id).revision, 1)

    def test_multiple_projects_isolated(self):
        other = self.store.create_project("다른 작품")
        self.store.save_rule(self.project.project_id, "canon", "첫 번째")
        self.store.save_rule(other.project_id, "canon", "두 번째")
        self.assertEqual(self.store.get_rule(other.project_id, "canon").value, "두 번째")
        self.assertEqual(len(self.store.list_rules(self.project.project_id)), 1)

    def test_user_bible_overrides_reference_numeric(self):
        key = FEATURE_KEYS[0]
        self.store.save_rule(self.project.project_id, key, "대사보다는 서술을 우선")
        resolved = self.store.resolve_context(self.project.project_id, {key: 99.0})
        self.assertEqual(resolved.overridden_reference_keys, (key,))
        self.assertEqual(resolved.fields[0].value, "대사보다는 서술을 우선")
        self.assertEqual(resolved.fields[0].source, "novel_bible")

    def test_reference_cannot_override_canon_even_if_repeated(self):
        key = FEATURE_KEYS[0]
        self.store.save_rule(self.project.project_id, key, "사용자 규칙")
        for number in (0, 1, 99, 100000):
            result = self.store.resolve_context(self.project.project_id, {key: number})
            self.assertEqual(next(f.value for f in result.fields if f.key == key), "사용자 규칙")

    def test_other_numeric_statistics_survive_without_overwriting(self):
        self.store.save_rule(self.project.project_id, "canon", "사용자 설정")
        key = FEATURE_KEYS[0]
        result = self.store.resolve_context(self.project.project_id, {key: 12.5})
        self.assertEqual(len(result.fields), 2)
        self.assertEqual(next(f.value for f in result.fields if f.key == key), 12.5)
        self.assertEqual(next(f.source for f in result.fields if f.key == key), "reference_statistic")

    def test_empty_bible_fails_closed(self):
        with self.assertRaises(NovelBibleError):
            self.store.resolve_context(self.project.project_id, {FEATURE_KEYS[0]: 10})

    def test_missing_project_fails(self):
        with self.assertRaises(NovelBibleError):
            self.store.resolve_context("f" * 32)

    def test_reference_stats_are_not_persisted(self):
        self.store.save_rule(self.project.project_id, "canon", "독립 창작")
        self.store.resolve_context(self.project.project_id, {FEATURE_KEYS[0]: 123456.0})
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            self.assertEqual({r[0] for r in rows}, {"bible_projects", "bible_rules"})
            values = conn.execute("SELECT rule_value FROM bible_rules").fetchall()
            self.assertEqual(values, [("독립 창작",)])

    def test_create_and_update_version(self):
        r1 = self.store.save_rule(self.project.project_id, "canon", "첫 규칙")
        r2 = self.store.save_rule(self.project.project_id, "canon", "수정", expected_revision=1)
        self.assertEqual((r1.revision, r2.revision), (1, 2))
        self.assertEqual(self.store.get_project(self.project.project_id).revision, 2)

    def test_update_without_revision_rejected(self):
        self.store.save_rule(self.project.project_id, "canon", "처음")
        with self.assertRaises(NovelBibleError):
            self.store.save_rule(self.project.project_id, "canon", "덮어쓰기")
        self.assertEqual(self.store.get_rule(self.project.project_id, "canon").value, "처음")

    def test_stale_revision_rejected(self):
        self.store.save_rule(self.project.project_id, "canon", "처음")
        self.store.save_rule(self.project.project_id, "canon", "둘째", expected_revision=1)
        with self.assertRaises(NovelBibleError):
            self.store.save_rule(self.project.project_id, "canon", "셋째", expected_revision=1)
        self.assertEqual(self.store.get_project(self.project.project_id).revision, 2)

    def test_stale_revision_across_connections(self):
        self.store.save_rule(self.project.project_id, "canon", "처음")
        with NovelBibleStore(self.path) as other:
            other.save_rule(self.project.project_id, "canon", "둘째", expected_revision=1)
            with self.assertRaises(NovelBibleError):
                self.store.save_rule(self.project.project_id, "canon", "셋째", expected_revision=1)

    def test_create_with_nonempty_expected_revision_rejected(self):
        with self.assertRaises(NovelBibleError):
            self.store.save_rule(self.project.project_id, "canon", "값", expected_revision=1)

    def test_delete_requires_current_revision(self):
        self.store.save_rule(self.project.project_id, "canon", "값")
        with self.assertRaises(NovelBibleError):
            self.store.delete_rule(self.project.project_id, "canon", expected_revision=2)
        self.store.delete_rule(self.project.project_id, "canon", expected_revision=1)
        self.assertEqual(self.store.list_rules(self.project.project_id), ())

    def test_project_delete_cascades(self):
        self.store.save_rule(self.project.project_id, "canon", "값")
        self.store.delete_project(self.project.project_id)
        with self.assertRaises(NovelBibleError):
            self.store.get_rule(self.project.project_id, "canon")
        with self.assertRaises(NovelBibleError):
            self.store.get_project(self.project.project_id)

    def test_project_listing(self):
        self.store.create_project("추가")
        self.assertEqual(len(self.store.list_projects()), 2)

    def test_rule_order_stable(self):
        self.store.save_rule(self.project.project_id, "zeta", "끝")
        self.store.save_rule(self.project.project_id, "alpha", "처음")
        self.assertEqual([r.key for r in self.store.list_rules(self.project.project_id)],
                         ["alpha", "zeta"])

    def test_delete_missing_rule_fails(self):
        with self.assertRaises(NovelBibleError):
            self.store.delete_rule(self.project.project_id, "none", expected_revision=1)

    def test_delete_missing_project_fails(self):
        with self.assertRaises(NovelBibleError):
            self.store.delete_project("f" * 32)

    def test_invalid_id_rejected(self):
        for invalid in ("x", "../path", "f" * 33, None, 1, "F" * 32):
            with self.subTest(invalid=invalid), self.assertRaises(NovelBibleError):
                self.store.get_project(invalid)

    def test_invalid_keys_rejected(self):
        for invalid in ("", "Upper", "한글", "foo.bar", "foo/bar", "a" * 65, 4, None):
            with self.subTest(invalid=invalid), self.assertRaises(NovelBibleError):
                self.store.save_rule(self.project.project_id, invalid, "값")

    def test_invalid_titles_rejected(self):
        for invalid in ("", "  ", "a" * 121, "abc\nxyz", "bad\x00", 9):
            with self.subTest(invalid=invalid), self.assertRaises(NovelBibleError):
                self.store.create_project(invalid)

    def test_invalid_values_rejected(self):
        for invalid in ("", "   ", "a" * 4001, "a\x00b", 10, None, "a" * 100 + "\x1b"):
            with self.subTest(invalid=invalid), self.assertRaises(NovelBibleError):
                self.store.save_rule(self.project.project_id, "canon", invalid)

    def test_unpaired_surrogate_rejected_safely(self):
        with self.assertRaises(NovelBibleError):
            self.store.save_rule(self.project.project_id, "canon", "\ud800")

    def test_unicode_byte_limit(self):
        with self.assertRaises(NovelBibleError):
            self.store.save_rule(self.project.project_id, "canon", "한" * 3000)

    def test_multiline_unicode_value_allowed(self):
        value = "제1법칙\n\t시간은 거꾸로 흐른다"
        self.assertEqual(self.store.save_rule(self.project.project_id, "canon", value).value, value)

    def test_bool_revision_rejected(self):
        with self.assertRaises(NovelBibleError):
            self.store.save_rule(self.project.project_id, "canon", "값", expected_revision=True)

    def test_invalid_statistic_keys_rejected(self):
        self.store.save_rule(self.project.project_id, "canon", "값")
        for invalid in ({"reference_quote": 1.0}, {"__proto__": 1}, {"author": "원문"}):
            with self.subTest(invalid=invalid), self.assertRaises(NovelBibleError):
                self.store.resolve_context(self.project.project_id, invalid)

    def test_non_numeric_stats_rejected(self):
        for bad in ("문장", None, True, float("nan"), float("inf"), -float("inf"), 1e15):
            with self.subTest(bad=bad), self.assertRaises(NovelBibleError):
                _safe_statistics({FEATURE_KEYS[0]: bad})

    def test_stats_not_mapping_rejected(self):
        for invalid in ([], "hello", 123):
            with self.assertRaises(NovelBibleError):
                _safe_statistics(invalid)

    def test_all_allowed_feature_keys(self):
        self.store.save_rule(self.project.project_id, "canon", "기본 규칙")
        stats = {key: i / 3 for i, key in enumerate(FEATURE_KEYS)}
        result = self.store.resolve_context(self.project.project_id, stats)
        self.assertEqual(len(result.fields), len(FEATURE_KEYS) + 1)

    def test_bible_only_context(self):
        self.store.save_rule(self.project.project_id, "canon", "기본 규칙")
        result = self.store.resolve_context(self.project.project_id)
        self.assertEqual(result.overridden_reference_keys, ())
        self.assertEqual(result.fields[0].source, "novel_bible")

    def test_context_revision_tracks_edit(self):
        self.store.save_rule(self.project.project_id, "canon", "1")
        old = self.store.resolve_context(self.project.project_id)
        self.store.save_rule(self.project.project_id, "canon", "2", expected_revision=1)
        new = self.store.resolve_context(self.project.project_id)
        self.assertEqual((old.project_revision, new.project_revision), (1, 2))

    def test_database_local_file_permissions(self):
        if os.name == "posix":
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_missing_parent_rejected(self):
        with self.assertRaises(NovelBibleError):
            NovelBibleStore(Path(self.tmp.name) / "missing" / "bible.db")

    def test_remote_uri_rejected(self):
        for path in ("file:shared?mode=memory", "\\\\host\\share\\db", "//host/db"):
            with self.subTest(path=path), self.assertRaises(NovelBibleError):
                NovelBibleStore(path)

    def test_symlink_rejected(self):
        target = Path(self.tmp.name) / "link.db"
        try:
            target.symlink_to(self.path)
        except OSError:
            self.skipTest("symlink unavailable")
        with self.assertRaises(NovelBibleError):
            NovelBibleStore(target)

    def test_database_schema_has_foreign_keys(self):
        self.assertEqual(self.store._db.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_sql_injection_key_rejected(self):
        with self.assertRaises(NovelBibleError):
            self.store.save_rule(self.project.project_id, "x'); DROP TABLE bible_rules; --", "값")
        self.assertEqual(len(self.store.list_projects()), 1)

    def test_corrupt_value_fails_closed(self):
        self.store.save_rule(self.project.project_id, "canon", "값")
        with self.store._db:
            self.store._db.execute("UPDATE bible_rules SET rule_value='   '")
        with self.assertRaises(NovelBibleError):
            self.store.resolve_context(self.project.project_id)

    def test_corrupt_revision_fails_closed(self):
        self.store.save_rule(self.project.project_id, "canon", "값")
        with self.store._db:
            self.store._db.execute("UPDATE bible_rules SET revision=999999999999")
        with self.assertRaises(NovelBibleError):
            self.store.list_rules(self.project.project_id)

    def test_failed_save_does_not_increment_project_revision(self):
        with self.assertRaises(NovelBibleError):
            self.store.save_rule(self.project.project_id, "canon", "값", expected_revision=1)
        self.assertEqual(self.store.get_project(self.project.project_id).revision, 0)

    def test_save_and_resolve_without_socket_access(self):
        import socket
        with patch.object(socket, "socket", side_effect=AssertionError("network used")):
            self.store.save_rule(self.project.project_id, "canon", "완전 오프라인")
            result = self.store.resolve_context(self.project.project_id, {FEATURE_KEYS[0]: 20})
            self.assertEqual(len(result.fields), 2)

    def test_no_external_client_needed(self):
        self.assertEqual(self.store._db.execute("SELECT 1").fetchone()[0], 1)


class BibleCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "bible.db"
        self.value_file = Path(self.tmp.name) / "canon.txt"
        self.value_file.write_text("하늘 위 도시에는 해가 없다", encoding="utf-8")
        with NovelBibleStore(self.path) as db:
            self.project = db.create_project("작품")

    def call(self, *args):
        out = StringIO()
        with redirect_stdout(out):
            code = main(["--database", str(self.path), *args])
        return code, out.getvalue()

    def test_set_does_not_echo_content(self):
        code, out = self.call("rule-set", self.project.project_id, "canon", "--value-file", str(self.value_file))
        self.assertEqual(code, 0)
        self.assertNotIn("하늘", out)

    def test_rule_show_redacted_by_default(self):
        self.call("rule-set", self.project.project_id, "canon", "--value-file", str(self.value_file))
        code, out = self.call("rule-show", self.project.project_id, "canon")
        self.assertEqual(code, 0)
        self.assertNotIn("하늘", out)
        self.assertIn("redacted", out)

    def test_rule_show_explicit_reveal(self):
        self.call("rule-set", self.project.project_id, "canon", "--value-file", str(self.value_file))
        code, out = self.call("rule-show", self.project.project_id, "canon", "--reveal")
        self.assertEqual(code, 0)
        self.assertIn("하늘", out)

    def test_rule_list_never_prints_value(self):
        self.call("rule-set", self.project.project_id, "canon", "--value-file", str(self.value_file))
        code, out = self.call("rule-list", self.project.project_id)
        self.assertEqual(code, 0)
        self.assertNotIn("하늘", out)

    def test_cli_update_revision(self):
        self.call("rule-set", self.project.project_id, "canon", "--value-file", str(self.value_file))
        code, _ = self.call("rule-set", self.project.project_id, "canon", "--value-file",
                            str(self.value_file), "--revision", "1")
        self.assertEqual(code, 0)
        with NovelBibleStore(self.path) as db:
            self.assertEqual(db.get_rule(self.project.project_id, "canon").revision, 2)

    def test_cli_stale_update_fails_without_content(self):
        self.call("rule-set", self.project.project_id, "canon", "--value-file", str(self.value_file))
        code, out = self.call("rule-set", self.project.project_id, "canon", "--value-file", str(self.value_file))
        self.assertEqual(code, 1)
        self.assertNotIn("하늘", out)

    def test_cli_context_redacts_value(self):
        self.call("rule-set", self.project.project_id, "canon", "--value-file", str(self.value_file))
        stats = Path(self.tmp.name) / "statistics.json"
        stats.write_text(json.dumps({FEATURE_KEYS[0]: 1.5}), encoding="utf-8")
        code, out = self.call("context", self.project.project_id, "--statistics-file", str(stats))
        self.assertEqual(code, 0)
        self.assertIn("reference_statistic", out)
        self.assertNotIn("하늘", out)

    def test_cli_rejects_prose_in_statistics(self):
        self.call("rule-set", self.project.project_id, "canon", "--value-file", str(self.value_file))
        stats = Path(self.tmp.name) / "statistics.json"
        stats.write_text(json.dumps({"reference_quote": "참고작 원문"}), encoding="utf-8")
        code, out = self.call("context", self.project.project_id, "--statistics-file", str(stats))
        self.assertEqual(code, 1)
        self.assertNotIn("참고작", out)

    def test_cli_rejects_duplicate_statistics_keys(self):
        self.call("rule-set", self.project.project_id, "canon", "--value-file", str(self.value_file))
        stats = Path(self.tmp.name) / "statistics.json"
        stats.write_text('{"%s":1,"%s":2}' % (FEATURE_KEYS[0], FEATURE_KEYS[0]))
        code, _ = self.call("context", self.project.project_id, "--statistics-file", str(stats))
        self.assertEqual(code, 1)

    def test_cli_project_list_redacts_title(self):
        code, out = self.call("project-list")
        self.assertEqual(code, 0)
        self.assertNotIn("작품", out)

    def test_cli_delete_rule(self):
        self.call("rule-set", self.project.project_id, "canon", "--value-file", str(self.value_file))
        code, _ = self.call("rule-delete", self.project.project_id, "canon", "--revision", "1")
        self.assertEqual(code, 0)

    def test_cli_missing_value_file_safe(self):
        code, out = self.call("rule-set", self.project.project_id, "canon", "--value-file",
                              str(Path(self.tmp.name) / "missing.txt"))
        self.assertEqual(code, 1)
        self.assertNotIn("missing.txt", out)

    def test_cli_project_create(self):
        code, out = self.call("project-create", "두 번째")
        self.assertEqual(code, 0)
        self.assertIn("created", out)
        self.assertNotIn("두 번째", out)

    def test_cli_project_delete(self):
        code, _ = self.call("project-delete", self.project.project_id)
        self.assertEqual(code, 0)
        with NovelBibleStore(self.path) as db:
            self.assertEqual(db.list_projects(), ())

    def test_cli_context_empty_bible_fails(self):
        code, out = self.call("context", self.project.project_id)
        self.assertEqual(code, 1)
        self.assertIn("ERROR", out)


if __name__ == "__main__":
    unittest.main()
