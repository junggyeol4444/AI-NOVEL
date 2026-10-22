"""Regression: mixed reference annotations retain review evidence, not approval.

Only partial manually supplied scene/structure annotations are inspected;
missing sources stay explicitly unexamined and fail the clear gate.
"""
import unittest
from hashlib import sha256
from unittest.mock import patch
from types import SimpleNamespace

from ai_novel_factory.reference_similarity_checker import (
    ReferenceMaterial, TextSpan, _scene_matches, _structure_matches,
    check_reference_similarity, require_reference_similarity_clear,
    ReferenceSimilarityError,
)

PID = 'c' * 32
DRAFT = '달빛 아래 탐험가가 오래된 도시의 문을 열고 낯선 곳으로 걸어갔다.'
REF_OTHER = '아침에는 마을 사람들이 광장에서 서로의 소식을 나누고 있었다.'
BEATS = ('setup', 'inciting', 'reversal', 'climax', 'resolution')


def reference(number, text, *, scenes=True, beats=()):
    return ReferenceMaterial(
        f'{number:032x}', sha256(text.encode('utf-8')).hexdigest(), text,
        (TextSpan(0, len(text)),) if scenes else (), beats,
    )


class PartialReferenceAnnotationTests(unittest.TestCase):
    def test_annotated_second_reference_scene_still_matches(self):
        refs = (reference(1, REF_OTHER, scenes=False),
                reference(2, DRAFT, scenes=True))
        unexamined, evidence = set(), []
        count = _scene_matches(DRAFT, (TextSpan(0, len(DRAFT)),),
                               refs, unexamined, lambda *args: evidence.append(args))
        self.assertEqual(count, 1)
        self.assertEqual(evidence[0][0:2], ('SCENE', 2))
        self.assertIn('scene_annotations_missing', unexamined)

    def test_annotated_first_reference_scene_still_matches(self):
        refs = (reference(1, DRAFT), reference(2, REF_OTHER, scenes=False))
        unexamined, evidence = set(), []
        count = _scene_matches(DRAFT, (TextSpan(0, len(DRAFT)),),
                               refs, unexamined, lambda *args: evidence.append(args))
        self.assertEqual(count, 1)
        self.assertEqual(evidence[0][0:2], ('SCENE', 1))
        self.assertIn('scene_annotations_missing', unexamined)

    def test_annotated_second_reference_structure_still_matches(self):
        refs = (reference(1, REF_OTHER, beats=()),
                reference(2, DRAFT, beats=BEATS))
        unexamined, evidence = set(), []
        count = _structure_matches(BEATS, refs, unexamined,
                                   lambda *args: evidence.append(args))
        self.assertEqual(count, 1)
        self.assertEqual(evidence[0][0:2], ('STRUCTURE', 2))
        self.assertIn('structure_annotations_missing', unexamined)

    def test_all_annotations_missing_remains_inconclusive(self):
        refs = (reference(1, REF_OTHER, scenes=False),
                reference(2, DRAFT, scenes=False))
        flags, evidence = set(), []
        count = _scene_matches(DRAFT, (TextSpan(0, len(DRAFT)),),
                               refs, flags, lambda *args: evidence.append(args))
        self.assertEqual(count, 0)
        self.assertEqual(evidence, [])
        self.assertIn('scene_annotations_missing', flags)
        flags.clear()
        count = _structure_matches(BEATS, refs, flags, lambda *args: evidence.append(args))
        self.assertEqual(count, 0)
        self.assertIn('structure_annotations_missing', flags)

    def test_missing_draft_annotation_does_not_invent_scene_evidence(self):
        refs = (reference(1, DRAFT),)
        flags, evidence = set(), []
        self.assertEqual(_scene_matches(DRAFT, (), refs, flags,
                                        lambda *args: evidence.append(args)), 0)
        self.assertIn('scene_annotations_missing', flags)
        self.assertEqual(evidence, [])

    def test_partial_coverage_report_is_review_not_publication_approval(self):
        refs = (reference(1, REF_OTHER, scenes=False),
                reference(2, DRAFT, scenes=True))
        # Force only the unrelated lexical baseline to clear, to isolate
        # the scene gate. The actual annotated reference remains identical.
        fake = SimpleNamespace(status='clear', exact_overlap_status='clear')
        with patch('ai_novel_factory.reference_similarity_checker.analyze_similarity_baseline',
                   return_value=fake), patch(
                   'ai_novel_factory.reference_similarity_checker._sentence_matches',
                   return_value=0):
            report = check_reference_similarity(
                PID, 2, DRAFT, references=refs,
                draft_scenes=(TextSpan(0, len(DRAFT)),), draft_beats=())
        self.assertEqual(report.status, 'review')
        self.assertEqual(report.scene_matches, 1)
        self.assertIn('scene_annotations_missing', report.unexamined)
        self.assertFalse(report.manuscript_approved)
        self.assertFalse(report.publication_approved)
        self.assertFalse(report.passed_checked_scope)


if __name__ == '__main__':
    unittest.main()
