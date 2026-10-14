"""Stage 34: explicit per-work statistical influence and local privacy rules."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
import importlib.util
import io
import json
import os
import socket
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory.database import ReferenceCatalog
from ai_novel_factory.database.genre_patterns import GenrePatternStore
from ai_novel_factory.database.pattern_strengths import (
    DEFAULT_STRENGTH, PatternStrengthStore, PatternStrengthStorageError, StrengthSetting,
    validate_strength, validate_reference_id,
)
from ai_novel_factory.database.reference_profiles import ReferenceProfileStore
from ai_novel_factory.references.pattern_strength import (
    PatternStrengthError, WorkInfluence, PatternStrengthPreview,
    preview_strengths, render_strength_preview,
)
from ai_novel_factory.references.profile_cli import main as cli
from ai_novel_factory.references.profile_pipeline import import_reference_profile

PRIVATE = 'COPYRIGHT_DO_NOT_COPY_721973118'
WORKS = (
    '제1화\n\n그는 위험했다. 그러나 상황이 좋아졌다.\n\n제2화\n\n결국 성공했다.',
    '제1화\n\n"정말?" 그는 슬펐다.\n\n제2화\n\n갑자기 공격했다.',
    '제1화\n\n마침내 평화로웠다.\n\n제2화\n\n그녀는 행복했다.',
)


class PatternStrengthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.db = self.folder / 'refs.sqlite3'
        self.catalog = ReferenceCatalog(self.db)
        self.addCleanup(self.catalog.close)
        self.genres = GenrePatternStore(self.catalog)
        self.strengths = PatternStrengthStore(self.catalog)
        self.ids = []
        for idx, value in enumerate(WORKS):
            path = self.folder / f'source_{idx}.txt'
            path.write_text(value, encoding='utf-8')
            entry = import_reference_profile(path, catalog=self.catalog)
            self.ids.append(entry.reference.reference_id)
            self.genres.assign(entry.reference.reference_id, 'fantasy')
        self.genres.build('fantasy')
        self.genres.build('fantasy', weighting='characters')

    def preview(self, weighting='equal'):
        return preview_strengths(self.genres, self.strengths, 'fantasy', weighting=weighting)

    def test_default_value_fifty(self):
        self.assertEqual(self.strengths.get(self.ids[0]), DEFAULT_STRENGTH)
        self.assertEqual(self.strengths.list_overrides(), ())

    def test_set_and_get_zero(self):
        self.strengths.set(self.ids[0], 0)
        self.assertEqual(self.strengths.get(self.ids[0]), 0)

    def test_set_and_get_hundred(self):
        self.strengths.set(self.ids[0], 100)
        self.assertEqual(self.strengths.get(self.ids[0]), 100)

    def test_set_get_min_and_max(self):
        for value in (0, 1, 49, 50, 99, 100):
            with self.subTest(value=value):
                self.strengths.set(self.ids[0], value)
                self.assertEqual(self.strengths.get(self.ids[0]), value)

    def test_override_replace_no_duplicate(self):
        self.strengths.set(self.ids[0], 20)
        self.strengths.set(self.ids[0], 30)
        self.assertEqual(self.strengths.list_overrides(), (StrengthSetting(self.ids[0], 30),))

    def test_reset_returns_default(self):
        self.strengths.set(self.ids[0], 2)
        self.assertTrue(self.strengths.reset(self.ids[0]))
        self.assertFalse(self.strengths.reset(self.ids[0]))
        self.assertEqual(self.strengths.get(self.ids[0]), 50)

    def test_persist_reopen(self):
        self.strengths.set(self.ids[1], 73)
        with ReferenceCatalog(self.db) as reopened:
            self.assertEqual(PatternStrengthStore(reopened).get(self.ids[1]), 73)

    def test_sorted_overrides(self):
        self.strengths.set(self.ids[2], 20)
        self.strengths.set(self.ids[0], 80)
        self.assertEqual(tuple(item.reference_id for item in self.strengths.list_overrides()),
                         tuple(sorted((self.ids[2], self.ids[0]))))

    def test_input_validation(self):
        for value in (True, False, None, 1.0, '20', -1, 101, [], {}, 0.1):
            with self.subTest(value=value), self.assertRaises(PatternStrengthStorageError):
                self.strengths.set(self.ids[0], value)

    def test_id_validation(self):
        for value in (None, True, 1, '0'*31, 'G'*32, '0'*33, "x' OR 1=1 --", PRIVATE):
            with self.subTest(value=value), self.assertRaises(PatternStrengthStorageError):
                self.strengths.get(value)

    def test_nonexistent_id(self):
        with self.assertRaises(PatternStrengthStorageError):
            self.strengths.set('a'*32, 50)

    def test_missing_profile(self):
        row = self.catalog.register(file_name='new.txt', source_format='txt', byte_count=1, sha256='f'*64)
        with self.assertRaises(PatternStrengthStorageError):
            self.strengths.get(row.reference_id)

    def test_invalid_storage_constructor(self):
        with self.assertRaises(PatternStrengthStorageError):
            PatternStrengthStore(None)

    def test_sql_check_constraints(self):
        for value in (-2, 101, 1.5):
            with self.subTest(value=value), self.assertRaises(Exception):
                with self.catalog._db:
                    self.catalog._db.execute('INSERT INTO reference_pattern_strengths VALUES (?, ?)',
                                             (self.ids[0], value))
        self.assertEqual(self.strengths.get(self.ids[0]), 50)

    def test_corrupt_saved_value_refused(self):
        self.strengths.set(self.ids[0], 20)
        self.catalog._db.execute('PRAGMA ignore_check_constraints=ON')
        try:
            with self.catalog._db:
                self.catalog._db.execute('UPDATE reference_pattern_strengths SET strength=101 WHERE reference_id=?',
                                         (self.ids[0],))
        finally:
            self.catalog._db.execute('PRAGMA ignore_check_constraints=OFF')
        with self.assertRaises(PatternStrengthStorageError):
            self.strengths.get(self.ids[0])

    def test_clear_value_no_profile_change(self):
        before = ReferenceProfileStore(self.catalog).get(self.ids[0])
        self.strengths.set(self.ids[0], 0)
        self.assertEqual(before, ReferenceProfileStore(self.catalog).get(self.ids[0]))

    def test_preview_default_three(self):
        value = self.preview()
        self.assertTrue(value.usable_for_selection)
        self.assertEqual(value.active_count, 3)
        self.assertEqual(value.status, 'ready')
        self.assertEqual([round(x.effective_percent, 2) for x in value.influences],
                         [33.33]*3)

    def test_preview_six_features(self):
        value = self.preview()
        self.assertEqual(tuple(feature.key for feature in value.features),
                         ('dialogue_ratio', 'sentence_characters', 'lexical_diversity',
                          'emotion_balance', 'cliffhanger_episode_rate',
                          'event_cue_density_per_1000'))

    def test_preview_equal_strength_same_as_genre(self):
        p = self.genres.get('fantasy')
        for expected, actual in zip(p.features, self.preview().features):
            self.assertEqual(expected.key, actual.key)
            self.assertAlmostEqual(expected.weighted_mean, actual.weighted_mean, places=5)

    def test_preview_changes_weighted_mean(self):
        original = self.preview()
        self.strengths.set(self.ids[0], 0)
        updated = self.preview()
        self.assertNotEqual(original.influences, updated.influences)
        self.assertTrue(any(a.weighted_mean != b.weighted_mean
                            for a,b in zip(original.features, updated.features)))

    def test_preview_zero_excludes_one_without_deleting(self):
        self.strengths.set(self.ids[0], 0)
        v = self.preview()
        self.assertEqual(v.active_count, 2)
        self.assertTrue(v.usable_for_selection)
        self.assertEqual(ReferenceProfileStore(self.catalog).count(), 3)

    def test_preview_one_active_is_not_usable(self):
        for ref in self.ids[:2]:
            self.strengths.set(ref, 0)
        v = self.preview()
        self.assertFalse(v.usable_for_selection)
        self.assertEqual(v.status, 'fewer_than_two')
        self.assertEqual(v.max_share_percent, 100)

    def test_preview_all_zero_is_not_usable(self):
        for ref in self.ids:
            self.strengths.set(ref, 0)
        v = self.preview()
        self.assertFalse(v.usable_for_selection)
        self.assertEqual(v.status, 'empty')
        self.assertTrue(all(f.weighted_mean == 0 for f in v.features))

    def test_concentration_flag_and_no_silent_clamping(self):
        self.strengths.set(self.ids[0], 100)
        self.strengths.set(self.ids[1], 1)
        self.strengths.set(self.ids[2], 1)
        v = self.preview()
        self.assertFalse(v.usable_for_selection)
        self.assertEqual(v.status, 'over_concentrated')
        self.assertGreater(v.max_share_percent, 60)
        self.assertGreater(max(x.effective_percent for x in v.influences), 60)

    def test_change_strength_can_restore_ready(self):
        self.strengths.set(self.ids[0], 100)
        self.strengths.set(self.ids[1], 1)
        self.strengths.set(self.ids[2], 1)
        self.assertFalse(self.preview().usable_for_selection)
        self.strengths.set(self.ids[1], 100)
        self.strengths.set(self.ids[2], 100)
        self.assertTrue(self.preview().usable_for_selection)

    def test_preview_characters_mode(self):
        v = self.preview('characters')
        self.assertEqual(v.weighting, 'characters')
        self.assertEqual(v.reference_count, 3)
        self.assertAlmostEqual(sum(x.effective_percent for x in v.influences), 100, places=2)

    def test_preview_weighting_mismatch_is_rejected(self):
        for x in (True, 0, None, 'unknown', ''):
            with self.subTest(value=x), self.assertRaises(PatternStrengthError):
                preview_strengths(self.genres, self.strengths, 'fantasy', weighting=x)

    def test_preview_bad_genres(self):
        for x in (None, True, '', PRIVATE, "fantasy';--"):
            with self.subTest(value=x), self.assertRaises(PatternStrengthError):
                preview_strengths(self.genres, self.strengths, x)

    def test_preview_wrong_stores(self):
        for invalid in ((None, self.strengths), (self.genres, None), (self.strengths, self.genres)):
            with self.subTest(value=invalid), self.assertRaises(PatternStrengthError):
                preview_strengths(invalid[0], invalid[1], 'fantasy')

    def test_preview_missing_genre_recipe(self):
        with self.assertRaises(PatternStrengthError):
            preview_strengths(self.genres, self.strengths, 'romance')

    def test_preview_stale_recipe(self):
        self.genres.unassign(self.ids[0])
        with self.assertRaises(PatternStrengthError):
            self.preview()

    def test_preview_does_not_write(self):
        before = self.catalog._db.total_changes
        self.preview()
        self.preview('characters')
        self.assertEqual(self.catalog._db.total_changes, before)

    def test_source_text_never_in_settings_or_report(self):
        report = render_strength_preview(self.preview())
        assert PRIVATE not in report
        for text in ('그는 위험했다', '갑자기 공격했다', str(self.folder), 'source_0.txt'):
            self.assertNotIn(text, report)
            self.assertNotIn(text, repr(self.preview()))
        sql = '\n'.join(map(str, self.catalog._db.execute("SELECT sql FROM sqlite_master WHERE name='reference_pattern_strengths'")))
        self.assertNotIn('source_0', sql)

    def test_render_exposes_notice_but_not_source(self):
        report = render_strength_preview(self.preview())
        self.assertIn('원문 복제', report)
        self.assertIn('최대 점유', report)
        self.assertIn('통계 지표', report)

    def test_render_validates_wrong_type(self):
        with self.assertRaises(PatternStrengthError):
            render_strength_preview(None)

    def test_render_rejects_bad_entry(self):
        wrong = replace(self.preview(), influences=(WorkInfluence(PRIVATE, 50, 20),) + self.preview().influences[1:])
        with self.assertRaises(PatternStrengthError):
            render_strength_preview(wrong)

    def test_reopen_preview_without_original_files(self):
        for path in self.folder.glob('source_*.txt'):
            path.unlink()
        with ReferenceCatalog(self.db) as reopened:
            v = preview_strengths(GenrePatternStore(reopened), PatternStrengthStore(reopened), 'fantasy')
        self.assertEqual(v.reference_count, 3)

    def test_network_disabled(self):
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('network not allowed')):
            self.strengths.set(self.ids[0], 20)
            self.assertEqual(self.strengths.get(self.ids[0]), 20)
            self.assertEqual(self.preview().reference_count, 3)

    def test_list_only_overrides(self):
        self.strengths.set(self.ids[0], 25)
        self.assertEqual(len(self.strengths.list_overrides()), 1)

    def test_delete_reference_cascades_strength(self):
        self.strengths.set(self.ids[0], 70)
        with self.catalog._db:
            self.catalog._db.execute('DELETE FROM reference_files WHERE reference_id=?', (self.ids[0],))
        self.assertEqual(self.strengths.list_overrides(), ())

    def test_delete_profile_cascades_strength(self):
        self.strengths.set(self.ids[0], 75)
        self.assertTrue(ReferenceProfileStore(self.catalog).delete(self.ids[0]))
        self.assertEqual(self.strengths.list_overrides(), ())
        with self.assertRaises(PatternStrengthStorageError):
            self.strengths.get(self.ids[0])

    def test_cli_show_default(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli(['--database', str(self.db), 'strength-show', self.ids[0]]), 0)
        self.assertIn(': 50', output.getvalue())

    def test_cli_set_list_preview_reset(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli(['--database', str(self.db), 'strength-set', self.ids[0], '80']), 0)
            self.assertEqual(cli(['--database', str(self.db), 'strength-list']), 0)
            self.assertEqual(cli(['--database', str(self.db), 'strength-preview', 'fantasy']), 0)
            self.assertEqual(cli(['--database', str(self.db), 'strength-reset', self.ids[0]]), 0)
        self.assertIn('강도 저장 완료', out.getvalue())
        self.assertIn('검토 결과', out.getvalue())
        self.assertEqual(self.strengths.get(self.ids[0]), 50)

    def test_cli_invalid_strength_safe_error(self):
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(cli(['--database', str(self.db), 'strength-set', self.ids[0], '101']), 1)
        self.assertIn('오류:', err.getvalue())
        self.assertNotIn(str(self.folder), err.getvalue())

    def test_cli_missing_recipe_safe_error(self):
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(cli(['--database', str(self.db), 'strength-preview', 'romance']), 1)
        self.assertIn('다시 구축', err.getvalue())


@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'PySide6 not installed')
class StrengthGuiTests(unittest.TestCase):
    def test_new_strength_controls(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        from ai_novel_factory.desktop.reference_profile_browser import ReferenceProfileBrowser
        from ai_novel_factory.desktop.reference_selection import ReferenceFileSelection
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'refs.sqlite3'
            with patch('ai_novel_factory.desktop.reference_profile_browser.default_local_catalog_path', return_value=db):
                window = ReferenceProfileBrowser(ReferenceFileSelection())
                self.assertEqual(window.strength_spinner.objectName(), 'referencePatternStrengthSpinner')
                self.assertEqual((window.strength_spinner.minimum(), window.strength_spinner.maximum()), (0, 100))
                window._preview_genre_strengths()
                self.assertIn('패턴', window.report.toPlainText())
                window.close()
        self.assertIsNotNone(app)
