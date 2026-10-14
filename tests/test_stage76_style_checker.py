"""Stage 76 — bounded, offline Style Bible rule checks, not automated literary QC."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from ai_novel_factory.database.style_bible import StyleBibleStore
from ai_novel_factory.episode_assembler import EpisodeDraftPreview, SceneSpan
from ai_novel_factory.style_checker import (
    StyleCheckerError, ViewpointClaim, check_style, check_episode_style,
)


class StyleCheckerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = StyleBibleStore(Path(self.temp.name) / 'canon.sqlite')
        self.addCleanup(self.store.close)
        self.pid = self.store.create_project('내 작품').project_id
        self.store.save_rule(self.pid, 'premise', '고유 세계관을 지킨다')
        self.store.save_style_rule(self.pid, 'forbidden_phrase_smile', '피식 웃었다')
        self.manuscript = '그는 피식 웃었다.\n\n대답했다.'

    _DEFAULT = object()

    def inspect(self, manuscript=_DEFAULT, **kwargs):
        return check_style(self.store, self.pid, 2,
                           self.manuscript if manuscript is self._DEFAULT else manuscript, **kwargs)

    def test_forbidden_phrase_offsets_and_fingerprint(self):
        report = self.inspect()
        finding = report.findings[0]
        self.assertEqual(finding.code, 'FORBIDDEN_PHRASE')
        self.assertEqual(finding.rule_key, 'forbidden_phrase_smile')
        self.assertEqual(finding.source, 'style_bible')
        self.assertEqual(self.manuscript[finding.start:finding.end], '피식 웃었다')
        self.assertEqual(finding.evidence_sha256, sha256('피식 웃었다'.encode()).hexdigest())
        self.assertEqual(report.manuscript_sha256, sha256(self.manuscript.encode()).hexdigest())
        self.assertNotIn('피식 웃었다', repr(report))
        self.assertFalse(report.persisted)
        self.assertFalse(report.publication_approved)
        self.assertIn('NOT_FULL_QC', report.status)

    def test_non_overlapping_literal_matches(self):
        r = self.inspect('피식 웃었다 피식 웃었다')
        self.assertEqual([f.start for f in r.findings], [0, 7])

    def test_phrase_is_case_sensitive_literal(self):
        self.assertFalse(self.inspect('그는 피식 웃었다고 했다').passed_checked_rules)
        self.assertTrue(self.inspect('그는 피식 웃는다.').passed_checked_rules)

    def test_novel_bible_override_takes_precedence(self):
        self.store.save_rule(self.pid, 'forbidden_phrase_smile', '대답했다')
        r = self.inspect()
        self.assertEqual(len(r.findings), 1)
        self.assertEqual(r.findings[0].source, 'novel_bible')
        self.assertEqual(self.manuscript[r.findings[0].start:r.findings[0].end], '대답했다')

    def test_sentence_length(self):
        self.store.save_style_rule(self.pid, 'max_sentence_chars', '5')
        r = self.inspect('123456.\n123.')
        self.assertEqual([f.code for f in r.findings], ['SENTENCE_TOO_LONG'])

    def test_paragraph_length(self):
        self.store.save_style_rule(self.pid, 'max_paragraph_chars', '6')
        r = self.inspect('1234567\n\n123')
        self.assertEqual([f.code for f in r.findings], ['PARAGRAPH_TOO_LONG'])

    def test_multiline_paragraph_detection(self):
        self.store.save_style_rule(self.pid, 'max_paragraph_chars', '6')
        r = self.inspect('1234\n5678\n\n123')
        self.assertEqual([f.code for f in r.findings], ['PARAGRAPH_TOO_LONG'])

    def test_novel_bible_length_override(self):
        self.store.save_style_rule(self.pid, 'max_sentence_chars', '5')
        self.store.save_rule(self.pid, 'max_sentence_chars', '30')
        r = self.inspect('123456.')
        self.assertFalse(r.findings)
        self.assertIn('max_sentence_chars', r.applied_rules)

    def test_invalid_numeric_rule_rejected(self):
        for bad in ('0', '-1', '10.2', 'abc', '1000001', ' 3 '):
            with self.subTest(bad=bad):
                self.store.save_style_rule(self.pid, 'max_sentence_chars', bad,
                    expected_revision=(self.store.get_style_rule(self.pid, 'max_sentence_chars').revision
                        if any(x.key == 'max_sentence_chars' for x in self.store.list_style_rules(self.pid)) else None))
                with self.assertRaises(StyleCheckerError):
                    self.inspect('Hi.')

    def test_viewpoint_claim_match(self):
        self.store.save_style_rule(self.pid, 'viewpoint', 'third_person_limited')
        claim = ViewpointClaim(0, 2, self.manuscript[:2], 'third_person_limited')
        r = self.inspect(viewpoint_claims=(claim,))
        self.assertEqual(r.viewpoint_claims_checked, 1)
        self.assertEqual([f.code for f in r.findings], ['FORBIDDEN_PHRASE'])

    def test_viewpoint_mismatch_and_missing_evidence(self):
        self.store.save_style_rule(self.pid, 'viewpoint', 'third_person_limited')
        missing = self.inspect('이야기.')
        self.assertIn('viewpoint_evidence_missing', missing.unexamined_rules)
        claim = ViewpointClaim(0, 2, self.manuscript[:2], 'first_person')
        self.assertIn('VIEWPOINT_CONFLICT', [f.code for f in self.inspect(viewpoint_claims=(claim,)).findings])

    def test_freeform_viewpoint_is_unexamined_not_silently_passed(self):
        self.store.save_style_rule(self.pid, 'viewpoint', '3인칭 제한')
        r = self.inspect('나는 집으로 돌아왔다.')
        self.assertIn('viewpoint', r.unexamined_rules)

    def test_freeform_tone_unexamined(self):
        self.store.save_style_rule(self.pid, 'tone', '빠르고 간결하게')
        r = self.inspect('짧은 문장.')
        self.assertIn('tone', r.unexamined_rules)

    def test_no_executable_rule_marked_unexamined(self):
        self.store.delete_style_rule(self.pid, 'forbidden_phrase_smile', expected_revision=1)
        self.store.save_style_rule(self.pid, 'tone', '잔잔하게')
        r = self.inspect('장면.')
        self.assertIn('no_executable_style_rules', r.unexamined_rules)

    def test_invalid_viewpoint_evidence_and_cross_boundaries(self):
        for c in (ViewpointClaim(0, 2, '다른', 'first_person'),
                  ViewpointClaim(-1, 1, '그', 'first_person'),
                  ViewpointClaim(0, 1, '그', 'wrong'),
                  ViewpointClaim(True, 1, '그', 'first_person')):
            with self.subTest(claim=c), self.assertRaises(StyleCheckerError):
                self.inspect(viewpoint_claims=(c,))

    def test_duplicate_claim_rejected(self):
        c = ViewpointClaim(0, 1, '그', 'first_person')
        with self.assertRaises(StyleCheckerError):
            self.inspect(viewpoint_claims=(c, c))

    def test_cross_project_scope(self):
        pid2 = self.store.create_project('두 번째').project_id
        self.store.save_rule(pid2, 'premise', '다른 세계')
        self.store.save_style_rule(pid2, 'forbidden_phrase_smile', '다른 말')
        r = check_style(self.store, pid2, 1, '피식 웃었다')
        self.assertFalse(r.findings)
        self.assertEqual(r.project_id, pid2)

    def test_stale_project_revision(self):
        old = self.store.get_project(self.pid).revision
        self.store.save_rule(self.pid, 'tone', '차분하게')
        with self.assertRaises(StyleCheckerError):
            self.inspect(expected_project_revision=old)

    def test_bad_project_and_episode(self):
        for project in ('../../', 'other', None):
            with self.subTest(project=project), self.assertRaises(StyleCheckerError):
                check_style(self.store, project, 1, self.manuscript)
        for ep in (0, -1, True, 1.5):
            with self.subTest(ep=ep), self.assertRaises(StyleCheckerError):
                check_style(self.store, self.pid, ep, self.manuscript)

    def test_empty_and_invalid_manuscripts(self):
        for text in ('', '  ', '\x00', '\ud800', None, 7, 'x' * 1_000_001):
            with self.subTest(text=repr(text)[:30]), self.assertRaises(StyleCheckerError):
                self.inspect(text)

    def test_invalid_forbidden_phrase_rule_is_not_silently_ignored(self):
        self.store.save_style_rule(self.pid, 'forbidden_phrase_extra', 'line\nbreak')
        with self.assertRaises(StyleCheckerError):
            self.inspect()

    def test_finding_capacity_fails_closed(self):
        with self.assertRaises(StyleCheckerError):
            self.inspect('피식 웃었다' * 1001)

    def test_missing_canon_or_style(self):
        pid = self.store.create_project('미완성').project_id
        with self.assertRaises(StyleCheckerError):
            check_style(self.store, pid, 1, '문장.')
        self.store.save_rule(pid, 'premise', '설정')
        with self.assertRaises(StyleCheckerError):
            check_style(self.store, pid, 1, '문장.')

    def test_viewpoint_claim_count_limit(self):
        c = ViewpointClaim(0, 1, '그', 'first_person')
        with self.assertRaises(StyleCheckerError):
            self.inspect(viewpoint_claims=(c,) * 501)

    def _preview(self):
        text = '첫 장면.\n\n두 번째 장면.'
        part1, part2 = '첫 장면.', '두 번째 장면.'
        h = lambda s: sha256(s.encode()).hexdigest()
        spans = (SceneSpan(1, 0, len(part1), h(part1), h('prompt1'), ('fact',)),
                 SceneSpan(2, len(part1) + 2, len(text), h(part2), h('prompt2'), ('fact',)))
        return EpisodeDraftPreview(self.pid, 3, text, h(text), spans, ('fact',),
                                   'offline-mock-v1', 'DETERMINISTIC_MOCK_NOT_AI')

    def test_episode_preview_integration(self):
        r = check_episode_style(self.store, self._preview())
        self.assertEqual(r.episode_number, 3)
        self.assertFalse(r.persisted)

    def test_modified_preview_rejected(self):
        p = self._preview()
        for tampered in (replace(p, draft=p.draft + '변조'),
                         replace(p, persisted=True),
                         replace(p, publication_approved=True),
                         replace(p, status='APPROVED'),
                         replace(p, scenes=p.scenes[:-1]),
                         replace(p, scenes=(replace(p.scenes[0], start=1), *p.scenes[1:]))):
            with self.subTest(tampered=repr(tampered)[:80]), self.assertRaises(StyleCheckerError):
                check_episode_style(self.store, tampered)

    def test_no_source_or_db_mutations(self):
        before = self.store.get_project(self.pid).revision
        self.inspect()
        self.assertEqual(self.store.get_project(self.pid).revision, before)
        self.assertEqual(self.store.get_style_rule(self.pid, 'forbidden_phrase_smile').directive,
                         '피식 웃었다')


if __name__ == '__main__':
    unittest.main()
