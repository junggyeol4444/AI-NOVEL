"""Stage 36: local pattern similarity, safety, staleness and CLI regression."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import importlib.util
import io
from pathlib import Path
import shutil
import socket
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory.database import ReferenceCatalog
from ai_novel_factory.database.genre_patterns import GenrePatternStore
from ai_novel_factory.database.element_selections import ElementSelectionStore
from ai_novel_factory.database.pattern_strengths import PatternStrengthStore
from ai_novel_factory.references.element_selection import FEATURE_KEYS
from ai_novel_factory.references.profile_pipeline import import_reference_profile
from ai_novel_factory.references.profile_cli import main as cli
from ai_novel_factory.references.related_pattern_search import (
    MAX_RESULTS, MetricDifference, RelatedPattern, RelatedPatternError,
    RelatedPatternResults, RelatedPatternSearch, _distance, render_related_patterns,
)

CANARY = "NO_COPY_SOURCE_CANARY_49051"
GENRES = ("fantasy", "romance", "mystery")


class RelatedPatternSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_dir = tempfile.TemporaryDirectory()
        cls.base_path = Path(cls.fixture_dir.name) / "base.sqlite3"
        with ReferenceCatalog(cls.base_path) as catalog:
            cls.reference_ids = {}
            genres = GenrePatternStore(catalog)
            for genre_index, genre in enumerate(GENRES):
                ids = []
                for episode in range(3):
                    source = Path(cls.fixture_dir.name) / f"{CANARY}_{genre_index}_{episode}.txt"
                    # Equal-size synthetic works keep 3-way characters weighting below 60%.
                    text = ("제1화\n\n" + ("그는 위험했다. " if genre_index == 0 else
                            "그녀는 기뻤다. " if genre_index == 1 else "그런데 사실은. ") * 10
                            + "\n\n제2화\n\n" + ("갑자기 공격했다. " if genre_index == 0 else
                            '"성공했어!" ' if genre_index == 1 else "비밀을 밝혔다. ") * 10 + f"\n\n{chr(44032 + episode)}.")
                    source.write_text(text, encoding="utf-8")
                    record = import_reference_profile(source, catalog=catalog)
                    ids.append(record.reference.reference_id)
                    genres.assign(ids[-1], genre)
                cls.reference_ids[genre] = ids
                genres.build(genre, weighting="equal")
                genres.build(genre, weighting="characters")
            ElementSelectionStore(catalog).save("fantasy", ["dialogue_ratio", "emotion_balance"])
            ElementSelectionStore(catalog).save("fantasy", ["dialogue_ratio"], weighting="characters")

    @classmethod
    def tearDownClass(cls):
        cls.fixture_dir.cleanup()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dbpath = Path(tmp.name) / "refs.sqlite3"
        shutil.copyfile(self.base_path, self.dbpath)
        self.catalog = ReferenceCatalog(self.dbpath)
        self.addCleanup(self.catalog.close)
        self.genres = GenrePatternStore(self.catalog)
        self.strengths = PatternStrengthStore(self.catalog)
        self.selections = ElementSelectionStore(self.catalog)
        self.searcher = RelatedPatternSearch(self.catalog)

    def test_search_uses_saved_feature_keys(self):
        result = self.searcher.search("fantasy")
        self.assertEqual(result.selected_keys, ("dialogue_ratio", "emotion_balance"))
        self.assertEqual(result.source_genre, "fantasy")
        self.assertEqual(result.weighting, "equal")

    def test_excludes_source_genre(self):
        result = self.searcher.search("fantasy")
        self.assertEqual({m.genre for m in result.matches}, {"romance", "mystery"})
        self.assertNotIn("fantasy", [m.genre for m in result.matches])

    def test_two_candidates_considered(self):
        result = self.searcher.search("fantasy")
        self.assertEqual(result.inspected_count, 2)
        self.assertEqual(result.excluded_stale, 0)
        self.assertEqual(result.excluded_unsafe, 0)
        self.assertEqual(result.filtered_by_threshold, 0)

    def test_rank_descending_then_slug(self):
        matches = self.searcher.search("fantasy").matches
        self.assertEqual(list(matches), sorted(matches, key=lambda m: (-m.similarity_percent, m.genre)))

    def test_scores_are_bounded(self):
        for m in self.searcher.search("fantasy").matches:
            self.assertGreaterEqual(m.similarity_percent, 0)
            self.assertLessEqual(m.similarity_percent, 100)
            self.assertEqual(tuple(x.key for x in m.differences),
                             ("dialogue_ratio", "emotion_balance"))
            self.assertTrue(all(0 <= d.distance <= 1 for d in m.differences))

    def test_limit(self):
        self.assertEqual(len(self.searcher.search("fantasy", limit=1).matches), 1)
        self.assertEqual(self.searcher.search("fantasy", limit=1).inspected_count, 2)

    def test_similarity_threshold(self):
        full = self.searcher.search("fantasy").matches
        cutoff = max(m.similarity_percent for m in full)
        limited = self.searcher.search("fantasy", min_similarity=cutoff)
        self.assertTrue(all(m.similarity_percent >= cutoff for m in limited.matches))
        self.assertEqual(len(limited.matches) + limited.filtered_by_threshold, 2)

    def test_min_similarity_100(self):
        results = self.searcher.search("fantasy", min_similarity=100)
        self.assertTrue(all(m.similarity_percent == 100 for m in results.matches))

    def test_characters_weighting_uses_saved_recipe(self):
        result = self.searcher.search("fantasy", weighting="characters")
        self.assertEqual(result.selected_keys, ("dialogue_ratio",))
        self.assertEqual(result.weighting, "characters")
        self.assertEqual(len(result.matches), 2)

    def test_requires_saved_recipe(self):
        with self.assertRaises(RelatedPatternError):
            self.searcher.search("romance")

    def test_rejects_stale_source(self):
        self.genres.unassign(self.reference_ids["fantasy"][0])
        with self.assertRaises(RelatedPatternError):
            self.searcher.search("fantasy")

    def test_skip_stale_candidate(self):
        self.genres.unassign(self.reference_ids["romance"][0])
        result = self.searcher.search("fantasy")
        self.assertEqual(result.excluded_stale, 1)
        self.assertEqual([m.genre for m in result.matches], ["mystery"])

    def test_skip_unsafe_candidate(self):
        ids = self.reference_ids["romance"]
        self.strengths.set(ids[0], 100)
        self.strengths.set(ids[1], 0)
        self.strengths.set(ids[2], 0)
        result = self.searcher.search("fantasy")
        self.assertEqual(result.excluded_unsafe, 1)
        self.assertEqual(tuple(m.genre for m in result.matches), ("mystery",))

    def test_source_unsafe_rejected(self):
        for rid in self.reference_ids["fantasy"][:2]:
            self.strengths.set(rid, 0)
        with self.assertRaises(RelatedPatternError):
            self.searcher.search("fantasy")

    def test_weight_changes_search_result(self):
        before = self.searcher.search("fantasy")
        self.strengths.set(self.reference_ids["romance"][0], 100)
        self.strengths.set(self.reference_ids["romance"][1], 100)
        self.assertEqual(len(before.matches), len(self.searcher.search("fantasy").matches))

    def test_changed_selected_features(self):
        self.selections.save("fantasy", ["event_cue_density_per_1000"])
        result = self.searcher.search("fantasy")
        self.assertEqual(result.selected_keys, ("event_cue_density_per_1000",))
        self.assertEqual(len(result.matches[0].differences), 1)

    def test_deleted_selected_features(self):
        self.selections.delete("fantasy")
        with self.assertRaises(RelatedPatternError):
            self.searcher.search("fantasy")

    def test_does_not_rewrite_db_content(self):
        before = self.dbpath.read_bytes()
        self.searcher.search("fantasy")
        self.assertEqual(before, self.dbpath.read_bytes())

    def test_all_outputs_are_text_free(self):
        result = self.searcher.search("fantasy")
        report = render_related_patterns(result)
        for marker in (CANARY, ".txt", "제1화", "위험했다", "성공했어"):
            self.assertNotIn(marker, repr(result) + report)

    def test_no_network_even_when_sockets_disabled(self):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network access")):
            self.assertEqual(self.searcher.search("fantasy").inspected_count, 2)

    def test_reopen_database_and_search(self):
        self.catalog.close()
        with ReferenceCatalog(self.dbpath) as reopened:
            self.assertEqual(RelatedPatternSearch(reopened).search("fantasy").inspected_count, 2)

    def test_just_one_candidate_available(self):
        self.genres.delete("mystery")
        result = self.searcher.search("fantasy")
        self.assertEqual([m.genre for m in result.matches], ["romance"])

    def test_no_candidate_exists(self):
        self.genres.delete("mystery")
        self.genres.delete("romance")
        result = self.searcher.search("fantasy")
        self.assertEqual(result.inspected_count, 0)
        self.assertIn("조건에 맞는 패턴이 없습니다", render_related_patterns(result))

    def test_bad_genre(self):
        for genre in ("", None, True, CANARY, "fantasy'; DROP TABLE refs;--"):
            with self.subTest(genre=genre), self.assertRaises(RelatedPatternError):
                self.searcher.search(genre)

    def test_bad_weighting(self):
        for value in (None, True, "other", CANARY, 1):
            with self.subTest(mode=value), self.assertRaises(RelatedPatternError):
                self.searcher.search("fantasy", weighting=value)

    def test_bad_limits(self):
        for value in (-1, 0, MAX_RESULTS+1, True, 1.2, "1", None):
            with self.subTest(limit=value), self.assertRaises(RelatedPatternError):
                self.searcher.search("fantasy", limit=value)

    def test_bad_threshold(self):
        for value in (-1, 101, float("nan"), float("inf"), True, None, "0"):
            with self.subTest(value=value), self.assertRaises(RelatedPatternError):
                self.searcher.search("fantasy", min_similarity=value)

    def test_difference_zero(self):
        self.assertEqual(_distance("dialogue_ratio", .5, .5), 0)

    def test_difference_range(self):
        self.assertEqual(_distance("dialogue_ratio", 0, 1), 1)
        self.assertEqual(_distance("emotion_balance", -1, 1), 1)

    def test_sentence_distance_has_sensible_scale(self):
        self.assertEqual(_distance("sentence_characters", 10, 20), .5)

    def test_event_distance_has_floor(self):
        self.assertEqual(_distance("event_cue_density_per_1000", 0, 5), .5)

    def test_distance_rejects_bad_values(self):
        for key, value in (("bad", 1), ("dialogue_ratio", float('nan')),
                           ("dialogue_ratio", True), ("dialogue_ratio", None)):
            with self.subTest(key=key, value=value), self.assertRaises(RelatedPatternError):
                _distance(key, 0, value)

    def test_render_rejects_unspecified_genre(self):
        result = self.searcher.search("fantasy")
        fake = replace(result, source_genre="secret" + CANARY)
        with self.assertRaises(RelatedPatternError):
            render_related_patterns(fake)

    def test_render_rejects_corrupt_candidate(self):
        result = self.searcher.search("fantasy")
        tampered = replace(result.matches[0], similarity_percent=float("nan"))
        with self.assertRaises(RelatedPatternError):
            render_related_patterns(replace(result, matches=(tampered,)))

    def test_render_rejects_corrupt_distance(self):
        result = self.searcher.search("fantasy")
        match = result.matches[0]
        corrupted = replace(match, differences=(MetricDifference("wrong", .8),))
        with self.assertRaises(RelatedPatternError):
            render_related_patterns(replace(result, matches=(corrupted,)))

    def test_wrong_catalog(self):
        with self.assertRaises(RelatedPatternError):
            RelatedPatternSearch(None)

    def test_cli_search(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli(["--database", str(self.dbpath), "pattern-related", "fantasy"]), 0)
        self.assertIn("관련 패턴 검색", output.getvalue())
        self.assertNotIn(CANARY, output.getvalue())

    def test_cli_filter_and_limit(self):
        output = io.StringIO()
        with redirect_stdout(output):
            status = cli(["--database", str(self.dbpath), "pattern-related", "fantasy",
                          "--limit", "1", "--min-similarity", "0"])
        self.assertEqual(status, 0)
        self.assertEqual(output.getvalue().count(" · 통계 근접도 "), 1)

    def test_cli_missing_recipe(self):
        error = io.StringIO()
        with redirect_stderr(error):
            self.assertEqual(cli(["--database", str(self.dbpath), "pattern-related", "romance"]), 1)
        self.assertNotIn(CANARY, error.getvalue())

    def test_different_selected_metrics_change_ranking_input(self):
        two = self.searcher.search("fantasy")
        self.selections.save("fantasy", ["dialogue_ratio"])
        one = self.searcher.search("fantasy")
        self.assertNotEqual(tuple((m.genre, tuple(x.key for x in m.differences)) for m in two.matches),
                            tuple((m.genre, tuple(x.key for x in m.differences)) for m in one.matches))

    def test_uses_only_fixed_taxonomy(self):
        results = self.searcher.search("fantasy")
        self.assertTrue(all(match.genre in GENRES for match in results.matches))

    @unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 not installed")
    def test_gui_exposes_button(self):
        from PySide6.QtWidgets import QApplication
        from ai_novel_factory.desktop.reference_profile_browser import ReferenceProfileBrowser
        from ai_novel_factory.desktop.reference_selection import ReferenceFileSelection
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication.instance() or QApplication([])
        browser = ReferenceProfileBrowser(ReferenceFileSelection())
        self.assertIsNotNone(browser.findChild(type(browser.related_search_button),
                                               "searchRelatedReferencePatternsButton"))
        browser.close()


if __name__ == "__main__":
    unittest.main()
