"""Stage 78: reference similarity with explicit scope and no publication approval."""
from dataclasses import replace
from hashlib import sha256
import unittest
from unittest.mock import patch

from ai_novel_factory.database.reference_catalog import ReferenceCatalog
from ai_novel_factory.references.copy_protection import analyze_copy_protection
from ai_novel_factory.episode_assembler import EpisodeDraftPreview, SceneSpan
from ai_novel_factory.reference_similarity_checker import (
    ReferenceMaterial, ReferenceSimilarityError, TextSpan,
    check_reference_similarity, check_episode_reference_similarity,
    require_reference_similarity_clear, _sentence_matches,
)

PID = 'a' * 32
DRAFT = ('달빛 아래 탐험가가 새로운 도시의 문을 열었다.\n'
         '낯선 정원에서는 사람들이 서로 다른 노래를 부르고 있었다.')
SOURCE = ('깊은 바닷속의 탐사선은 오래된 암석을 조사했다.\n'
          '멀리 보이는 산맥에서는 작은 구름들이 천천히 흩어지고 있었다.')
BEATS_DRAFT = ('setup', 'reversal', 'escalation', 'climax', 'hook')
BEATS_REF = ('inciting', 'setback', 'resolution', 'transition', 'setup')


def h(text):
    return sha256(text.encode()).hexdigest()


def ref(record, text=SOURCE, *, beats=BEATS_REF, scenes=True):
    return ReferenceMaterial(record.reference_id, record.sha256, text,
                             (TextSpan(0, len(text)),) if scenes else (), beats)


