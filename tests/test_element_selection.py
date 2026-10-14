"""Stage 35 offline selection, persistence, privacy, staleness and CLI regressions."""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
from pathlib import Path
import importlib.util
import io
import json
import socket
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory.database import ReferenceCatalog
from ai_novel_factory.database.element_selections import (
    ElementSelectionStore, ElementSelectionStorageError, SavedElementSelection,
)
from ai_novel_factory.database.genre_patterns import GenrePatternStore
from ai_novel_factory.database.pattern_strengths import PatternStrengthStore
from ai_novel_factory.references.element_selection import (
    ElementSelectionError, FEATURE_KEYS, FEATURE_LABELS, SelectedElement,
    render_element_selection, select_elements, validate_element_keys,
)
from ai_novel_factory.references.pattern_strength import preview_strengths
from ai_novel_factory.references.profile_cli import main as cli_main
from ai_novel_factory.references.profile_pipeline import import_reference_profile

PRIVATE = 'CANARY_COPYRIGHT_DO_NOT_PERSIST_78543'
WORKS = (
    '제1화\n\n그는 위험했다. 그러나 싸움이 끝났다.\n\n제2화\n\n결국 성공했다.',
    '제1화\n\n그녀는 기뻤다.\n\n제2화\n\n"왜?" 갑자기 공격이 시작됐다.',
    '제1화\n\n진실이 드러났다.\n\n제2화\n\n마침내 평화를 되찾았다.',
)


class ElementSelectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.path = self.folder / 'refs.sqlite3'
        self.catalog = ReferenceCatalog(self.path)
        self.addCleanup(self.catalog.close)
        self.genres = GenrePatternStore(self.catalog)
        self.strengths = PatternStrengthStore(self.catalog)
        self.ids = []
        for i, prose in enumerate(WORKS):
            file = self.folder / f'{PRIVATE}_{i}.txt'
            file.write_text(prose, encoding='utf-8')
            imported = import_reference_profile(file, catalog=self.catalog)
            self.ids.append(imported.reference.reference_id)
            self.genres.assign(imported.reference.reference_id, 'fantasy')
        self.genres.build('fantasy')
        self.genres.build('fantasy', weighting='characters')
        self.store = ElementSelectionStore(self.catalog)

    def test_fixed_feature_keys(self):
        self.assertEqual(len(FEATURE_KEYS), 6)
        self.assertEqual(len(FEATURE_LABELS), 6)

    def test_canonical_order(self):
        self.assertEqual(validate_element_keys(['emotion_balance', 'dialogue_ratio']),
                         ('dialogue_ratio', 'emotion_balance'))

    def test_one_feature_valid(self):
        self.assertEqual(validate_element_keys(['dialogue_ratio']), ('dialogue_ratio',))

    def test_all_features_valid(self):
        self.assertEqual(validate_element_keys(list(reversed(FEATURE_KEYS))), FEATURE_KEYS)

    def test_invalid_element_sets(self):
        for value in ([], (), 'dialogue_ratio', None, True, {'dialogue_ratio'},
                      ['dialogue_ratio']*2, ['dialogue_ratio']*7,
                      ['dialogue_ratio', PRIVATE], [1], [True], ['author_style'],
                      ["x'); DROP TABLE reference_files; --"]):
            with self.subTest(value=value), self.assertRaises(ElementSelectionError):
                validate_element_keys(value)

    def test_save_get_default(self):
        result = self.store.save('fantasy', ['emotion_balance', 'dialogue_ratio'])
        self.assertEqual(result.selected_keys, ('dialogue_ratio', 'emotion_balance'))
        self.assertEqual(self.store.get('fantasy'), result)
        self.assertEqual(result.reference_count, 3)

    def test_genre_classification_is_explicit(self):
        self.assertEqual(self.genres.list_assignments('fantasy')[0][1], 'fantasy')

    def test_no_selection_by_default(self):
        self.assertEqual(self.store.list(), ())
        with self.assertRaises(ElementSelectionStorageError):
            self.store.get('fantasy')

    def test_save_replaces_existing(self):
        self.store.save('fantasy', ['dialogue_ratio'])
        self.store.save('fantasy', ['lexical_diversity'])
        self.assertEqual(self.store.get('fantasy').selected_keys, ('lexical_diversity',))
        self.assertEqual(len(self.store.list()), 1)

    def test_delete_and_idempotence(self):
        self.store.save('fantasy', ['emotion_balance'])
        self.assertTrue(self.store.delete('fantasy'))
        self.assertFalse(self.store.delete('fantasy'))
        with self.assertRaises(ElementSelectionStorageError):
            self.store.get('fantasy')

    def test_delete_never_removes_profile_or_genre(self):
        self.store.save('fantasy', ['emotion_balance'])
        self.store.delete('fantasy')
        self.assertEqual(len(self.genres.list_assignments('fantasy')), 3)
        self.assertEqual(len(self.genres.get('fantasy').features), 6)

    def test_persist_across_reopening(self):
        self.store.save('fantasy', ['dialogue_ratio', 'emotion_balance'])
        with ReferenceCatalog(self.path) as reopened:
            other = ElementSelectionStore(reopened)
            self.assertEqual(other.get('fantasy').selected_keys,
                             ('dialogue_ratio', 'emotion_balance'))

    def test_equal_and_characters_separate(self):
        self.store.save('fantasy', ['dialogue_ratio'], weighting='equal')
        self.store.save('fantasy', ['emotion_balance'], weighting='characters')
        self.assertEqual(len(self.store.list()), 2)
        self.assertEqual(self.store.get('fantasy', weighting='characters').selected_keys,
                         ('emotion_balance',))

    def test_not_wrong_weighting(self):
        self.store.save('fantasy', ['dialogue_ratio'])
        with self.assertRaises(ElementSelectionStorageError):
            self.store.get('fantasy', weighting='characters')

    def test_bad_genre_and_weighting_rejected(self):
        for genre, mode in (('nonexistent','equal'), (PRIVATE,'equal'), (None,'equal'),
                            ('fantasy','arbitrary'), ('fantasy',True)):
            with self.subTest(genre=genre,mode=mode), self.assertRaises(ElementSelectionStorageError):
                self.store.save(genre, ['dialogue_ratio'], weighting=mode)

    def test_invalid_features_rejected_on_save(self):
        with self.assertRaises(ElementSelectionError):
            self.store.save('fantasy', ['copy_source_text'])

    def test_nonexistent_genre_recipe(self):
        with self.assertRaises(ElementSelectionStorageError):
            self.store.save('romance', ['dialogue_ratio'])

    def test_requires_two_active_sources(self):
        for reference_id in self.ids[:2]:
            self.strengths.set(reference_id, 0)
        with self.assertRaises(ElementSelectionStorageError):
            self.store.save('fantasy', ['dialogue_ratio'])

    def test_reject_60_percent_dominance(self):
        self.strengths.set(self.ids[0], 100)
        self.strengths.set(self.ids[1], 1)
        self.strengths.set(self.ids[2], 1)
        with self.assertRaises(ElementSelectionStorageError):
            self.store.save('fantasy', ['dialogue_ratio'])

    def test_saved_recipe_rechecked_after_strength_change(self):
        self.store.save('fantasy', ['dialogue_ratio'])
        self.strengths.set(self.ids[1], 0)
        self.strengths.set(self.ids[2], 0)
        with self.assertRaises(ElementSelectionStorageError):
            self.store.get('fantasy')
        self.assertFalse(self.store.list()[0].current)

    def test_restoration_after_strength_reset(self):
        self.store.save('fantasy', ['dialogue_ratio'])
        self.strengths.set(self.ids[0], 100)
        self.strengths.set(self.ids[1], 0)
        self.strengths.set(self.ids[2], 0)
        self.assertFalse(self.store.list()[0].current)
        for item in self.ids:
            self.strengths.reset(item)
        self.assertTrue(self.store.list()[0].current)
        self.assertEqual(self.store.get('fantasy').selected_keys, ('dialogue_ratio',))

    def test_stale_on_reassignment(self):
        self.store.save('fantasy', ['dialogue_ratio'])
        self.genres.assign(self.ids[0], 'romance')
        with self.assertRaises(ElementSelectionStorageError):
            self.store.get('fantasy')
        self.assertFalse(self.store.list()[0].current)

    def test_stale_on_profile_deletion(self):
        from ai_novel_factory.database.reference_profiles import ReferenceProfileStore
        self.store.save('fantasy', ['dialogue_ratio'])
        ReferenceProfileStore(self.catalog).delete(self.ids[0])
        with self.assertRaises(ElementSelectionStorageError):
            self.store.get('fantasy')

    def test_empty_strength_disallowed(self):
        for item in self.ids:
            self.strengths.set(item, 0)
        with self.assertRaises(ElementSelectionStorageError):
            self.store.save('fantasy', ['dialogue_ratio'])

    def test_saved_key_corruption_rejected(self):
        self.store.save('fantasy', ['dialogue_ratio'])
        with self.catalog._db:
            self.catalog._db.execute('UPDATE reference_element_selections SET keys_json=?',
                                     ('["dialogue_ratio","dialogue_ratio"]',))
        with self.assertRaises(ElementSelectionStorageError):
            self.store.get('fantasy')

    def test_saved_noncanonical_corruption_rejected(self):
        self.store.save('fantasy', ['dialogue_ratio'])
        with self.catalog._db:
            self.catalog._db.execute('UPDATE reference_element_selections SET keys_json=?',
                                     ('["emotion_balance","dialogue_ratio"]',))
        with self.assertRaises(ElementSelectionStorageError):
            self.store.get('fantasy')

    def test_saved_malicious_key_rejected(self):
        self.store.save('fantasy', ['dialogue_ratio'])
        with self.catalog._db:
            self.catalog._db.execute('UPDATE reference_element_selections SET keys_json=?',
                                     ('["' + PRIVATE + '"]',))
        with self.assertRaises(ElementSelectionStorageError):
            self.store.get('fantasy')

    def test_saved_malformed_json_rejected(self):
        self.store.save('fantasy', ['dialogue_ratio'])
        with self.catalog._db:
            self.catalog._db.execute('UPDATE reference_element_selections SET keys_json=?', ('bad',))
        with self.assertRaises(ElementSelectionStorageError):
            self.store.get('fantasy')

    def test_corrupt_timestamp_rejected_in_list(self):
        self.store.save('fantasy', ['dialogue_ratio'])
        with self.catalog._db:
            self.catalog._db.execute('UPDATE reference_element_selections SET updated_at=?', (PRIVATE,))
        with self.assertRaises(ElementSelectionStorageError):
            self.store.list()

    def test_duplicate_group_key_unique(self):
        self.store.save('fantasy', ['dialogue_ratio'])
        self.assertEqual(len(self.store.list()), 1)
        with self.assertRaises(Exception):
            with self.catalog._db:
                self.catalog._db.execute('INSERT INTO reference_element_selections VALUES (?,?,?,?)',
                                         ('fantasy','equal','["dialogue_ratio"]','2026-10-12T12:00:00.000000+00:00'))

    def test_no_raw_content_persisted(self):
        self.store.save('fantasy', ['dialogue_ratio'])
        with self.catalog._db:
            stored = self.catalog._db.execute('SELECT * FROM reference_element_selections').fetchall()
        self.assertNotIn(PRIVATE, repr(tuple(tuple(row) for row in stored)))
        self.assertNotIn('위험', repr(tuple(tuple(row) for row in stored)))

    def test_render_uses_fixed_labels(self):
        rendered = render_element_selection(self.store.save('fantasy', FEATURE_KEYS))
        self.assertIn('대사 비율', rendered)
        self.assertNotIn(PRIVATE, rendered)
        self.assertEqual(rendered.count('\n- '), 6)

    def test_render_detects_tampering(self):
        valid = self.store.save('fantasy', ['dialogue_ratio'])
        with self.assertRaises(ElementSelectionError):
            render_element_selection(replace(valid, elements=(SelectedElement('dialogue_ratio', PRIVATE, 5),)))

    def test_selected_observed_not_targets(self):
        preview = preview_strengths(self.genres, self.strengths, 'fantasy')
        result = select_elements(preview, ['emotion_balance'])
        self.assertAlmostEqual(result.elements[0].observed_mean,
                               dict((p.key, p.weighted_mean) for p in preview.features)['emotion_balance'])

    def test_nonfinite_values_rejected(self):
        preview = preview_strengths(self.genres, self.strengths, 'fantasy')
        bad = replace(preview, features=(replace(preview.features[0], weighted_mean=float('nan')),
                                         *preview.features[1:]))
        with self.assertRaises(ElementSelectionError):
            select_elements(bad, ['dialogue_ratio'])

    def test_no_socket_required(self):
        with patch.object(socket, 'create_connection', side_effect=AssertionError('unexpected network')):
            self.store.save('fantasy', ['dialogue_ratio'])
            self.store.get('fantasy')
            self.store.list()

    def test_list_contains_only_fixed_schema(self):
        self.store.save('fantasy', ['emotion_balance'])
        entries = self.store.list()
        self.assertEqual(len(entries), 1)
        self.assertIsInstance(entries[0], SavedElementSelection)
        self.assertTrue(entries[0].current)
        self.assertEqual(entries[0].selected_keys, ('emotion_balance',))

    def test_cli_save_show_list_delete(self):
        actions = [
            ['elements-save', 'fantasy', 'dialogue_ratio', 'emotion_balance'],
            ['elements-show', 'fantasy'],
            ['elements-list'],
            ['elements-delete', 'fantasy'],
        ]
        captures = []
        for action in actions:
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli_main(['--database', str(self.path), *action]), 0)
            captures.append(output.getvalue())
        self.assertIn('대사 비율', captures[1])
        self.assertIn('fantasy', captures[2])
        self.assertIn('삭제됨', captures[3])

    def test_cli_rejects_stale(self):
        self.store.save('fantasy', ['dialogue_ratio'])
        self.strengths.set(self.ids[0], 100)
        self.strengths.set(self.ids[1], 0)
        self.strengths.set(self.ids[2], 0)
        output = io.StringIO()
        with redirect_stderr(output):
            status = cli_main(['--database', str(self.path), 'elements-show', 'fantasy'])
        self.assertEqual(status, 1)
        self.assertNotIn(PRIVATE, output.getvalue())

    def test_cli_rejects_unapproved_metric(self):
        output = io.StringIO()
        with redirect_stderr(output):
            status = cli_main(['--database', str(self.path), 'elements-save', 'fantasy', PRIVATE])
        self.assertNotEqual(status, 0)
        self.assertNotIn(PRIVATE, output.getvalue())

    @unittest.skipUnless(importlib.util.find_spec('PySide6'), 'PySide6 GUI environment unavailable')
    def test_gui_controls(self):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        from ai_novel_factory.desktop.reference_profile_browser import ReferenceProfileBrowser
        from ai_novel_factory.desktop.reference_selection import ReferenceFileSelection
        app = QApplication.instance() or QApplication([])
        self.assertIsNotNone(app)
        widget = ReferenceProfileBrowser(ReferenceFileSelection())
        try:
            self.assertEqual(widget.element_list.count(), 6)
            self.assertEqual(widget.elements_save_button.objectName(), 'saveReferenceElementsButton')
            self.assertEqual(widget.elements_show_button.objectName(), 'showReferenceElementsButton')
        finally:
            widget.close()


if __name__ == '__main__':
    unittest.main()
