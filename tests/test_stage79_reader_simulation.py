"""Stage 79: manual evidence only; no subjective quality guarantees."""
from dataclasses import replace
from hashlib import sha256
import unittest

from ai_novel_factory.episode_assembler import EpisodeDraftPreview, SceneSpan
from ai_novel_factory.reader_simulation import (
    ReaderSimulationError, SceneReaderAnnotation, simulate_reader_profiles,
    annotations_from_episode_preview,
)

PID = 'a' * 32
A = '바람이 작은 항구에 불었다.'
B = '등불이 부두 끝에서 흔들렸다.'
DRAFT = A + '\n\n' + B
FLAGS = dict(goal_visible=True, tension_present=True, development=True,
             character_choice=True, consequence=True, closing_hook=True)


def scenes(text=DRAFT, first=None, second=None):
    first = FLAGS if first is None else first
    second = FLAGS if second is None else second
    return (SceneReaderAnnotation(1, 0, len(A), sha256(A.encode()).hexdigest(), **first),
            SceneReaderAnnotation(2, len(A) + 2, len(text),
                                  sha256(text[len(A)+2:].encode()).hexdigest(), **second))


def run(draft=DRAFT, marks=None, pid=PID, ep=1):
    return simulate_reader_profiles(pid, ep, draft, scenes=scenes(draft) if marks is None else marks)


