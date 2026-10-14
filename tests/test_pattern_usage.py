"""Stage 37 regression: opt-in anonymous usage journal and local-only CLI/UI."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
import importlib.util
import io
import shutil
import socket
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory.database import ReferenceCatalog
from ai_novel_factory.database.element_selections import ElementSelectionStore
from ai_novel_factory.database.genre_patterns import GenrePatternStore
from ai_novel_factory.database.pattern_strengths import PatternStrengthStore
from ai_novel_factory.database.pattern_usage import (
    PatternUsageError, PatternUsageRecord, PatternUsageStore, render_usage_record,
)
from ai_novel_factory.references.profile_cli import main as cli
from ai_novel_factory.references.profile_pipeline import import_reference_profile
from ai_novel_factory.references.related_pattern_search import RelatedPatternSearch

CANARY = "DO_NOT_LOG_PRIVATE_SOURCE_97513"
GENRES = ("fantasy", "romance", "mystery")


class PatternUsageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.tmp.name) / "base.sqlite3"
        cls.refs = {}
        with ReferenceCatalog(cls.base) as catalog:
            genres = GenrePatternStore(catalog)
            for g_index, genre in enumerate(GENRES):
                ids = []
                for i in range(3):
                    path = Path(cls.tmp.name) / f"private_{CANARY}_{g_index}_{i}.txt"
                    phrase = ("그는 위험했다. " if g_index == 0 else
                              "그녀는 기뻤다. " if g_index == 1 else "그런데 사실은. ")
                    path.write_text("제1화\n\n" + phrase*10 + "\n\n제2화\n\n" + phrase*10 + f"\n\n{chr(44032+i)}.", encoding="utf8")
                    imported = import_reference_profile(path, catalog=catalog)
                    rid = imported.reference.reference_id
                    ids.append(rid)
                    genres.assign(rid, genre)
                cls.refs[genre] = tuple(ids)
                genres.build(genre)
                genres.build(genre, weighting="characters")
            selection = ElementSelectionStore(catalog)
            selection.save("fantasy", ["dialogue_ratio", "emotion_balance"])
            selection.save("fantasy", ["dialogue_ratio"], weighting="characters")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "refs.sqlite3"
        shutil.copyfile(self.base, self.path)
        self.catalog = ReferenceCatalog(self.path)
        self.addCleanup(self.catalog.close)
        self.usage = PatternUsageStore(self.catalog)
        self.selections = ElementSelectionStore(self.catalog)
        self.genres = GenrePatternStore(self.catalog)
        self.strengths = PatternStrengthStore(self.catalog)

    def run_cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli(["--database", str(self.path), *args])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_record_same_genre(self):
        entry = self.usage.record("fantasy")
        self.assertEqual(entry.source_genre, "fantasy")
        self.assertEqual(entry.pattern_genre, "fantasy")
        self.assertIsNone(entry.similarity_percent)
        self.assertTrue(entry.current)
        self.assertEqual(len(entry.usage_id), 32)

    def test_record_related_genre(self):
        entry = self.usage.record("fantasy", pattern_genre="romance")
        self.assertEqual(entry.pattern_genre, "romance")
        self.assertGreaterEqual(entry.similarity_percent, 0)
        self.assertLessEqual(entry.similarity_percent, 100)
        self.assertTrue(entry.current)

    def test_record_uses_existing_related_search_safety(self):
        expected = next(x for x in RelatedPatternSearch(self.catalog).search("fantasy").matches
                        if x.genre == "romance")
        actual = self.usage.record("fantasy", pattern_genre="romance")
        self.assertEqual(actual.similarity_percent, expected.similarity_percent)

    def test_repeated_record_is_append_only(self):
        a, b = self.usage.record("fantasy"), self.usage.record("fantasy")
        self.assertNotEqual(a.usage_id, b.usage_id)
        self.assertEqual(self.usage.count(), 2)

    def test_list_is_newest_first(self):
        a, b = self.usage.record("fantasy"), self.usage.record("fantasy", pattern_genre="mystery")
        self.assertEqual([r.usage_id for r in self.usage.list()], [b.usage_id, a.usage_id])

    def test_get_unknown(self):
        with self.assertRaises(PatternUsageError):
            self.usage.get("0"*32)

    def test_reopened_catalog_persists_record(self):
        entry = self.usage.record("fantasy", pattern_genre="romance")
        self.catalog.close()
        with ReferenceCatalog(self.path) as other:
            retrieved = PatternUsageStore(other).get(entry.usage_id)
            self.assertEqual(retrieved, entry)

    def test_list_filters_source(self):
        self.usage.record("fantasy")
        self.assertEqual(len(self.usage.list(source_genre="fantasy")), 1)
        self.assertEqual(self.usage.list(source_genre="romance"), ())

    def test_list_filters_target(self):
        self.usage.record("fantasy")
        item = self.usage.record("fantasy", pattern_genre="romance")
        self.assertEqual(self.usage.list(pattern_genre="romance"), (item,))

    def test_page_limit_offset(self):
        records = [self.usage.record("fantasy") for _ in range(4)]
        self.assertEqual(self.usage.list(limit=2, offset=1), (records[2], records[1]))

    def test_filter_current_and_stale_before_offset(self):
        old = self.usage.record("fantasy")
        self.selections.save("fantasy", ["event_cue_density_per_1000"])
        new = self.usage.record("fantasy")
        self.assertEqual(self.usage.list(current=False), (replace(old, current=False),))
        self.assertEqual(self.usage.list(current=True), (new,))
        self.assertEqual(self.usage.list(current=False, offset=1), ())

    def test_delete_only_one_and_idempotent(self):
        a, b = self.usage.record("fantasy"), self.usage.record("fantasy")
        self.assertTrue(self.usage.delete(a.usage_id))
        self.assertFalse(self.usage.delete(a.usage_id))
        self.assertEqual(self.usage.list(), (b,))

    def test_deletion_does_not_delete_profiles_or_elements(self):
        before = self.catalog.count()
        entry = self.usage.record("fantasy")
        self.usage.delete(entry.usage_id)
        self.assertEqual(self.catalog.count(), before)
        self.assertEqual(self.selections.get("fantasy").selected_keys,
                         ("dialogue_ratio", "emotion_balance"))

    def test_selection_change_marks_old_record_stale(self):
        entry = self.usage.record("fantasy")
        self.selections.save("fantasy", ["lexical_diversity"])
        self.assertFalse(self.usage.get(entry.usage_id).current)

    def test_selection_deleted_marks_stale(self):
        entry = self.usage.record("fantasy")
        self.selections.delete("fantasy")
        self.assertFalse(self.usage.get(entry.usage_id).current)

    def test_source_genre_membership_change_marks_stale(self):
        entry = self.usage.record("fantasy")
        self.genres.unassign(self.refs["fantasy"][0])
        self.assertFalse(self.usage.get(entry.usage_id).current)

    def test_target_genre_membership_change_marks_stale(self):
        entry = self.usage.record("fantasy", pattern_genre="romance")
        self.genres.unassign(self.refs["romance"][0])
        self.assertFalse(self.usage.get(entry.usage_id).current)

    def test_target_deleted_marks_stale(self):
        entry = self.usage.record("fantasy", pattern_genre="romance")
        self.genres.delete("romance")
        self.assertFalse(self.usage.get(entry.usage_id).current)

    def test_strongly_overweighted_target_rejected(self):
        for rid in self.refs["romance"][1:]:
            self.strengths.set(rid, 0)
        with self.assertRaises(PatternUsageError):
            self.usage.record("fantasy", pattern_genre="romance")
        self.assertEqual(self.usage.count(), 0)

    def test_strongly_overweighted_source_rejected(self):
        for rid in self.refs["fantasy"][1:]:
            self.strengths.set(rid, 0)
        with self.assertRaises(PatternUsageError):
            self.usage.record("fantasy")

    def test_numeric_strength_change_marks_stale(self):
        item = self.usage.record("fantasy")
        self.strengths.set(self.refs["fantasy"][0], 60)
        self.assertFalse(self.usage.get(item.usage_id).current)

    def test_original_profile_unchanged_during_record(self):
        source = self.catalog.get(self.refs["fantasy"][0])
        self.usage.record("fantasy")
        self.assertEqual(self.catalog.get(source.reference_id), source)

    def test_no_raw_text_in_database_rows(self):
        self.usage.record("fantasy", pattern_genre="romance")
        # The copied reference metadata may contain fixture basenames;
        # the usage table specifically must never contain them.
        rows = self.catalog._db.execute("SELECT * FROM reference_pattern_usage").fetchall()
        as_text = repr(tuple(tuple(row) for row in rows))
        for forbidden in (CANARY, "private_", ".txt", "제1화", "위험했다"):
            self.assertNotIn(forbidden, as_text)
        self.assertEqual(len(rows), 1)

    def test_renderer_rejects_forged_source_text_timestamp(self):
        value = self.usage.record("fantasy")
        with self.assertRaises(PatternUsageError):
            render_usage_record(replace(value, created_at=CANARY))

    def test_renderer_is_only_fixed_labels(self):
        rendered = render_usage_record(self.usage.record("fantasy"))
        self.assertIn("기준 장르", rendered)
        for forbidden in (CANARY, "private_", ".txt", "제1화"):
            self.assertNotIn(forbidden, rendered)

    def test_network_is_not_used_for_record_and_list(self):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("external network")):
            entry = self.usage.record("fantasy")
            self.assertEqual(self.usage.list(), (entry,))

    def test_read_methods_never_append_usage(self):
        before = self.usage.count()
        RelatedPatternSearch(self.catalog).search("fantasy")
        self.usage.list()
        self.assertEqual(self.usage.count(), before)

    def test_invalid_genre_rejected_without_echoing_value(self):
        value = "nonexistent_' ; DROP TABLE x; --"
        with self.assertRaises(PatternUsageError) as caught:
            self.usage.record(value)
        self.assertNotIn(value, str(caught.exception))

    def test_missing_source_recipe_rejected(self):
        with self.assertRaises(PatternUsageError):
            self.usage.record("romance")

    def test_invalid_weighting(self):
        for value in ("invalid", None, True, 3):
            with self.subTest(value=value), self.assertRaises(PatternUsageError):
                self.usage.record("fantasy", weighting=value)

    def test_invalid_ids(self):
        for value in ("../file.txt", "a"*33, "", None, 123):
            with self.subTest(value=value), self.assertRaises(PatternUsageError):
                self.usage.get(value)
            with self.subTest(value=value), self.assertRaises(PatternUsageError):
                self.usage.delete(value)

    def test_invalid_paging_and_filters(self):
        for filters in ({"limit": 0}, {"limit": 101}, {"limit": True},
                        {"offset": -1}, {"offset": False}, {"current": "yes"},
                        {"source_genre": "fantasy' OR 1=1 --"},
                        {"pattern_genre": "wat"}):
            with self.subTest(filters=filters), self.assertRaises(PatternUsageError):
                self.usage.list(**filters)

    def test_corrupt_saved_keys(self):
        entry = self.usage.record("fantasy")
        self.catalog._db.execute("UPDATE reference_pattern_usage SET keys_json='[\"user phrase\"]'")
        self.catalog._db.commit()
        with self.assertRaises(PatternUsageError):
            self.usage.get(entry.usage_id)

    def test_corrupt_saved_signature(self):
        entry = self.usage.record("fantasy")
        self.catalog._db.execute("UPDATE reference_pattern_usage SET signature=?", ("a"*64,))
        self.catalog._db.commit()
        self.assertFalse(self.usage.get(entry.usage_id).current)

    def test_invalid_signature_format_rejected(self):
        entry = self.usage.record("fantasy")
        self.catalog._db.execute("UPDATE reference_pattern_usage SET signature=?", ("x"*64,))
        self.catalog._db.commit()
        with self.assertRaises(PatternUsageError):
            self.usage.get(entry.usage_id)

    def test_bad_time_rejected(self):
        entry = self.usage.record("fantasy")
        self.catalog._db.execute("UPDATE reference_pattern_usage SET created_at='path/CANARY'")
        self.catalog._db.commit()
        with self.assertRaises(PatternUsageError):
            self.usage.get(entry.usage_id)

    def test_cli_record_show_list_delete(self):
        code, out, err = self.run_cli("usage-add", "fantasy")
        self.assertEqual((code, err), (0, ""))
        entry_id = self.usage.list()[0].usage_id
        self.assertIn(entry_id, out)
        code, out, err = self.run_cli("usage-show", entry_id)
        self.assertEqual(code, 0)
        self.assertIn("현재 선택과 일치", out)
        code, out, err = self.run_cli("usage-list", "--genre", "fantasy")
        self.assertEqual(code, 0)
        self.assertIn(entry_id, out)
        code, out, err = self.run_cli("usage-delete", entry_id)
        self.assertEqual(code, 0)
        self.assertEqual(self.usage.count(), 0)

    def test_cli_record_related_and_filter_stale(self):
        code, out, err = self.run_cli("usage-add", "fantasy", "--pattern-genre", "romance")
        self.assertEqual((code, err), (0, ""))
        self.selections.save("fantasy", ["lexical_diversity"])
        code, out, err = self.run_cli("usage-list", "--status", "stale")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("재검토 필요", out)

    def test_cli_rejects_unsafe_without_raw_value(self):
        code, out, err = self.run_cli("usage-add", "romance")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertNotIn(CANARY, err)

    def test_reference_package_and_cli_import(self):
        from ai_novel_factory.database.pattern_usage import PatternUsageStore as Imported
        self.assertIs(Imported, PatternUsageStore)

    @unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 optional GUI not installed")
    def test_ui_stage37_controls(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QObject
        from ai_novel_factory.desktop.reference_profile_browser import ReferenceProfileBrowser
        from ai_novel_factory.desktop.reference_selection import ReferenceFileSelection
        app = QApplication.instance() or QApplication([])
        view = ReferenceProfileBrowser(ReferenceFileSelection())
        for name in ("recordReferencePatternUsageButton", "listReferencePatternUsageButton",
                     "deleteReferencePatternUsageButton", "referencePatternUsageList"):
            self.assertIsNotNone(view.findChild(QObject, name))
        view.close()


if __name__ == "__main__":
    unittest.main()
