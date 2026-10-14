"""Stage 33: offline, read-only reference pattern library integration tests."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import importlib.util
import io
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory.database import ReferenceCatalog
from ai_novel_factory.database.genre_patterns import GenrePatternStore
from ai_novel_factory.database.reference_profiles import ReferenceProfileStore
from ai_novel_factory.references.pattern_library import (
    LibraryEntry, LibraryPage, LibraryComparison, PatternLibraryError,
    ReferencePatternLibrary, render_library_page, render_library_comparison,
)
from ai_novel_factory.references.profile_cli import main
from ai_novel_factory.references.profile_pipeline import import_reference_profile

PRIVATE_TEXT = '원본_대사_절대로_라이브러리_저장금지_983'
BODIES = (
    '제1화\n\n그러나 위험했다. 행복했다!\n\n제2화\n\n결국 성공했다?',
    '제1화\n\n갑자기 싸움이 났다.\n\n제2화\n\n마침내 비밀을 알았다.',
    '제1화\n\n사랑과 기쁨. 행복했다.\n\n제2화\n\n하지만 슬펐다.',
    '제1화\n\n그런데 위험했다.\n\n제2화\n\n끝내 해결했다.',
)


class PatternLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.db = self.folder / 'local.sqlite3'
        self.catalog = ReferenceCatalog(self.db)
        self.addCleanup(self.catalog.close)
        self.store = GenrePatternStore(self.catalog)
        self.library = ReferencePatternLibrary(self.store)
        self.ids = []
        for idx, source in enumerate(BODIES):
            path = self.folder / f'private_{idx}.txt'
            path.write_text(source, encoding='utf-8')
            self.ids.append(import_reference_profile(path, catalog=self.catalog).reference.reference_id)
        for idx, ref in enumerate(self.ids):
            self.store.assign(ref, 'fantasy' if idx < 2 else 'romance')
        self.store.build('fantasy')
        self.store.build('romance')

    def test_constructor_rejects_wrong_store(self):
        for invalid in (None, self.catalog, {}, 4):
            with self.subTest(value=invalid), self.assertRaises(PatternLibraryError):
                ReferencePatternLibrary(invalid)

    def test_browse_two_saved_patterns(self):
        page = self.library.search()
        self.assertEqual(page.total, 2)
        self.assertEqual([x.genre for x in page.entries], ['fantasy', 'romance'])
        self.assertTrue(all(x.current for x in page.entries))

    def test_browse_is_deterministic(self):
        self.assertEqual(self.library.search(), self.library.search())

    def test_hangul_search(self):
        page = self.library.search(query='판타지')
        self.assertEqual(page.total, 1)
        self.assertEqual(page.entries[0].genre, 'fantasy')

    def test_code_search_casefold(self):
        self.assertEqual(self.library.search(query='FANTASY').total, 1)

    def test_weighting_keyword_search(self):
        self.assertEqual(self.library.search(query='equal').total, 2)

    def test_multi_term_search(self):
        self.assertEqual(self.library.search(query='판타지 equal').total, 1)
        self.assertEqual(self.library.search(query='판타지 characters').total, 0)

    def test_search_does_not_use_original_text(self):
        self.assertEqual(self.library.search(query='그러나 위험했다').total, 0)
        self.assertEqual(self.library.search(query='private_0').total, 0)

    def test_whitespace_query(self):
        self.assertEqual(self.library.search(query='   ').total, 2)

    def test_filter_genre(self):
        self.assertEqual(self.library.search(genre='romance').entries[0].genre, 'romance')

    def test_filter_weighting(self):
        self.store.build('fantasy', weighting='characters')
        page = self.library.search(weighting='characters')
        self.assertEqual(page.total, 1)
        self.assertEqual(page.entries[0].weighting, 'characters')

    def test_filter_current_true(self):
        self.assertEqual(self.library.search(current=True).total, 2)
        self.assertEqual(self.library.search(current=False).total, 0)

    def test_stale_result_stays_visible(self):
        self.store.unassign(self.ids[0])
        page = self.library.search(current=False)
        self.assertEqual(page.total, 1)
        self.assertFalse(page.entries[0].current)
        self.assertIn('재구축 필요', render_library_page(page))

    def test_stale_result_not_shown_in_current_filter(self):
        self.store.unassign(self.ids[0])
        self.assertEqual(self.library.search(current=True).total, 1)

    def test_stale_detail_refused(self):
        self.store.unassign(self.ids[0])
        with self.assertRaises(PatternLibraryError):
            self.library.get('fantasy')

    def test_stale_compare_refused(self):
        self.store.unassign(self.ids[0])
        with self.assertRaises(PatternLibraryError):
            self.library.compare(['fantasy', 'romance'])

    def test_rebuild_restores_current(self):
        self.store.assign(self.ids[0], 'fantasy')
        self.store.unassign(self.ids[0])
        self.store.assign(self.ids[0], 'fantasy')
        self.assertEqual(self.library.search(current=True).total, 2)

    def test_change_cohort_requires_rebuild(self):
        self.store.assign(self.ids[2], 'fantasy')
        self.assertEqual(self.library.search(current=False).total, 2)
        self.store.build('fantasy')
        self.assertEqual(self.library.search(current=True).total, 1)

    def test_pagination_total_and_offset(self):
        one = self.library.search(limit=1)
        second = self.library.search(limit=1, offset=1)
        self.assertEqual(one.total, second.total)
        self.assertEqual(len(one.entries), len(second.entries))
        self.assertNotEqual(one.entries[0], second.entries[0])

    def test_pagination_beyond_end(self):
        self.assertEqual(self.library.search(offset=500).entries, ())

    def test_exact_page_limit(self):
        self.assertEqual(len(self.library.search(limit=2).entries), 2)

    def test_invalid_pagination(self):
        for value in (-1, 101, True, '10', None):
            with self.subTest(value=value), self.assertRaises(PatternLibraryError):
                self.library.search(limit=value)
        for value in (-1, 10001, True, None, '1'):
            with self.subTest(value=value), self.assertRaises(PatternLibraryError):
                self.library.search(offset=value)

    def test_bad_query_type(self):
        for query in (None, True, 42, [], {}, 'a' * 81, 'abc\nfoo'):
            with self.subTest(query=query), self.assertRaises(PatternLibraryError):
                self.library.search(query=query)

    def test_bad_genre_filter(self):
        for code in (True, 'bad', "fantasy' OR 1=1 --", '', 9):
            with self.subTest(code=code), self.assertRaises(PatternLibraryError):
                self.library.search(genre=code)

    def test_bad_weighting_filter(self):
        for code in (True, 'bad', '', 0):
            with self.subTest(code=code), self.assertRaises(PatternLibraryError):
                self.library.search(weighting=code)

    def test_bad_current_filter(self):
        for value in (0, 1, 'false', '', [], {}):
            with self.subTest(value=value), self.assertRaises(PatternLibraryError):
                self.library.search(current=value)

    def test_get_matches_stage32_store(self):
        self.assertEqual(self.library.get('fantasy'), self.store.get('fantasy'))

    def test_compare_two_genres(self):
        result = self.library.compare(['fantasy', 'romance'])
        self.assertEqual(result.genres, ('fantasy', 'romance'))
        self.assertEqual(result.reference_counts, (2, 2))
        self.assertEqual(len(result.features), 6)

    def test_compare_feature_means_reproduced(self):
        result = self.library.compare(('fantasy', 'romance'))
        for idx, feature in enumerate(result.features):
            actual = (self.store.get('fantasy').features[idx].weighted_mean,
                      self.store.get('romance').features[idx].weighted_mean)
            self.assertEqual(feature.means, actual)
            self.assertAlmostEqual(feature.difference, max(actual) - min(actual), places=6)

    def test_compare_reverse_preserves_order(self):
        result = self.library.compare(['romance', 'fantasy'])
        self.assertEqual(result.genres, ('romance', 'fantasy'))
        self.assertEqual(result.features[0].means[0], self.store.get('romance').features[0].weighted_mean)

    def test_compare_characters_mode(self):
        self.store.build('fantasy', weighting='characters')
        self.store.build('romance', weighting='characters')
        result = self.library.compare(['fantasy', 'romance'], weighting='characters')
        self.assertEqual(result.weighting, 'characters')

    def test_compare_requires_matching_weighting_recipe(self):
        self.store.build('fantasy', weighting='characters')
        with self.assertRaises(PatternLibraryError):
            self.library.compare(['fantasy', 'romance'], weighting='characters')

    def test_compare_minimum_two(self):
        for items in ([], ['fantasy'], (), 'fantasy', None):
            with self.subTest(items=items), self.assertRaises(PatternLibraryError):
                self.library.compare(items)

    def test_compare_duplicate_refused(self):
        with self.assertRaises(PatternLibraryError):
            self.library.compare(['fantasy', 'fantasy'])

    def test_compare_bad_codes(self):
        for x in (True, None, 'invalid', 'romance;DELETE FROM x'):
            with self.subTest(value=x), self.assertRaises(PatternLibraryError):
                self.library.compare(['fantasy', x])

    def test_compare_too_many(self):
        with self.assertRaises(PatternLibraryError):
            self.library.compare(list(range(13)))

    def test_compare_invalid_weighting(self):
        for mode in ('unknown', '', True, 1):
            with self.subTest(mode=mode), self.assertRaises(PatternLibraryError):
                self.library.compare(['fantasy', 'romance'], weighting=mode)

    def test_compare_no_db_writes(self):
        before = self.catalog._db.total_changes
        self.library.compare(['fantasy', 'romance'])
        self.library.search()
        self.library.get('fantasy')
        self.assertEqual(self.catalog._db.total_changes, before)

    def test_render_list_safe(self):
        output = render_library_page(self.library.search())
        self.assertIn('Reference Pattern Library', output)
        self.assertIn('판타지', output)
        self.assertNotIn(PRIVATE_TEXT, output)
        self.assertNotIn(str(self.folder), output)
        self.assertNotIn('private_0', output)

    def test_render_comparison_safe(self):
        output = render_library_comparison(self.library.compare(['fantasy','romance']))
        self.assertIn('평균값 차이', output)
        self.assertIn('참고', output)
        self.assertNotIn(PRIVATE_TEXT, output)
        self.assertNotIn(str(self.folder), output)
        self.assertNotIn('위험했다', output)

    def test_render_rejects_forged_entry(self):
        page = self.library.search()
        forged = replace(page, entries=(replace(page.entries[0], genre=PRIVATE_TEXT),))
        with self.assertRaises(PatternLibraryError):
            render_library_page(forged)

    def test_render_rejects_wrong_page(self):
        with self.assertRaises(PatternLibraryError):
            render_library_page('raw source text')

    def test_render_rejects_wrong_comparison(self):
        with self.assertRaises(PatternLibraryError):
            render_library_comparison('raw source text')

    def test_reopen_database_and_recompute(self):
        with ReferenceCatalog(self.db) as reopened:
            library = ReferencePatternLibrary(GenrePatternStore(reopened))
            self.assertEqual(library.search().total, 2)
            self.assertEqual(library.compare(['fantasy','romance']).reference_counts, (2,2))

    def test_deleted_recipe_disappears(self):
        self.store.delete('fantasy')
        self.assertEqual(self.library.search().total, 1)
        self.assertEqual(ReferenceProfileStore(self.catalog).count(), 4)

    def test_no_network_needed(self):
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('network is forbidden')):
            self.assertEqual(self.library.search().total, 2)
            self.assertIn('판타지', render_library_comparison(
                self.library.compare(['fantasy','romance'])))

    def test_no_source_file_needed_after_import(self):
        for path in self.folder.glob('private_*.txt'):
            path.unlink()
        self.assertEqual(self.library.search().total, 2)
        self.assertEqual(len(self.library.compare(['fantasy','romance']).features), 6)

    def test_cli_search(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['--database', str(self.db), 'pattern-list', '--search', '판타지']), 0)
        self.assertIn('판타지', output.getvalue())
        self.assertNotIn('로맨스 (romance)', output.getvalue())

    def test_cli_show(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['--database', str(self.db), 'pattern-show', 'fantasy']), 0)
        self.assertIn('장르 패턴', output.getvalue())

    def test_cli_compare(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['--database', str(self.db), 'pattern-compare', 'fantasy', 'romance']), 0)
        self.assertIn('평균값 차이', output.getvalue())
        self.assertNotIn(str(self.folder), output.getvalue())

    def test_cli_status_and_page(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['--database', str(self.db), 'pattern-list', '--status', 'current', '--limit', '1']), 0)
        self.assertIn('총 2개', output.getvalue())

    def test_cli_stale_error_redacted(self):
        self.store.unassign(self.ids[0])
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(main(['--database', str(self.db), 'pattern-show', 'fantasy']), 1)
        self.assertIn('오류', err.getvalue())
        self.assertNotIn(str(self.folder), err.getvalue())

    def test_cli_reject_invalid_limit(self):
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(main(['--database', str(self.db), 'pattern-list', '--limit', '-1']), 1)
        self.assertIn('오류', err.getvalue())


@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'PySide6 not installed')
class PatternLibraryGuiTests(unittest.TestCase):
    def test_library_widgets_and_offline_refresh(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from ai_novel_factory.desktop.reference_profile_browser import ReferenceProfileBrowser
        from ai_novel_factory.desktop.reference_selection import ReferenceFileSelection
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'local.sqlite3'
            with patch('ai_novel_factory.desktop.reference_profile_browser.default_local_catalog_path', return_value=db):
                window = ReferenceProfileBrowser(ReferenceFileSelection())
                self.assertEqual(window.pattern_search.objectName(), 'patternLibrarySearchInput')
                self.assertEqual(window.pattern_list.objectName(), 'patternLibraryList')
                window._refresh_library()
                self.assertIn('총 0개', window.report.toPlainText())
                window.close()
        self.assertIsNotNone(app)
