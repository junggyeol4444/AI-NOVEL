"""Stage 31 tests: truthful work-level aggregation and fully offline DB/CLI integration."""
from __future__ import annotations

from dataclasses import replace
from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory.database import ReferenceCatalog
from ai_novel_factory.database.reference_profiles import ProfileStorageError, ReferenceProfileStore
from ai_novel_factory.references import (
    ReferenceParseError, build_reference_profile, parse_text,
)
from ai_novel_factory.references.profile_cli import main as profile_cli_main
from ai_novel_factory.references.profile_collection import (
    CURVE_BINS, MAX_COLLECTION_REFERENCES, combine_reference_profiles,
    combine_saved_profiles, render_profile_collection,
)
from ai_novel_factory.references.profile_pipeline import import_reference_profile

FIRST = (
    "제1화\n\n\"정말 괜찮아?\" 그러나 위험했다.\n\n"
    "꿈과 희망이 있었다.\n\n"
    "제2화\n\n마침내 해결했다! 위험한 싸움은 끝났다."
)
SECOND = (
    "제1화\n\n두 사람은 싸웠다. 그러나 비밀이 있었다.\n\n"
    "제2화\n\n갑자기 위기가 닥쳤다?\n\n"
    "제3화\n\n드디어 성공했다. 사랑과 기쁨이었다."
)
SECRET = "THIS_REFERENCE_ORIGINAL_MUST_NOT_LEAK_8031241"


class PureCollectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = build_reference_profile(parse_text(FIRST))
        cls.b = build_reference_profile(parse_text(SECOND))
        cls.blank = build_reference_profile(parse_text("# 빈 문서 제목", format="markdown"))

    def test_two_references_counted(self):
        m = combine_reference_profiles([self.a, self.b])
        self.assertEqual(m.reference_count, 2)
        self.assertEqual(m.episode_count, 5)
        self.assertEqual(m.total_characters, self.a.total_characters + self.b.total_characters)
        self.assertEqual(m.total_words, self.a.total_words + self.b.total_words)
        self.assertEqual(m.total_event_cue_candidates,
                         self.a.event_cue_candidates + self.b.event_cue_candidates)

    def test_default_equal_weights(self):
        m = combine_reference_profiles([self.a, self.b])
        self.assertEqual(m.weighting, "equal")
        self.assertAlmostEqual(m.dialogue_ratio.weighted_mean,
                               (self.a.dialogue_ratio + self.b.dialogue_ratio) / 2, places=5)

    def test_work_length_weighted(self):
        m = combine_reference_profiles([self.a, self.b], weighting="characters")
        expected = ((self.a.total_characters * self.a.dialogue_ratio +
                     self.b.total_characters * self.b.dialogue_ratio) /
                    (self.a.total_characters + self.b.total_characters))
        self.assertAlmostEqual(m.dialogue_ratio.weighted_mean, expected, places=5)

    def test_weighting_modes_differ_when_metrics_and_sizes_differ(self):
        different = replace(self.b, total_characters=self.b.total_characters + 1000)
        self.assertNotEqual(combine_reference_profiles([self.a, different]).dialogue_ratio,
                            combine_reference_profiles([self.a, different], weighting="characters").dialogue_ratio)

    def test_pooled_cue_density_both_modes(self):
        expected = 1000 * (self.a.event_cue_candidates + self.b.event_cue_candidates) / (
            self.a.total_characters + self.b.total_characters)
        for mode in ("equal", "characters"):
            with self.subTest(mode=mode):
                m = combine_reference_profiles((self.a, self.b), weighting=mode)
                self.assertAlmostEqual(m.event_cue_density_per_1000, expected, places=5)

    def test_spread_math(self):
        m = combine_reference_profiles((self.a, self.b))
        self.assertEqual(m.dialogue_ratio.minimum, round(min(self.a.dialogue_ratio, self.b.dialogue_ratio), 6))
        self.assertEqual(m.dialogue_ratio.maximum, round(max(self.a.dialogue_ratio, self.b.dialogue_ratio), 6))
        self.assertGreaterEqual(m.dialogue_ratio.standard_deviation, 0)

    def test_equal_input_zero_variance(self):
        m = combine_reference_profiles([self.a, self.a])
        self.assertEqual(m.dialogue_ratio.standard_deviation, 0.0)
        self.assertEqual(m.emotion_balance.standard_deviation, 0.0)

    def test_input_order_does_not_change_aggregate(self):
        for mode in ("equal", "characters"):
            with self.subTest(mode=mode):
                self.assertEqual(combine_reference_profiles((self.a, self.b), weighting=mode),
                                 combine_reference_profiles((self.b, self.a), weighting=mode))

    def test_hook_counts_sum_to_all_episodes(self):
        m = combine_reference_profiles([self.a, self.b])
        self.assertEqual(sum(n for _, n in m.hook_type_counts), m.episode_count)
        self.assertEqual(sum(n for name, n in m.hook_type_counts if name != "none"),
                         m.total_hook_candidate_episodes)

    def test_hooks_fixed_categories_sorted(self):
        m = combine_reference_profiles([self.a, self.b])
        self.assertEqual(tuple(name for name, _ in m.hook_type_counts),
                         tuple(sorted(name for name, _ in m.hook_type_counts)))

    def test_curve_five_bins(self):
        m = combine_reference_profiles([self.a, self.b])
        self.assertEqual(len(m.episode_curve), CURVE_BINS)
        self.assertEqual([entry.segment for entry in m.episode_curve], [1, 2, 3, 4, 5])
        self.assertEqual(sum(entry.contributing_episodes for entry in m.episode_curve), m.episode_count)
        self.assertTrue(all(0 <= entry.contributing_works <= 2 for entry in m.episode_curve))

    def test_curve_uses_relative_episode_position(self):
        # With 2 episodes, bin 2 and 4. With 3 episodes, bin 1,3,5.
        m = combine_reference_profiles([self.a, self.b])
        self.assertEqual([b.contributing_episodes for b in m.episode_curve], [1, 1, 1, 1, 1])

    def test_sparse_curve_empty_bins_zero(self):
        m = combine_reference_profiles([self.blank, self.blank])
        for item in m.episode_curve:
            if item.contributing_works == 0:
                self.assertEqual(item.dialogue_ratio, 0)
                self.assertEqual(item.emotion_balance, 0)

    def test_zero_character_all_uses_fallback(self):
        m = combine_reference_profiles((self.blank, self.blank), weighting="characters")
        self.assertTrue(m.empty_character_fallback)
        self.assertEqual(m.event_cue_density_per_1000, 0)
        self.assertEqual(m.total_characters, 0)
        self.assertIn("전체 본문 0자", render_profile_collection(m))

    def test_zero_character_one_work_ignored_in_length_weighted_mean(self):
        m = combine_reference_profiles([self.a, self.blank], weighting="characters")
        self.assertFalse(m.empty_character_fallback)
        self.assertAlmostEqual(m.dialogue_ratio.weighted_mean, self.a.dialogue_ratio, places=5)
        self.assertEqual(m.dialogue_ratio.minimum, 0.0)

    def test_min_and_max_reference_count(self):
        self.assertEqual(combine_reference_profiles([self.a] * MAX_COLLECTION_REFERENCES).reference_count, 50)
        for wrong in ([], [self.a], [self.a] * 51):
            with self.subTest(size=len(wrong)), self.assertRaises(ReferenceParseError):
                combine_reference_profiles(wrong)

    def test_invalid_container(self):
        for bad in ((p for p in (self.a, self.b)), 'abc', {"a": self.a}, None):
            with self.assertRaises(ReferenceParseError):
                combine_reference_profiles(bad)

    def test_invalid_weighting(self):
        for bad in ("invalid", "", "Characters", None, 2, True):
            with self.subTest(bad=bad), self.assertRaises(ReferenceParseError):
                combine_reference_profiles([self.a, self.b], weighting=bad)

    def test_invalid_profiles_rejected_before_aggregation(self):
        for bad in (None, "novel original", {}, replace(self.a, total_characters=-1)):
            with self.subTest(bad_type=type(bad)), self.assertRaises(ReferenceParseError):
                combine_reference_profiles([self.a, bad])

    def test_injected_label_rejected(self):
        e = replace(self.a.episodes[0], cliffhanger_type=SECRET)
        bad = replace(self.a, episodes=(e, *self.a.episodes[1:]))
        with self.assertRaises(ReferenceParseError):
            combine_reference_profiles((bad, self.b))

    def test_render_has_no_original_text(self):
        m = combine_reference_profiles([self.a, self.b])
        report = render_profile_collection(m)
        self.assertIn("여러 참고작 통합", report)
        self.assertIn("5구간", report)
        for phrase in ("정말 괜찮아?", "위기가 닥쳤다", "사랑과 기쁨", SECRET):
            self.assertNotIn(phrase, report)
            self.assertNotIn(phrase, repr(m))

    def test_render_only_valid_result(self):
        for invalid in (None, {}, self.a):
            with self.assertRaises(ReferenceParseError):
                render_profile_collection(invalid)

    def test_individual_lexical_diversity_not_pooled(self):
        m = combine_reference_profiles((self.a, self.b))
        self.assertAlmostEqual(m.lexical_diversity.weighted_mean,
                               (self.a.lexical_diversity + self.b.lexical_diversity) / 2,
                               places=5)
        self.assertIn("실제 어휘 다양도가 아닙니다", render_profile_collection(m))

    def test_single_episode_curve_midpoint(self):
        book = build_reference_profile(parse_text('다행히 사랑은 성공했다.'))
        m = combine_reference_profiles([book, book])
        self.assertEqual([x.contributing_episodes for x in m.episode_curve], [0, 0, 2, 0, 0])


class StoredCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.db_path = self.folder / "local.sqlite3"
        self.db = ReferenceCatalog(self.db_path)
        self.addCleanup(self.db.close)
        self.store = ReferenceProfileStore(self.db)
        self.a_path = self.folder / 'one.txt'
        self.b_path = self.folder / 'two.txt'
        self.a_path.write_text(FIRST, encoding='utf-8')
        self.b_path.write_text(SECOND, encoding='utf-8')
        self.a_id = import_reference_profile(self.a_path, catalog=self.db).reference.reference_id
        self.b_id = import_reference_profile(self.b_path, catalog=self.db).reference.reference_id

    def test_compare_saved_ids(self):
        summary = combine_saved_profiles(self.store, [self.a_id, self.b_id])
        self.assertEqual(summary.reference_count, 2)
        self.assertEqual(summary.episode_count, 5)

    def test_reopen_then_compare_with_novel_files_deleted(self):
        self.a_path.unlink()
        self.b_path.unlink()
        with ReferenceCatalog(self.db_path) as db:
            loaded = combine_saved_profiles(ReferenceProfileStore(db), [self.a_id, self.b_id])
        self.assertEqual(loaded.reference_count, 2)

    def test_no_extra_db_tables(self):
        before = set(self.db._db.execute('SELECT name FROM sqlite_master WHERE type="table"').fetchall())
        combine_saved_profiles(self.store, [self.a_id, self.b_id])
        after = set(self.db._db.execute('SELECT name FROM sqlite_master WHERE type="table"').fetchall())
        self.assertEqual(before, after)

    def test_comparison_does_not_write_results_to_db(self):
        before = '\n'.join(self.db._db.iterdump())
        combine_saved_profiles(self.store, [self.a_id, self.b_id])
        self.assertEqual(before, '\n'.join(self.db._db.iterdump()))

    def test_invalid_store_type(self):
        with self.assertRaises(ReferenceParseError):
            combine_saved_profiles(object(), [self.a_id, self.b_id])

    def test_duplicate_ids_denied(self):
        with self.assertRaises(ReferenceParseError):
            combine_saved_profiles(self.store, [self.a_id, self.a_id])

    def test_wrong_id_types_denied(self):
        for x in (None, "", "' OR 1=1 --", "G"*32, "0"*33, 12):
            with self.subTest(item=x), self.assertRaises(ReferenceParseError):
                combine_saved_profiles(self.store, [self.a_id, x])

    def test_missing_id_is_not_silently_skipped(self):
        with self.assertRaises(ProfileStorageError):
            combine_saved_profiles(self.store, [self.a_id, '0' * 32])

    def test_bad_id_collection(self):
        for value in ([], [self.a_id], [self.a_id, self.b_id] * 26,
                      (v for v in [self.a_id, self.b_id])):
            with self.assertRaises(ReferenceParseError):
                combine_saved_profiles(self.store, value)

    def test_corrupted_json_denied(self):
        self.db._db.execute('UPDATE reference_profiles SET profile_json=? WHERE reference_id=?',
                            ('{"novel":"' + SECRET + '"}', self.a_id))
        self.db._db.commit()
        with self.assertRaises(ProfileStorageError) as cm:
            combine_saved_profiles(self.store, [self.a_id, self.b_id])
        self.assertNotIn(SECRET, str(cm.exception))

    def test_delete_one_profile_denied(self):
        self.assertTrue(self.store.delete(self.a_id))
        with self.assertRaises(ProfileStorageError):
            combine_saved_profiles(self.store, [self.a_id, self.b_id])

    def test_socket_disabled_offline(self):
        with patch('socket.socket', side_effect=AssertionError('network called')):
            output = combine_saved_profiles(self.store, [self.a_id, self.b_id])
        self.assertEqual(output.reference_count, 2)

    def test_no_original_names_in_report_or_results(self):
        output = combine_saved_profiles(self.store, [self.a_id, self.b_id])
        report = render_profile_collection(output)
        for private in ('one.txt', 'two.txt', str(self.folder), self.a_id, self.b_id):
            self.assertNotIn(private, repr(output))
            self.assertNotIn(private, report)

    def test_cli_compare_equal(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rc = profile_cli_main(['--database', str(self.db_path), 'compare', self.a_id, self.b_id])
        self.assertEqual(rc, 0)
        self.assertIn('작품별 동일 가중치', buffer.getvalue())
        self.assertNotIn('one.txt', buffer.getvalue())

    def test_cli_characters(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rc = profile_cli_main(['--database', str(self.db_path), 'compare',
                                   self.a_id, self.b_id, '--weighting', 'characters'])
        self.assertEqual(rc, 0)
        self.assertIn('작품 글자 수 가중치', buffer.getvalue())

    def test_cli_requires_two_unique(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = profile_cli_main(['--database', str(self.db_path), 'compare', self.a_id])
        self.assertEqual(rc, 1)
        self.assertIn('오류:', stderr.getvalue())

    def test_cli_missing_id(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            rc = profile_cli_main(['--database', str(self.db_path), 'compare', self.a_id, '0'*32])
        self.assertEqual(rc, 1)
        self.assertNotIn(str(self.folder), stderr.getvalue())


class CollectionGuiOptionalTests(unittest.TestCase):
    def test_gui_widget_exists_and_compares_selected(self):
        try:
            from PySide6.QtWidgets import QApplication
            from ai_novel_factory.desktop.reference_profile_browser import ReferenceProfileBrowser
            from ai_novel_factory.desktop.reference_selection import ReferenceFileSelection
        except ImportError:
            self.skipTest('PySide6 미설치: Windows GUI 실기기 테스트 별도 필요')
        import os
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        app = QApplication.instance() or QApplication([])
        browser = ReferenceProfileBrowser(ReferenceFileSelection())
        self.assertIsNotNone(browser.findChild(type(browser.compare_button), 'compareReferenceProfilesButton'))
        browser._compare_selected()
        self.assertIn('2~50개', browser.report.toPlainText())
        browser.close()
        self.assertIsNotNone(app)


if __name__ == '__main__':
    unittest.main()