class ReaderProxyTests(unittest.TestCase):
    def test_all_yes_score_100(self):
        report = run()
        self.assertEqual(report.status, 'ANNOTATED_PROXY_ONLY')
        self.assertEqual([m.score for m in report.metrics], [100, 100, 100, 100])
        self.assertEqual([p.score for p in report.profiles], [100, 100, 100])
        self.assertEqual(report.scene_count, 2)
        self.assertFalse(report.persisted)
        self.assertFalse(report.manuscript_approved)
        self.assertFalse(report.publication_approved)
        self.assertNotIn(A, repr(report))
        self.assertNotIn(B, repr(report))
        self.assertIn('NOT_REAL_READERS', report.methodology)

    def test_all_no_score_zero(self):
        no = dict.fromkeys(FLAGS, False)
        r = run(marks=scenes(first=no, second=no))
        self.assertEqual([m.score for m in r.metrics], [0, 0, 0, 0])
        self.assertEqual([p.score for p in r.profiles], [0, 0, 0])

    def test_hook_last_scene_only(self):
        last = {**FLAGS, 'closing_hook': False}
        r = run(marks=scenes(second=last))
        self.assertEqual(next(m.score for m in r.metrics if m.dimension == 'hook'), 30)
        self.assertEqual(next(m.score for m in r.metrics if m.dimension == 'engagement'), 100)

    def test_character_agency_affects_character_only(self):
        last = {**FLAGS, 'character_choice': False}
        r = run(marks=scenes(second=last))
        self.assertEqual(next(m.score for m in r.metrics if m.dimension == 'character'), 70)
        self.assertEqual(next(m.score for m in r.metrics if m.dimension == 'pacing'), 100)

    def test_missing_is_not_false(self):
        last = {**FLAGS, 'development': None}
        r = run(marks=scenes(second=last))
        self.assertEqual(r.status, 'INCOMPLETE_ANNOTATIONS')
        self.assertEqual(next(m.score for m in r.metrics if m.dimension == 'engagement'), None)
        self.assertEqual(next(m.score for m in r.metrics if m.dimension == 'pacing'), None)
        self.assertEqual(next(m.score for m in r.metrics if m.dimension == 'character'), 100)
        self.assertTrue(all(p.score is None for p in r.profiles))
        self.assertIn('incomplete_pacing_annotations', r.unexamined)

    def test_missing_hook_in_last_scene_only(self):
        first = {**FLAGS, 'closing_hook': None}
        r = run(marks=scenes(first=first))
        self.assertEqual(r.status, 'ANNOTATED_PROXY_ONLY')

    def test_text_change_invalidates_evidence(self):
        with self.assertRaises(ReaderSimulationError):
            run(DRAFT.replace('등불', '달빛'), marks=scenes())

    def test_digest_change_invalidates_evidence(self):
        broken = replace(scenes()[0], evidence_sha256='0' * 64)
        with self.assertRaises(ReaderSimulationError):
            run(marks=(broken, scenes()[1]))

    def test_uncovered_nonspace_invalid(self):
        first = scenes()[0]
        with self.assertRaises(ReaderSimulationError):
            run(marks=(first,))

    def test_gaps_whitespace_ok(self):
        self.assertEqual(run().scene_count, 2)

    def test_overlapping_scenes_invalid(self):
        second = replace(scenes()[1], start=1)
        with self.assertRaises(ReaderSimulationError):
            run(marks=(scenes()[0], second))

    def test_reversed_scenes_invalid(self):
        with self.assertRaises(ReaderSimulationError):
            run(marks=tuple(reversed(scenes())))

    def test_wrong_scene_numbers_invalid(self):
        with self.assertRaises(ReaderSimulationError):
            run(marks=(replace(scenes()[0], scene_number=2), scenes()[1]))

    def test_nonboolean_annotation_rejected(self):
        with self.assertRaises(ReaderSimulationError):
            run(marks=(replace(scenes()[0], development=1), scenes()[1]))

    def test_invalid_project_and_episode(self):
        for pid, ep in [('bad', 1), (PID, True), (PID, 0), (PID, 1_000_001)]:
            with self.subTest(pid=pid, ep=ep), self.assertRaises(ReaderSimulationError):
                run(pid=pid, ep=ep)

    def test_control_character_rejected(self):
        with self.assertRaises(ReaderSimulationError):
            run(draft=DRAFT + '\x00')

    def test_surrogate_rejected(self):
        with self.assertRaises(ReaderSimulationError):
            run(draft=DRAFT + '\ud800', marks=scenes())

    def test_empty_and_large_draft_rejected(self):
        for text in ['', ' ' * 10, 'a' * 1_000_001]:
            with self.assertRaises(ReaderSimulationError):
                run(draft=text)

    def test_bad_annotation_type_rejected(self):
        with self.assertRaises(ReaderSimulationError):
            run(marks=[*scenes()])

    def test_single_scene_works(self):
        s = SceneReaderAnnotation(1, 0, len(A), sha256(A.encode()).hexdigest(), **FLAGS)
        r = simulate_reader_profiles(PID, 1, A, scenes=(s,))
        self.assertEqual(r.metrics[-1].score, 100)

    def make_preview(self):
        span1 = SceneSpan(1, 0, len(A), sha256(A.encode()).hexdigest(), '0'*64, ())
        span2 = SceneSpan(2, len(A)+2, len(DRAFT), sha256(B.encode()).hexdigest(), '0'*64, ())
        p = EpisodeDraftPreview(PID, 1, DRAFT, sha256(DRAFT.encode()).hexdigest(),
                                (span1, span2), (), 'offline-mock-v1', 'DETERMINISTIC_MOCK_NOT_AI')
        return p

    def test_preview_adapter(self):
        p = self.make_preview()
        anns = annotations_from_episode_preview(p, marks=(FLAGS, FLAGS))
        self.assertEqual(run(marks=anns).metrics[0].score, 100)

    def test_preview_rejects_persisted(self):
        p = replace(self.make_preview(), persisted=True)
        with self.assertRaises(ReaderSimulationError):
            annotations_from_episode_preview(p, marks=(FLAGS, FLAGS))

    def test_preview_rejects_approved(self):
        p = replace(self.make_preview(), publication_approved=True)
        with self.assertRaises(ReaderSimulationError):
            annotations_from_episode_preview(p, marks=(FLAGS, FLAGS))

    def test_preview_rejects_modified_draft(self):
        p = replace(self.make_preview(), draft=DRAFT+'변조')
        with self.assertRaises(ReaderSimulationError):
            annotations_from_episode_preview(p, marks=(FLAGS, FLAGS))

    def test_preview_rejects_scene_digest(self):
        p = self.make_preview()
        p = replace(p, scenes=(replace(p.scenes[0], draft_sha256='f'*64), p.scenes[1]))
        with self.assertRaises(ReaderSimulationError):
            annotations_from_episode_preview(p, marks=(FLAGS, FLAGS))

    def test_preview_rejects_missing_mark(self):
        p = self.make_preview()
        with self.assertRaises(ReaderSimulationError):
            annotations_from_episode_preview(p, marks=(FLAGS,))

    def test_preview_rejects_unknown_mark(self):
        p = self.make_preview()
        with self.assertRaises(ReaderSimulationError):
            annotations_from_episode_preview(p, marks=({**FLAGS, 'unknown': True}, FLAGS))

    def test_preview_rejects_bad_separator(self):
        p = self.make_preview()
        bad = A+'XX'+B
        p = replace(p, draft=bad, draft_sha256=sha256(bad.encode()).hexdigest())
        with self.assertRaises(ReaderSimulationError):
            annotations_from_episode_preview(p, marks=(FLAGS, FLAGS))

    def test_fingerprint_changes_when_marks_change(self):
        r1 = run()
        r2 = run(marks=scenes(second={**FLAGS, 'character_choice': False}))
        self.assertEqual(r1.draft_sha256, r2.draft_sha256)
        self.assertNotEqual(r1.annotation_sha256, r2.annotation_sha256)

    def test_no_network_or_model_call_required(self):
        self.assertEqual(run().profiles[0].profile, 'momentum')


if __name__ == '__main__':
    unittest.main()