class Stage78SimilarityTests(unittest.TestCase):
    def setUp(self):
        self.catalog = ReferenceCatalog(':memory:')
        self.record = self.catalog.register(file_name='reference.txt', source_format='txt',
                                            byte_count=len(SOURCE.encode()), sha256=h(SOURCE))
        self.catalog.change_status(self.record.reference_id, 'analyzing')
        self.catalog.change_status(self.record.reference_id, 'analyzed')

    def tearDown(self):
        self.catalog.close()

    def check(self, draft=DRAFT, references=None, *, draft_scenes=None,
              draft_beats=BEATS_DRAFT, required=True, catalog=True):
        if references is None:
            references = (ref(self.record),)
        if draft_scenes is None:
            draft_scenes = (TextSpan(0, len(draft)),) if isinstance(draft, str) else ()
        return check_reference_similarity(
            PID, 3, draft, references=references,
            draft_scenes=draft_scenes, draft_beats=draft_beats,
            required_reference_ids=(self.record.reference_id,) if required else None,
            catalog=self.catalog if catalog else None,
        )

    def test_clear_checked_scope_is_not_approval(self):
        report = self.check()
        self.assertEqual(report.status, 'clear')
        self.assertEqual(report.direct_status, 'clear')
        self.assertEqual(report.paragraph_status, 'clear')
        self.assertTrue(report.registration_checked)
        self.assertTrue(report.passed_checked_scope)
        self.assertFalse(report.manuscript_approved)
        self.assertFalse(report.publication_approved)
        self.assertFalse(report.persisted)
        self.assertEqual(report.draft_sha256, h(DRAFT))
        self.assertEqual(report.reference_text_sha256, (h(SOURCE),))
        self.assertNotIn('탐험가', repr(report))
        self.assertNotIn('바닷속', repr(report))

    def test_direct_copy_blocked(self):
        long_source = SOURCE * 3
        record = self.catalog.register(file_name='long.txt', source_format='txt',
                                       byte_count=len(long_source.encode()), sha256=h(long_source))
        self.catalog.change_status(record.reference_id, 'analyzing')
        self.catalog.change_status(record.reference_id, 'analyzed')
        report = check_reference_similarity(
            PID, 3, long_source, references=(ref(record, long_source),),
            draft_scenes=(TextSpan(0, len(long_source)),), draft_beats=BEATS_DRAFT,
            required_reference_ids=(record.reference_id,), catalog=self.catalog)
        self.assertEqual(report.status, 'blocked')
        self.assertEqual(report.direct_status, 'blocked')
        self.assertFalse(report.passed_checked_scope)

    def test_exact_sentence_review(self):
        draft = '다른 문장으로 시작한다.\n' + SOURCE.split('\n')[1]
        report = self.check(draft)
        self.assertEqual(report.status, 'review')
        self.assertGreaterEqual(report.sentence_matches, 1)
        evidence = next(e for e in report.evidence if e.channel == 'SENTENCE')
        self.assertEqual(draft[evidence.draft_start:evidence.draft_end], SOURCE.split('\n')[1])
        self.assertEqual(evidence.reference_number, 1)

    def test_sentence_near_match(self):
        source = SOURCE.split('\n')[1]
        draft = '멀리 보이는 산맥에서는 작은 구름들이 매우 천천히 흩어지고 있었다.'
        report = self.check(draft)
        self.assertEqual(report.status, 'review')
        self.assertGreaterEqual(report.sentence_matches, 1)

    def test_scene_match(self):
        # The sentence changes, but the combined scene still has large overlap.
        draft = SOURCE.replace('탐사선은', '조사팀은')
        report = self.check(draft)
        self.assertEqual(report.status, 'review')
        self.assertEqual(report.scene_matches, 1)
        evidence = next(e for e in report.evidence if e.channel == 'SCENE')
        self.assertEqual((evidence.draft_start, evidence.draft_end), (0, len(draft)))

    def test_structure_match_with_unrelated_prose(self):
        report = self.check(draft_beats=BEATS_REF)
        self.assertEqual(report.status, 'review')
        self.assertEqual(report.structure_matches, 1)
        evidence = next(e for e in report.evidence if e.channel == 'STRUCTURE')
        self.assertIsNone(evidence.draft_start)
        self.assertEqual(evidence.score, 1.0)

    def test_structure_similar_not_identical(self):
        beats = ('inciting', 'setback', 'resolution', 'transition', 'hook')
        report = self.check(draft_beats=beats)
        self.assertEqual(report.structure_matches, 0)

    def test_no_scene_annotations_inconclusive(self):
        report = self.check(draft_scenes=())
        self.assertEqual(report.status, 'inconclusive')
        self.assertIn('scene_annotations_missing', report.unexamined)

    def test_reference_scene_annotations_missing(self):
        report = self.check(references=(ref(self.record, scenes=False),))
        self.assertEqual(report.status, 'inconclusive')
        self.assertIn('scene_annotations_missing', report.unexamined)

    def test_short_reference_scene_is_not_silently_cleared(self):
        tiny = '짧은 글.'
        report = self.check(references=(ref(self.record, text=tiny),))
        self.assertEqual(report.status, 'inconclusive')
        self.assertIn('short_reference_scenes_not_compared', report.unexamined)

    def test_short_reference_sentences_not_silently_cleared(self):
        tiny = '짧다.'
        report = self.check(references=(ref(self.record, text=tiny),))
        self.assertEqual(report.status, 'inconclusive')
        self.assertIn('reference_sentence_coverage_insufficient', report.unexamined)

    def test_structure_missing_inconclusive(self):
        report = self.check(draft_beats=())
        self.assertEqual(report.status, 'inconclusive')
        self.assertIn('structure_annotations_missing', report.unexamined)

    def test_reference_structure_missing_inconclusive(self):
        report = self.check(references=(ref(self.record, beats=()),))
        self.assertEqual(report.status, 'inconclusive')

    def test_catalog_missing_inconclusive(self):
        report = self.check(catalog=False)
        self.assertEqual(report.status, 'inconclusive')
        self.assertIn('reference_registration_not_verified', report.unexamined)

    def test_required_reference_set_missing_inconclusive(self):
        report = self.check(required=False)
        self.assertEqual(report.status, 'inconclusive')

    def test_required_reference_set_mismatch_rejected(self):
        with self.assertRaises(ReferenceSimilarityError):
            check_reference_similarity(PID, 3, DRAFT, references=(ref(self.record),),
                                       required_reference_ids=('f' * 32,), catalog=self.catalog)

    def test_reference_missing_from_catalog_rejected(self):
        foreign = replace(ref(self.record), reference_id='f' * 32)
        with self.assertRaises(ReferenceSimilarityError):
            self.check(references=(foreign,), required=False)

    def test_reference_sha_mismatch_rejected(self):
        with self.assertRaises(ReferenceSimilarityError):
            self.check(references=(replace(ref(self.record), source_sha256='f' * 64),))

    def test_registered_but_not_analyzed_rejected(self):
        record = self.catalog.register(file_name='other.txt', source_format='txt',
                                       byte_count=3, sha256='b' * 64)
        with self.assertRaises(ReferenceSimilarityError):
            self.check(references=(ReferenceMaterial(record.reference_id, record.sha256,
                                                      SOURCE, (TextSpan(0, len(SOURCE)),), BEATS_REF),),
                       required=False)

    def test_duplicate_reference_ids_rejected(self):
        with self.assertRaises(ReferenceSimilarityError):
            self.check(references=(ref(self.record), ref(self.record)))

    def test_one_hundred_registered_references_include_last_and_fail_closed(self):
        # Disposable catalog only. The 100th source must actually be examined.
        references = []
        for n in range(99):
            text = ('완전히 별개의 검사용 항해 기록과 장치 설명입니다. '
                    + str(n).zfill(3) + '번 실험은 독립된 가상 사건입니다.') * 2
            record = self.catalog.register(
                file_name=f'synthetic-{n:03}.txt', source_format='txt',
                byte_count=len(text.encode()), sha256=h(text))
            self.catalog.change_status(record.reference_id, 'analyzing')
            self.catalog.change_status(record.reference_id, 'analyzed')
            references.append(ref(record, text, scenes=False, beats=()))
        references.append(ref(self.record))
        selected = tuple(item.reference_id for item in references)
        direct = analyze_copy_protection(SOURCE, tuple(item.text for item in references))
        self.assertIsNotNone(direct.evidence)
        self.assertEqual(direct.evidence.reference_number, 100)
        report = check_reference_similarity(
            PID, 3, SOURCE, references=tuple(references),
            required_reference_ids=selected, catalog=self.catalog)
        self.assertEqual(len(report.reference_ids), 100)
        self.assertTrue(report.registration_checked)
        self.assertIn(report.status, ('blocked', 'review', 'inconclusive'))
        self.assertFalse(report.manuscript_approved)
        self.assertFalse(report.publication_approved)
        with self.assertRaises(ReferenceSimilarityError):
            check_reference_similarity(
                PID, 3, SOURCE, references=tuple(references[:-1]),
                required_reference_ids=selected, catalog=self.catalog)
        with self.assertRaises(ReferenceSimilarityError):
            check_reference_similarity(
                PID, 3, SOURCE, references=tuple(references) + (
                    ReferenceMaterial('f' * 32, 'f' * 64, '초과된 독립 참고 원문입니다.'),))

    def test_sentence_budget_still_samples_hundredth_reference(self):
        # Sentence budget used to consume all 4,000 entries in earlier sources.
        target = '깊은협곡에서비밀의서고를찾아낸순례자들은희망의빛을보았다'
        filler = '오늘은평범한광장에서전혀다른약속을준비했다'
        references = tuple(ReferenceMaterial('a' * 32, 'b' * 64,
                                            'LAST' if n == 99 else f'REF{n}')
                           for n in range(100))
        def sentences(text):
            if text in ('DRAFT', 'LAST'):
                return [(0, len(target), target)]
            return [(0, len(filler), filler)] * 41
        flags, hits = set(), []
        with patch('ai_novel_factory.reference_similarity_checker._sentences',
                   side_effect=sentences):
            count = _sentence_matches('DRAFT', references, flags,
                                      lambda kind, number, *_: hits.append((kind, number)))
        self.assertEqual(count, 1)
        self.assertEqual(hits, [('SENTENCE', 100)])
        self.assertIn('sentence_count_budget_exceeded', flags)

    def test_invalid_id_rejected(self):
        with self.assertRaises(ReferenceSimilarityError):
            self.check(references=(replace(ref(self.record), reference_id='../secrets'),))

    def test_invalid_text_rejected(self):
        for text in ('', '\x00', '\ud800', '   ', None):
            with self.subTest(text=repr(text)), self.assertRaises(ReferenceSimilarityError):
                self.check(text)

    def test_invalid_episode_and_project(self):
        for episode in (0, True, '3', 1_000_001):
            with self.subTest(episode=episode), self.assertRaises(ReferenceSimilarityError):
                check_reference_similarity(PID, episode, DRAFT, references=(ref(self.record),))
        with self.assertRaises(ReferenceSimilarityError):
            check_reference_similarity('invalid', 1, DRAFT, references=(ref(self.record),))

    def test_invalid_scene_spans_rejected(self):
        for spans in ((TextSpan(1, len(DRAFT)),), (TextSpan(0, len(DRAFT) - 1),),
                      (TextSpan(0, 12), TextSpan(10, len(DRAFT))),
                      (TextSpan(True, len(DRAFT)),), (TextSpan(0, 0),),
                      [TextSpan(0, len(DRAFT))]):
            with self.subTest(spans=repr(spans)), self.assertRaises(ReferenceSimilarityError):
                self.check(draft_scenes=spans)

    def test_whitespace_between_scenes_allowed(self):
        draft = '한 문장이 길게 이어지고 새로운 장면이 펼쳐졌다.\n\n' + DRAFT
        first_end = draft.index('\n\n')
        report = self.check(draft, draft_scenes=(TextSpan(0, first_end),
                                                 TextSpan(first_end + 2, len(draft))))
        self.assertTrue(report.registration_checked)

    def test_invalid_beats_rejected(self):
        for beats in (('setup', 'SECRET_CHARACTER_NAME'), ['setup'], ('setup', 3)):
            with self.subTest(beats=repr(beats)), self.assertRaises(ReferenceSimilarityError):
                self.check(draft_beats=beats)

    def test_invalid_catalog_rejected(self):
        with self.assertRaises(ReferenceSimilarityError):
            check_reference_similarity(PID, 1, DRAFT, references=(ref(self.record),), catalog='db')

    def test_baseline_input_limit_fails_closed(self):
        with self.assertRaises(ReferenceSimilarityError):
            self.check('a' * 400001)

    def test_clear_guard_reruns_and_never_approves(self):
        args = dict(references=(ref(self.record),), draft_scenes=(TextSpan(0, len(DRAFT)),),
                    draft_beats=BEATS_DRAFT, required_reference_ids=(self.record.reference_id,),
                    catalog=self.catalog)
        report = require_reference_similarity_clear(PID, 3, DRAFT, **args)
        self.assertEqual(report.status, 'clear')
        self.assertFalse(report.manuscript_approved)
        with self.assertRaises(ReferenceSimilarityError):
            require_reference_similarity_clear(PID, 3, SOURCE, **dict(args, draft_scenes=(TextSpan(0, len(SOURCE)),)))

    def test_guard_rejects_unverified_registration(self):
        with self.assertRaises(ReferenceSimilarityError):
            require_reference_similarity_clear(PID, 3, DRAFT, references=(ref(self.record),),
                                               draft_scenes=(TextSpan(0, len(DRAFT)),),
                                               draft_beats=BEATS_DRAFT)

    def test_short_sentences_unexamined(self):
        report = self.check('짧다. 또 짧다.', draft_scenes=(TextSpan(0, len('짧다. 또 짧다.')),))
        self.assertEqual(report.status, 'inconclusive')
        self.assertIn('sentence_comparison_insufficient', report.unexamined)

    def test_long_sentences_unexamined(self):
        draft = '다' * 501 + '.'
        report = self.check(draft)
        self.assertEqual(report.status, 'inconclusive')
        self.assertIn('long_sentences_not_compared', report.unexamined)

    def test_no_raw_text_in_report(self):
        report = self.check(SOURCE)
        self.assertNotIn('오래된 암석', repr(report))
        self.assertNotIn('탐사선', repr(report))

    def test_source_text_sha_digest_is_bound_to_report(self):
        report = self.check()
        self.assertEqual(report.reference_text_sha256, (h(SOURCE),))
        self.assertEqual(report.reference_ids, (self.record.reference_id,))

    def test_preview_integration(self):
        first, second = DRAFT.split('\n')
        draft = first + '\n\n' + second
        spans = (SceneSpan(1, 0, len(first), h(first), h('prompt1'), ('fact',)),
                 SceneSpan(2, len(first) + 2, len(draft), h(second), h('prompt2'), ('fact',)))
        preview = EpisodeDraftPreview(PID, 3, draft, h(draft), spans, ('fact',),
                                      'offline-mock-v1', 'DETERMINISTIC_MOCK_NOT_AI')
        report = check_episode_reference_similarity(
            preview, references=(ref(self.record),), draft_beats=BEATS_DRAFT,
            required_reference_ids=(self.record.reference_id,), catalog=self.catalog)
        self.assertEqual(report.status, 'inconclusive')
        self.assertIn('short_scenes_not_compared', report.unexamined)
        for bad in (replace(preview, draft_sha256='f' * 64),
                    replace(preview, persisted=True),
                    replace(preview, publication_approved=True),
                    replace(preview, status='APPROVED'),
                    replace(preview, scenes=(replace(spans[0], draft_sha256='b' * 64), spans[1])),
                    replace(preview, scenes=(spans[1], spans[0])),
                    replace(preview, draft=draft + 'x')):
            with self.subTest(bad=repr(bad)[:40]), self.assertRaises(ReferenceSimilarityError):
                check_episode_reference_similarity(bad, references=(ref(self.record),))

    def test_report_does_not_include_source_or_draft(self):
        report = self.check()
        self.assertFalse(hasattr(report, 'draft'))
        self.assertFalse(hasattr(report, 'reference_text'))
        self.assertFalse(hasattr(report, 'source_path'))


if __name__ == '__main__':
    unittest.main()