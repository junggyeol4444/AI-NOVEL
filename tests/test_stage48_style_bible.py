"""Stage 48: local style canon, priority, generation-context and CLI tests."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from ai_novel_factory.database.novel_bible import NovelBibleError
from ai_novel_factory.database.style_bible import (
    StyleBibleError, StyleBibleStore, MAX_STYLE_BYTES, MAX_STYLE_RULES,
)
from ai_novel_factory.database.style_cli import main
from ai_novel_factory.references.element_selection import FEATURE_KEYS


class StyleBibleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "bible.db"
        self.store = StyleBibleStore(self.db)
        self.addCleanup(self.store.close)
        self.project = self.store.create_project("나만의 세계")
        self.pid = self.project.project_id

    def _ready(self):
        self.store.save_rule(self.pid, "premise", "인물은 시간을 되돌릴 수 없다")
        self.store.save_style_rule(self.pid, "tone", "절제된 문장으로 쓴다")

    def test_create_and_read(self):
        r = self.store.save_style_rule(self.pid, "tone", "차분한 말투")
        self.assertEqual((r.key, r.directive, r.revision), ("tone", "차분한 말투", 1))

    def test_creation_increments_project_revision(self):
        self.store.save_style_rule(self.pid, "tone", "차분한 말투")
        self.assertEqual(self.store.get_project(self.pid).revision, 1)

    def test_list_empty(self):
        self.assertEqual(self.store.list_style_rules(self.pid), ())

    def test_list_sorted(self):
        self.store.save_style_rule(self.pid, "voice", "짧게")
        self.store.save_style_rule(self.pid, "tone", "차분하게")
        self.assertEqual([r.key for r in self.store.list_style_rules(self.pid)], ["tone", "voice"])

    def test_update_revision(self):
        self.store.save_style_rule(self.pid, "tone", "차분하게")
        r = self.store.save_style_rule(self.pid, "tone", "경쾌하게", expected_revision=1)
        self.assertEqual((r.revision, r.directive), (2, "경쾌하게"))
        self.assertEqual(self.store.get_project(self.pid).revision, 2)

    def test_create_with_revision_rejected(self):
        with self.assertRaises(StyleBibleError):
            self.store.save_style_rule(self.pid, "tone", "절제", expected_revision=1)

    def test_update_without_revision_rejected(self):
        self.store.save_style_rule(self.pid, "tone", "절제")
        with self.assertRaises(StyleBibleError):
            self.store.save_style_rule(self.pid, "tone", "변경")

    def test_stale_revision_rejected(self):
        self.store.save_style_rule(self.pid, "tone", "절제")
        self.store.save_style_rule(self.pid, "tone", "변경", expected_revision=1)
        with self.assertRaises(StyleBibleError):
            self.store.save_style_rule(self.pid, "tone", "옛 변경", expected_revision=1)
        self.assertEqual(self.store.get_style_rule(self.pid, "tone").directive, "변경")

    def test_delete(self):
        self.store.save_style_rule(self.pid, "tone", "절제")
        self.store.delete_style_rule(self.pid, "tone", expected_revision=1)
        self.assertEqual(self.store.list_style_rules(self.pid), ())
        self.assertEqual(self.store.get_project(self.pid).revision, 2)

    def test_delete_stale_rejected(self):
        self.store.save_style_rule(self.pid, "tone", "절제")
        with self.assertRaises(StyleBibleError):
            self.store.delete_style_rule(self.pid, "tone", expected_revision=2)
        self.assertEqual(len(self.store.list_style_rules(self.pid)), 1)

    def test_delete_missing_rejected(self):
        with self.assertRaises(StyleBibleError):
            self.store.delete_style_rule(self.pid, "tone", expected_revision=1)

    def test_get_missing_rejected(self):
        with self.assertRaises(StyleBibleError):
            self.store.get_style_rule(self.pid, "tone")

    def test_missing_project_rejected(self):
        with self.assertRaises(NovelBibleError):
            self.store.save_style_rule("a" * 32, "tone", "절제")

    def test_invalid_ids(self):
        for value in ("", "abc", "A" * 32, "../", 2, None):
            with self.subTest(value=value), self.assertRaises(NovelBibleError):
                self.store.list_style_rules(value)

    def test_invalid_keys(self):
        for value in ("", "Tone", "../secret", "foo.bar", "한글", "a" * 65, None, 5):
            with self.subTest(value=value), self.assertRaises(StyleBibleError):
                self.store.save_style_rule(self.pid, value, "절제")

    def test_invalid_directives(self):
        for value in ("", "  ", "a" * 4001, "a\x00b", "a\x1bb", 0, None, "\ud800"):
            with self.subTest(value=repr(value)), self.assertRaises(StyleBibleError):
                self.store.save_style_rule(self.pid, "tone", value)

    def test_multiline_korean(self):
        value = "짧은 문장\n감탄사는 최소화\t(대사 제외)"
        self.assertEqual(self.store.save_style_rule(self.pid, "tone", value).directive, value)

    def test_utf8_byte_limit(self):
        with self.assertRaises(StyleBibleError):
            self.store.save_style_rule(self.pid, "tone", "한" * 3000)

    def test_revision_bool_rejected(self):
        with self.assertRaises(NovelBibleError):
            self.store.save_style_rule(self.pid, "tone", "절제", expected_revision=True)

    def test_revision_upper_bound(self):
        with self.assertRaises(StyleBibleError):
            self.store.save_style_rule(self.pid, "tone", "절제", expected_revision=2**31 - 1)

    def test_max_rules(self):
        for n in range(MAX_STYLE_RULES):
            self.store.save_style_rule(self.pid, f"rule_{n:02}", "간결하게")
        with self.assertRaises(StyleBibleError):
            self.store.save_style_rule(self.pid, "overflow", "절제")
        self.assertEqual(len(self.store.list_style_rules(self.pid)), MAX_STYLE_RULES)

    def test_max_bytes(self):
        for n in range(8):
            self.store.save_style_rule(self.pid, f"rule_{n:02}", "a" * 4000)
        with self.assertRaises(StyleBibleError):
            self.store.save_style_rule(self.pid, "overflow", "b" * 800)
        self.assertEqual(len(self.store.list_style_rules(self.pid)), 8)

    def test_max_bytes_update_rolls_back(self):
        for n in range(8):
            self.store.save_style_rule(self.pid, f"rule_{n:02}", "a" * 4000)
        self.store.save_style_rule(self.pid, "last", "b" * 500)
        before = self.store.get_project(self.pid).revision
        with self.assertRaises(StyleBibleError):
            self.store.save_style_rule(self.pid, "last", "c" * 1000, expected_revision=1)
        self.assertEqual(self.store.get_project(self.pid).revision, before)
        self.assertEqual(len(self.store.get_style_rule(self.pid, "last").directive), 500)

    def test_max_rules_replacement_allowed(self):
        for n in range(MAX_STYLE_RULES):
            self.store.save_style_rule(self.pid, f"rule_{n:02}", "절제")
        r = self.store.save_style_rule(self.pid, "rule_00", "조용하게", expected_revision=1)
        self.assertEqual(r.revision, 2)

    def test_restart_persistence(self):
        self.store.save_style_rule(self.pid, "tone", "단정한 문장")
        with StyleBibleStore(self.db) as reopened:
            self.assertEqual(reopened.get_style_rule(self.pid, "tone").directive, "단정한 문장")

    def test_project_isolation(self):
        other = self.store.create_project("다른 작품")
        self.store.save_style_rule(self.pid, "tone", "절제")
        self.assertEqual(self.store.list_style_rules(other.project_id), ())
        with self.assertRaises(StyleBibleError):
            self.store.get_style_rule(other.project_id, "tone")

    def test_project_deletion_cascades(self):
        self.store.save_style_rule(self.pid, "tone", "절제")
        self.store.delete_project(self.pid)
        self.assertEqual(self.store._db.execute("SELECT COUNT(*) FROM bible_style_rules").fetchone()[0], 0)

    def test_two_connections_stale_edit(self):
        self.store.save_style_rule(self.pid, "tone", "절제")
        with StyleBibleStore(self.db) as second:
            second.save_style_rule(self.pid, "tone", "짧게", expected_revision=1)
            with self.assertRaises(StyleBibleError):
                self.store.save_style_rule(self.pid, "tone", "길게", expected_revision=1)

    def test_corrupt_row_rejected(self):
        self.store.save_style_rule(self.pid, "tone", "절제")
        self.store._db.execute("UPDATE bible_style_rules SET directive='  ' WHERE project_id=?", (self.pid,))
        with self.assertRaises(StyleBibleError):
            self.store.get_style_rule(self.pid, "tone")

    def test_corrupt_timestamp_rejected(self):
        self.store.save_style_rule(self.pid, "tone", "절제")
        self.store._db.execute("UPDATE bible_style_rules SET updated_at='yesterday'")
        with self.assertRaises(StyleBibleError):
            self.store.list_style_rules(self.pid)

    def test_context_missing_novel_bible_fails(self):
        self.store.save_style_rule(self.pid, "tone", "절제")
        with self.assertRaises(StyleBibleError):
            self.store.build_generation_context(self.pid)

    def test_context_missing_style_bible_fails(self):
        self.store.save_rule(self.pid, "premise", "설정")
        with self.assertRaises(StyleBibleError):
            self.store.build_generation_context(self.pid)

    def test_context_with_user_canon_and_style(self):
        self._ready()
        ctx = self.store.build_generation_context(self.pid)
        self.assertEqual({f.key: f.value for f in ctx.fields},
                         {"premise": "인물은 시간을 되돌릴 수 없다", "tone": "절제된 문장으로 쓴다"})
        self.assertEqual({f.key: f.source for f in ctx.fields},
                         {"premise": "novel_bible", "tone": "style_bible"})

    def test_canon_overrides_style_same_key(self):
        self._ready()
        self.store.save_rule(self.pid, "tone", "사용자 최우선 말투")
        ctx = self.store.build_generation_context(self.pid)
        self.assertEqual(ctx.overridden_style_keys, ("tone",))
        self.assertEqual(next(f for f in ctx.fields if f.key == "tone").value,
                         "사용자 최우선 말투")

    def test_style_overrides_reference_stat(self):
        key = FEATURE_KEYS[0]
        self._ready()
        self.store.save_style_rule(self.pid, key, "통계보다 사용자 문체", expected_revision=None)
        ctx = self.store.build_generation_context(self.pid, {key: 3.5})
        self.assertEqual(ctx.overridden_reference_keys, (key,))
        self.assertEqual(next(f for f in ctx.fields if f.key == key).source, "style_bible")

    def test_canon_overrides_reference_and_style(self):
        key = FEATURE_KEYS[0]
        self._ready()
        self.store.save_style_rule(self.pid, key, "문체")
        self.store.save_rule(self.pid, key, "절대 규칙")
        ctx = self.store.build_generation_context(self.pid, {key: 5.0})
        self.assertEqual(ctx.overridden_style_keys, (key,))
        self.assertEqual(ctx.overridden_reference_keys, (key,))
        self.assertEqual(next(f for f in ctx.fields if f.key == key).value, "절대 규칙")

    def test_reference_stat_kept_when_not_overridden(self):
        self._ready()
        key = FEATURE_KEYS[0]
        ctx = self.store.build_generation_context(self.pid, {key: 1.25})
        self.assertEqual(next(f for f in ctx.fields if f.key == key).source,
                         "reference_statistic")

    def test_reject_reference_prose(self):
        self._ready()
        with self.assertRaises(NovelBibleError):
            self.store.build_generation_context(self.pid, {"reference_quote": "원문 복제"})

    def test_reject_bad_statistics(self):
        self._ready()
        for stats in ({FEATURE_KEYS[0]: float("nan")}, {FEATURE_KEYS[0]: "원문"},
                      {"unknown": 1}, {FEATURE_KEYS[0]: True}):
            with self.subTest(stats=stats), self.assertRaises(NovelBibleError):
                self.store.build_generation_context(self.pid, stats)

    def test_reference_stats_not_persisted(self):
        self._ready()
        self.store.build_generation_context(self.pid, {FEATURE_KEYS[0]: 3.0})
        self.assertNotIn(FEATURE_KEYS[0], [f.key for f in self.store.build_generation_context(self.pid).fields])

    def test_context_sorted_deterministically(self):
        self._ready()
        self.store.save_style_rule(self.pid, "voice", "대화는 자연스럽게")
        ctx = self.store.build_generation_context(self.pid)
        self.assertEqual(tuple(f.key for f in ctx.fields), tuple(sorted(f.key for f in ctx.fields)))
        self.assertEqual(ctx.style_rule_revisions, (("tone", 1), ("voice", 1)))

    def test_context_tracks_project_revision(self):
        self._ready()
        before = self.store.build_generation_context(self.pid)
        self.store.save_style_rule(self.pid, "tone", "간결한 문장", expected_revision=1)
        after = self.store.build_generation_context(self.pid)
        self.assertEqual(after.project_revision, before.project_revision + 1)
        self.assertEqual(after.style_rule_revisions, (("tone", 2),))

    def test_context_after_style_delete_fails(self):
        self._ready()
        self.store.delete_style_rule(self.pid, "tone", expected_revision=1)
        with self.assertRaises(StyleBibleError):
            self.store.build_generation_context(self.pid)

    def test_context_json_is_structured(self):
        self._ready()
        data = json.loads(self.store.build_generation_context(self.pid).to_json())
        self.assertEqual(data["schema"], "anf.generation_context.v1")
        self.assertEqual(data["publication_approved"], False)
        self.assertEqual(data["fields"][0]["source"], "novel_bible")

    def test_context_json_quotes_special_chars(self):
        self.store.save_rule(self.pid, "premise", "절대 법칙")
        self.store.save_style_rule(self.pid, "tone", '대사에 "따옴표"\n을 쓴다')
        data = json.loads(self.store.build_generation_context(self.pid).to_json())
        self.assertIn('"따옴표"\n', data["fields"][1]["value"])

    def test_context_json_has_no_remote_endpoints(self):
        self._ready()
        data = json.loads(self.store.build_generation_context(self.pid).to_json())
        self.assertNotIn("model_endpoint", data)
        self.assertNotIn("publish", data)

    def test_context_fails_closed_on_corrupt_style(self):
        self._ready()
        self.store._db.execute("UPDATE bible_style_rules SET directive='  '")
        with self.assertRaises(StyleBibleError):
            self.store.build_generation_context(self.pid)

    def test_context_snapshot_rollback_after_error(self):
        self.store.save_style_rule(self.pid, "tone", "절제")
        with self.assertRaises(StyleBibleError):
            self.store.build_generation_context(self.pid)
        self.store.save_rule(self.pid, "premise", "다시 정상")
        self.assertEqual(len(self.store.build_generation_context(self.pid).fields), 2)

    def test_cross_database_no_reference_import(self):
        self._ready()
        self.store.build_generation_context(self.pid, {FEATURE_KEYS[0]: 2.0})
        tables = {r[0] for r in self.store._db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("reference_raw_text", tables)

    def test_style_is_plaintext_local(self):
        self.store.save_style_rule(self.pid, "tone", "평문으로 저장")
        self.assertIn("평문으로 저장", self.db.read_bytes().decode("utf-8", errors="ignore"))

    def test_cli_set_show_redacted(self):
        path = Path(self.temp.name) / "rule.txt"
        path.write_text("비밀 문체 규칙", encoding="utf-8")
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["--database", str(self.db), "style-set", self.pid, "tone",
                                   "--directive-file", str(path)]), 0)
            self.assertEqual(main(["--database", str(self.db), "style-show", self.pid, "tone"]), 0)
        self.assertNotIn("비밀 문체 규칙", out.getvalue())
        self.assertIn("[redacted", out.getvalue())

    def test_cli_show_reveal(self):
        self.store.save_style_rule(self.pid, "tone", "명시적으로 공개")
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["--database", str(self.db), "style-show", self.pid,
                                   "tone", "--reveal"]), 0)
        self.assertIn("명시적으로 공개", out.getvalue())

    def test_cli_context_redacted(self):
        self._ready()
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["--database", str(self.db), "context", self.pid]), 0)
        self.assertIn("tone style_bible", out.getvalue())
        self.assertNotIn("절제된 문장", out.getvalue())

    def test_cli_context_reveal(self):
        self._ready()
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["--database", str(self.db), "context", self.pid,
                                   "--reveal"]), 0)
        self.assertEqual(json.loads(out.getvalue())["publication_approved"], False)

    def test_cli_context_statistics(self):
        self._ready()
        path = Path(self.temp.name) / "stats.json"
        path.write_text(json.dumps({FEATURE_KEYS[0]: 3.0}), encoding="utf-8")
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["--database", str(self.db), "context", self.pid,
                                   "--statistics-file", str(path)]), 0)
        self.assertIn("reference_statistic", out.getvalue())

    def test_cli_invalid_stats_redacted(self):
        self._ready()
        path = Path(self.temp.name) / "stats.json"
        path.write_text('{"reference_quote":"비공개 원문"}', encoding="utf-8")
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["--database", str(self.db), "context", self.pid,
                                   "--statistics-file", str(path)]), 1)
        self.assertNotIn("비공개 원문", out.getvalue())

    def test_cli_delete(self):
        self.store.save_style_rule(self.pid, "tone", "절제")
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["--database", str(self.db), "style-delete", self.pid,
                                   "tone", "--revision", "1"]), 0)
        self.assertEqual(self.store.list_style_rules(self.pid), ())

    def test_cli_list_no_content(self):
        self.store.save_style_rule(self.pid, "tone", "숨겨진 문체")
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["--database", str(self.db), "style-list", self.pid]), 0)
        self.assertNotIn("숨겨진 문체", out.getvalue())
        self.assertIn("tone", out.getvalue())

    def test_cli_remote_directive_path_rejected(self):
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["--database", str(self.db), "style-set", self.pid,
                                   "tone", "--directive-file", "//host/share/rule.txt"]), 1)
        self.assertNotIn("//host", out.getvalue())

    def test_cli_missing_file(self):
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["--database", str(self.db), "style-set", self.pid,
                                   "tone", "--directive-file", "missing.txt"]), 1)

    def test_cli_subprocess(self):
        self._ready()
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        result = subprocess.run([sys.executable, "-m", "ai_novel_factory.database.style_cli",
                                 "--database", str(self.db), "context", self.pid],
                                capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("절제된 문장", result.stdout)

    def test_cli_help(self):
        out = StringIO()
        with self.assertRaises(SystemExit) as cm, redirect_stdout(out):
            main(["--help"])
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("Style Bible", out.getvalue())


if __name__ == "__main__":
    unittest.main()
