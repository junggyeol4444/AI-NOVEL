"""Stage 32: local human-assigned genre patterns, provenance and privacy tests."""
from __future__ import annotations

from dataclasses import replace
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory.database import ReferenceCatalog
from ai_novel_factory.database.genre_patterns import GenrePatternStore, GenreStorageError
from ai_novel_factory.database.reference_profiles import ReferenceProfileStore
from ai_novel_factory.references.genre_patterns import (
    GENRE_NAMES, GenrePattern, build_genre_pattern, render_genre_pattern, validate_genre,
)
from ai_novel_factory.references.plaintext_parser import ReferenceParseError, parse_text
from ai_novel_factory.references.profile_cli import main as cli
from ai_novel_factory.references.profile_pipeline import import_reference_profile
from ai_novel_factory.references.reference_profile import build_reference_profile

ORIGINAL_SECRET = "COPYRIGHT_ORIGINAL_NEVER_STORE_99019101"
A = '제1화\n\n"가자!" 그러나 위험했다.\n\n제2화\n\n마침내 성공했다!'
B = '제1화\n\n행복했다. 사랑과 기쁨.\n\n제2화\n\n뜻밖에 비밀이 밝혀졌다?'
C = '제1화\n\n갑자기 싸움이 일어났다. 그러나 해결했다.'


class GenrePureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.first = build_reference_profile(parse_text(A))
        cls.second = build_reference_profile(parse_text(B))
        cls.blank = build_reference_profile(parse_text('# 빈 본문 제목', format='markdown'))

    def test_taxonomy_fixed_codes(self):
        self.assertIn('fantasy', GENRE_NAMES)
        self.assertIn('martial_arts', GENRE_NAMES)
        self.assertIn('science_fiction', GENRE_NAMES)
        self.assertIn('other', GENRE_NAMES)

    def test_valid_genres(self):
        for code in GENRE_NAMES:
            with self.subTest(code=code):
                self.assertEqual(validate_genre(code), code)

    def test_bad_genres_rejected(self):
        for code in (ORIGINAL_SECRET, 'fantasy;DROP TABLE x', 'Fantasy', '', None, True, 4):
            with self.subTest(code=code), self.assertRaises(ReferenceParseError):
                validate_genre(code)

    def test_two_profiles(self):
        result = build_genre_pattern('fantasy', [self.first, self.second])
        self.assertEqual(result.reference_count, 2)
        self.assertEqual(result.schema_version, 1)
        self.assertEqual(result.collection.episode_count, 4)
        self.assertEqual(len(result.features), 6)

    def test_genre_never_inferred_from_body(self):
        for genre in ('fantasy', 'romance', 'horror'):
            self.assertEqual(build_genre_pattern(genre, (self.first, self.second)).genre, genre)

    def test_no_one_work_generalization(self):
        with self.assertRaises(ReferenceParseError):
            build_genre_pattern('fantasy', [self.first])

    def test_too_many_works(self):
        with self.assertRaises(ReferenceParseError):
            build_genre_pattern('fantasy', [self.first] * 51)

    def test_wrong_input_container(self):
        for value in ('data', {'a': self.first}, None, (x for x in [self.first, self.second])):
            with self.subTest(type=type(value)), self.assertRaises(ReferenceParseError):
                build_genre_pattern('fantasy', value)

    def test_wrong_weighting(self):
        for value in ('random', '', None, True, 12):
            with self.subTest(value=value), self.assertRaises(ReferenceParseError):
                build_genre_pattern('fantasy', [self.first, self.second], weighting=value)

    def test_character_weights(self):
        eq = build_genre_pattern('fantasy', [self.first, self.second])
        weighted = build_genre_pattern('fantasy', [self.first, self.second], weighting='characters')
        self.assertEqual(eq.weighting, 'equal')
        self.assertEqual(weighted.weighting, 'characters')
        self.assertEqual(weighted.collection.weighting, 'characters')

    def test_feature_keys_fixed(self):
        keys = [f.key for f in build_genre_pattern('fantasy', [self.first, self.second]).features]
        self.assertEqual(keys, ['dialogue_ratio', 'sentence_characters', 'lexical_diversity',
                                'emotion_balance', 'cliffhanger_episode_rate',
                                'event_cue_density_per_1000'])

    def test_feature_ranges_respect_domain(self):
        p = build_genre_pattern('fantasy', [self.first, self.second])
        for entry in p.features:
            self.assertLessEqual(entry.observed_min, entry.observed_max)
            self.assertLessEqual(entry.typical_low, entry.typical_high)
            self.assertGreaterEqual(entry.standard_deviation, 0)
        for entry in p.features:
            if entry.key in ('dialogue_ratio', 'lexical_diversity', 'cliffhanger_episode_rate'):
                self.assertTrue(0 <= entry.typical_low <= entry.typical_high <= 1)
            if entry.key == 'emotion_balance':
                self.assertTrue(-1 <= entry.typical_low <= entry.typical_high <= 1)

    def test_equal_identical_profiles_zero_spread(self):
        p = build_genre_pattern('fantasy', [self.first, self.first])
        self.assertTrue(all(x.standard_deviation == 0 for x in p.features))

    def test_event_density_formula(self):
        result = build_genre_pattern('fantasy', [self.first, self.second])
        feature = next(x for x in result.features if x.key == 'event_cue_density_per_1000')
        densities = [1000 * p.event_cue_candidates / p.total_characters for p in (self.first, self.second)]
        self.assertAlmostEqual(feature.weighted_mean, sum(densities) / 2, places=4)
        # Corpus-wide density is separate and not incorrectly called mean density.
        pooled = (1000 * (self.first.event_cue_candidates + self.second.event_cue_candidates) /
                  (self.first.total_characters + self.second.total_characters))
        self.assertAlmostEqual(result.collection.event_cue_density_per_1000, pooled, places=4)

    def test_zero_character_works(self):
        p = build_genre_pattern('other', [self.blank, self.blank], weighting='characters')
        self.assertTrue(p.collection.empty_character_fallback)
        self.assertTrue(all(x.weighted_mean == 0 for x in p.features))

    def test_invalid_profiles_rejected(self):
        for invalid in (None, {}, replace(self.first, total_characters=-1)):
            with self.assertRaises(ReferenceParseError):
                build_genre_pattern('fantasy', [self.first, invalid])

    def test_input_order_invariant(self):
        for weight in ('equal', 'characters'):
            self.assertEqual(build_genre_pattern('fantasy', [self.first, self.second], weighting=weight),
                             build_genre_pattern('fantasy', [self.second, self.first], weighting=weight))

    def test_render_safe(self):
        p = build_genre_pattern('fantasy', [self.first, self.second])
        report = render_genre_pattern(p)
        self.assertIn('판타지', report)
        self.assertIn('5구간', report)
        self.assertIn('사용자 직접 지정', report)
        for original in (ORIGINAL_SECRET, '그러나 위험했다', '비밀이 밝혀졌다'):
            self.assertNotIn(original, report)
            self.assertNotIn(original, repr(p))

    def test_render_invalid_type(self):
        for wrong in ({}, None, self.first, replace(build_genre_pattern('fantasy', [self.first, self.second]), genre=ORIGINAL_SECRET)):
            with self.assertRaises(ReferenceParseError):
                render_genre_pattern(wrong)

    def test_no_network_used(self):
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
            p = build_genre_pattern('romance', [self.first, self.second])
            self.assertIn('로맨스', render_genre_pattern(p))


class GenreStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.db = self.folder / 'local.sqlite3'
        self.catalog = ReferenceCatalog(self.db)
        self.addCleanup(self.catalog.close)
        self.store = GenrePatternStore(self.catalog)
        self.paths = []
        self.ids = []
        for idx, content in enumerate((A, B, C)):
            path = self.folder / f'work_{idx}.txt'
            path.write_text(content, encoding='utf-8')
            self.paths.append(path)
            self.ids.append(import_reference_profile(path, catalog=self.catalog).reference.reference_id)

    def assign_two(self, genre='fantasy'):
        for reference_id in self.ids[:2]:
            self.store.assign(reference_id, genre)

    def test_assign_requires_existing_profile(self):
        with self.assertRaises(GenreStorageError):
            self.store.assign('0'*32, 'fantasy')

    def test_assign_and_read(self):
        self.assign_two()
        rows = self.store.list_assignments('fantasy')
        self.assertEqual([row[0] for row in rows], sorted(self.ids[:2]))
        self.assertTrue(all(row[1] == 'fantasy' for row in rows))

    def test_upsert_only_one_primary_genre(self):
        self.store.assign(self.ids[0], 'fantasy')
        self.store.assign(self.ids[0], 'romance')
        self.assertEqual(self.store.list_assignments('fantasy'), ())
        self.assertEqual(self.store.list_assignments('romance'), ((self.ids[0], 'romance'),))

    def test_invalid_reference_id(self):
        for reference_id in ('abc', '../../x', "' OR 1=1 --", True, None, '0'*33):
            with self.subTest(value=reference_id), self.assertRaises(GenreStorageError):
                self.store.assign(reference_id, 'fantasy')

    def test_invalid_genre_and_sql_injection(self):
        for genre in ("fantasy' OR 1=1 --", '아무 문구 ' + ORIGINAL_SECRET, '', True, None):
            with self.subTest(value=genre), self.assertRaises(GenreStorageError):
                self.store.assign(self.ids[0], genre)
        self.assertEqual(self.store.list_assignments(), ())

    def test_unassign_idempotent(self):
        self.store.assign(self.ids[0], 'fantasy')
        self.assertTrue(self.store.unassign(self.ids[0]))
        self.assertFalse(self.store.unassign(self.ids[0]))

    def test_unknown_unassign_false(self):
        self.assertFalse(self.store.unassign('0'*32))

    def test_not_enough_assignments_no_save(self):
        self.store.assign(self.ids[0], 'fantasy')
        with self.assertRaises(GenreStorageError):
            self.store.build('fantasy')
        self.assertEqual(self.store.list_patterns(), ())

    def test_build_save_get_same(self):
        self.assign_two()
        created = self.store.build('fantasy')
        loaded = self.store.get('fantasy')
        self.assertEqual(created, loaded)
        self.assertEqual(len(self.store.list_patterns()), 1)
        self.assertTrue(self.store.list_patterns()[0].current)

    def test_no_save_computes_without_db_insert(self):
        self.assign_two()
        result = self.store.build('fantasy', save=False)
        self.assertEqual(result.reference_count, 2)
        self.assertEqual(self.store.list_patterns(), ())

    def test_reopen_database(self):
        self.assign_two()
        self.store.build('fantasy')
        with ReferenceCatalog(self.db) as reopened:
            self.assertEqual(GenrePatternStore(reopened).get('fantasy').reference_count, 2)

    def test_two_weighting_modes(self):
        self.assign_two()
        for weighting in ('equal', 'characters'):
            self.store.build('fantasy', weighting=weighting)
        self.assertEqual({row.weighting for row in self.store.list_patterns()}, {'equal', 'characters'})

    def test_reassignment_detects_stale_cohort(self):
        self.assign_two()
        self.store.build('fantasy')
        self.store.assign(self.ids[1], 'romance')
        self.assertFalse(self.store.list_patterns()[0].current)
        with self.assertRaises(GenreStorageError):
            self.store.get('fantasy')

    def test_new_member_requires_rebuild(self):
        self.assign_two()
        self.store.build('fantasy')
        self.store.assign(self.ids[2], 'fantasy')
        with self.assertRaises(GenreStorageError):
            self.store.get('fantasy')
        self.assertEqual(self.store.build('fantasy').reference_count, 3)
        self.assertTrue(self.store.list_patterns()[0].current)

    def test_changing_profile_recomputes_stats(self):
        self.assign_two()
        old = self.store.build('fantasy')
        from dataclasses import replace as update
        profiles = ReferenceProfileStore(self.catalog)
        src = profiles.get(self.ids[0])
        # Can modify numeric metric that does not affect sums to simulate a
        # legitimate profile re-analysis, then reload pattern in same cohort.
        profiles.save(self.ids[0], update(src, average_sentence_characters=src.average_sentence_characters + 20))
        new = self.store.get('fantasy')
        self.assertNotEqual(old.collection.sentence_characters.weighted_mean,
                            new.collection.sentence_characters.weighted_mean)

    def test_missing_profile_rejected_on_read(self):
        self.assign_two()
        self.store.build('fantasy')
        ReferenceProfileStore(self.catalog).delete(self.ids[0])
        with self.assertRaises(GenreStorageError):
            self.store.get('fantasy')

    def test_corrupt_saved_ids_rejected(self):
        self.assign_two()
        self.store.build('fantasy')
        with self.catalog._db:
            self.catalog._db.execute("UPDATE genre_pattern_selections SET reference_ids_json=?",
                                     (json.dumps([ORIGINAL_SECRET]),))
        with self.assertRaises(GenreStorageError):
            self.store.get('fantasy')
        with self.assertRaises(GenreStorageError):
            self.store.list_patterns()

    def test_corrupt_json_rejected(self):
        self.assign_two()
        self.store.build('fantasy')
        with self.catalog._db:
            self.catalog._db.execute("UPDATE genre_pattern_selections SET reference_ids_json='not-json'")
        with self.assertRaises(GenreStorageError):
            self.store.get('fantasy')

    def test_no_full_path_or_original_in_new_tables(self):
        self.assign_two()
        self.store.build('fantasy')
        for table in ('reference_genres', 'genre_pattern_selections'):
            result = self.catalog._db.execute(f'SELECT * FROM {table}').fetchall()
            serialized = repr([tuple(row) for row in result])
            for banned in (str(self.folder), self.paths[0].name, '그러나 위험했다', ORIGINAL_SECRET):
                self.assertNotIn(banned, serialized)

    def test_no_external_network(self):
        self.assign_two()
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
            self.assertEqual(self.store.build('fantasy').reference_count, 2)
            self.assertIn('판타지', render_genre_pattern(self.store.get('fantasy')))

    def test_delete_recipe_does_not_remove_profiles_or_tags(self):
        self.assign_two()
        self.store.build('fantasy')
        self.assertTrue(self.store.delete('fantasy'))
        self.assertFalse(self.store.delete('fantasy'))
        self.assertEqual(len(self.store.list_assignments('fantasy')), 2)
        self.assertEqual(ReferenceProfileStore(self.catalog).count(), 3)

    def test_invalid_weighting(self):
        self.assign_two()
        for value in ('nope', True, 12, None):
            with self.assertRaises(GenreStorageError):
                self.store.build('fantasy', weighting=value)
        self.assertEqual(self.store.list_patterns(), ())

    def test_bad_save_flag_no_db_insert(self):
        self.assign_two()
        with self.assertRaises(GenreStorageError):
            self.store.build('fantasy', save='true')
        self.assertEqual(self.store.list_patterns(), ())

    def test_invalid_catalog_constructor(self):
        with self.assertRaises(GenreStorageError):
            GenrePatternStore(None)

    def test_database_genre_whitelist(self):
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            with self.catalog._db:
                self.catalog._db.execute(
                    "INSERT INTO reference_genres(reference_id, genre) VALUES (?, ?)",
                    (self.ids[0], ORIGINAL_SECRET))
        self.assertEqual(self.store.list_assignments(), ())

    def test_fifty_profiles_allowed_fifty_one_rejected(self):
        self.assign_two()
        for idx in range(2, 50):
            if idx < len(self.ids):
                ref = self.ids[idx]
            else:
                path = self.folder / f"extra_{idx}.txt"
                path.write_text(f"제1화\n\n새로운 장르의 이야기 {idx}", encoding="utf-8")
                ref = import_reference_profile(path, catalog=self.catalog).reference.reference_id
            self.store.assign(ref, "fantasy")
        self.assertEqual(self.store.build("fantasy").reference_count, 50)
        extra = self.folder / "too_many.txt"
        extra.write_text("제1화\n\n정말 마지막 추가 참고작", encoding="utf-8")
        ref = import_reference_profile(extra, catalog=self.catalog).reference.reference_id
        self.store.assign(ref, "fantasy")
        with self.assertRaises(GenreStorageError):
            self.store.build("fantasy")
        self.assertFalse(self.store.list_patterns()[0].current)

    def test_deleted_reference_cascades_tag_and_invalidates_saved_cohort(self):
        self.assign_two()
        self.store.build("fantasy")
        with self.catalog._db:
            self.catalog._db.execute("DELETE FROM reference_files WHERE reference_id=?",
                                     (self.ids[0],))
        self.assertEqual(len(self.store.list_assignments("fantasy")), 1)
        with self.assertRaises(GenreStorageError):
            self.store.get("fantasy")

    def test_show_missing_selection_rejected(self):
        self.assign_two()
        with self.assertRaises(GenreStorageError):
            self.store.get("fantasy")

    def test_cli_end_to_end(self):
        output = io.StringIO()
        for ref in self.ids[:2]:
            with redirect_stdout(output), redirect_stderr(output):
                self.assertEqual(cli(['--database', str(self.db), 'genre-assign', ref, 'fantasy']), 0)
        with redirect_stdout(output), redirect_stderr(output):
            self.assertEqual(cli(['--database', str(self.db), 'genre-build', 'fantasy']), 0)
            self.assertEqual(cli(['--database', str(self.db), 'genre-show', 'fantasy']), 0)
            self.assertEqual(cli(['--database', str(self.db), 'genre-list']), 0)
        content = output.getvalue()
        self.assertIn('판타지', content)
        self.assertIn('최신 구성', content)
        self.assertNotIn('그러나 위험했다', content)

    def test_cli_errors_safe(self):
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(cli(['--database', str(self.db), 'genre-show', 'fantasy']), 1)
        self.assertIn('오류', err.getvalue())
        self.assertNotIn(str(self.folder), err.getvalue())

    def test_tag_membership_without_source_read(self):
        self.assign_two()
        self.store.build('fantasy')
        for f in self.paths:
            f.unlink()
        self.assertEqual(self.store.get('fantasy').reference_count, 2)


class GenreGuiOptionalTests(unittest.TestCase):
    def test_manual_gui_controls_if_pyside6_installed(self):
        try:
            from PySide6.QtWidgets import QApplication
            from ai_novel_factory.desktop.reference_profile_browser import ReferenceProfileBrowser
            from ai_novel_factory.desktop.reference_selection import ReferenceFileSelection
        except ImportError:
            self.skipTest('PySide6 not installed in this runtime')
        from unittest.mock import patch as patched
        with patched('ai_novel_factory.desktop.reference_profile_browser.default_local_catalog_path',
                     return_value=Path(':memory:')):
            app = QApplication.instance() or QApplication([])
            window = ReferenceProfileBrowser(ReferenceFileSelection())
            self.assertEqual(window.genre_selector.count(), len(GENRE_NAMES))
            self.assertEqual(window.genre_build_button.objectName(), 'buildGenrePatternButton')
            self.assertEqual(window.genre_show_button.objectName(), 'showGenrePatternButton')
            window.deleteLater()
