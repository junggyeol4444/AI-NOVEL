"""Stage 77: offline repetition frequency, evidence integrity, bounded coverage."""
from dataclasses import replace
from hashlib import sha256
import unittest

from ai_novel_factory.episode_assembler import EpisodeDraftPreview, SceneSpan
from ai_novel_factory.repetition_checker import (
    RepetitionCheckerError, RepetitionPolicy, WatchedPhrase,
    check_repetition, check_episode_repetition,
)

PID = 'a' * 32


def check(text, **kwargs):
    return check_repetition(PID, 7, text, **kwargs)


class RepetitionCheckerTests(unittest.TestCase):
    def test_watched_phrase_over_limit(self):
        text = '그는 고개를 끄덕였다. 다시 고개를 끄덕였다. 그리고 고개를 끄덕였다.'
        r = check(text, watched_phrases=(WatchedPhrase('nod', '고개를 끄덕였다', 2),))
        f = next(x for x in r.findings if x.code == 'WATCHED_PHRASE_OVERUSED')
        self.assertEqual(f.count, 3)
        self.assertEqual(f.allowed_occurrences, 2)
        self.assertEqual(f.watched_key, 'nod')
        self.assertEqual(len(f.spans), 3)
        for span in f.spans:
            self.assertEqual(text[span.start:span.end], '고개를 끄덕였다')
            self.assertEqual(span.evidence_sha256, sha256('고개를 끄덕였다'.encode()).hexdigest())
        self.assertNotIn('고개를 끄덕였다', repr(r))
        self.assertFalse(r.persisted)
        self.assertFalse(r.publication_approved)
        self.assertIn('NOT_FULL_QC', r.status)

    def test_watched_exact_limit_not_violation(self):
        r = check('별빛 별빛 별빛', watched_phrases=(WatchedPhrase('star', '별빛', 3),))
        self.assertFalse(any(f.code == 'WATCHED_PHRASE_OVERUSED' for f in r.findings))

    def test_watched_zero_limit(self):
        r = check('금지 표현.', watched_phrases=(WatchedPhrase('ban', '금지', 0),))
        self.assertEqual(r.findings[0].count, 1)

    def test_watched_case_sensitive(self):
        r = check('Moon moon MOON', watched_phrases=(WatchedPhrase('moon', 'moon', 1),))
        self.assertFalse(r.findings)

    def test_watched_case_insensitive(self):
        r = check('Moon moon MOON', watched_phrases=(WatchedPhrase('moon', 'moon', 1, False),))
        self.assertEqual(r.findings[0].count, 3)

    def test_watched_casefold_expansion_rejected(self):
        with self.assertRaises(RepetitionCheckerError):
            check('Straße', watched_phrases=(WatchedPhrase('strasse', 'strasse', 0, False),))

    def test_watched_literal_nonoverlapping(self):
        r = check('aaaa', watched_phrases=(WatchedPhrase('aa', 'aa', 1),))
        f = r.findings[0]
        self.assertEqual([(s.start, s.end) for s in f.spans], [(0, 2), (2, 4)])

    def test_automatic_phrase_detected(self):
        text = '푸른 바람 속에. 푸른 바람 옆에. 푸른 바람 뒤에. 푸른 바람 아래.'
        r = check(text)
        self.assertTrue(any(f.code == 'REPEATED_PHRASE' and f.count == 4 for f in r.findings))

    def test_automatic_phrase_below_threshold(self):
        r = check('푸른 바람 속에. 푸른 바람 뒤에.')
        self.assertFalse(any(f.code == 'REPEATED_PHRASE' for f in r.findings))

    def test_automatic_phrase_does_not_cross_sentences(self):
        r = check('저녁에 빛난다. 별빛이 스친다. 저녁에 빛난다. 별빛이 스친다.')
        self.assertFalse(any(f.code == 'REPEATED_PHRASE' and f.count == 4 for f in r.findings))

    def test_auto_phrase_custom_limit(self):
        text = '푸른 바람 속에. 푸른 바람 옆에. 푸른 바람 뒤에.'
        r = check(text, policy=RepetitionPolicy(max_auto_phrase_occurrences=2))
        self.assertTrue(any(f.code == 'REPEATED_PHRASE' for f in r.findings))

    def test_auto_phrase_word_minimum(self):
        r = check('별빛. 별빛. 별빛. 별빛.')
        self.assertFalse(any(f.code == 'REPEATED_PHRASE' for f in r.findings))

    def test_exact_sentence_whitespace_punctuation_case_normalized(self):
        r = check('The blue sky was clear.\nThe BLUE sky was clear!')
        f = next(x for x in r.findings if x.code == 'REPEATED_SENTENCE')
        self.assertEqual(f.count, 2)
        self.assertEqual([(s.start, s.end) for s in f.spans], [(0, 23), (24, 47)])

    def test_exact_sentence_distant_occurrences(self):
        text = '별빛은 어두운 강 위에 내려앉았다.\n다른 장면이 멀리 지나간다.\n별빛은 어두운 강 위에 내려앉았다.'
        r = check(text)
        self.assertEqual(len([f for f in r.findings if f.code == 'REPEATED_SENTENCE']), 1)

    def test_short_sentences_not_falsely_flagged(self):
        r = check('네. 네. 네. 네.')
        self.assertFalse(any(f.code in ('REPEATED_SENTENCE', 'SIMILAR_SENTENCE') for f in r.findings))

    def test_near_duplicate_sentence(self):
        text = '그는 어두운 강을 천천히 걸어서 건넜다.\n그는 어두운 강을 천천히 걸어 건넜다.'
        r = check(text)
        f = next(x for x in r.findings if x.code == 'SIMILAR_SENTENCE')
        self.assertGreaterEqual(f.similarity, 0.88)
        self.assertEqual(f.count, 2)
        self.assertEqual(len(f.spans), 2)

    def test_unrelated_sentences_not_similar(self):
        r = check('어두운 숲의 바람이 잦아들었다.\n밝은 도시의 사람들이 축제를 열었다.')
        self.assertFalse(any(f.code == 'SIMILAR_SENTENCE' for f in r.findings))

    def test_identical_sentences_not_double_counted_as_similar(self):
        r = check('그는 어두운 강을 천천히 건넜다.\n그는 어두운 강을 천천히 건넜다.')
        self.assertEqual(len([f for f in r.findings if f.code == 'REPEATED_SENTENCE']), 1)
        self.assertFalse(any(f.code == 'SIMILAR_SENTENCE' for f in r.findings))

    def test_newlines_and_korean_punctuation(self):
        r = check('그는 멀리 떠나기로 했다。\n그는 멀리 떠나기로 했다！')
        self.assertTrue(any(f.code == 'REPEATED_SENTENCE' for f in r.findings))

    def test_invalid_manuscript(self):
        for value in ('', ' ', '\x00', '\ud800', None, 4, 'a' * 1_000_001):
            with self.subTest(value=repr(value)[:20]), self.assertRaises(RepetitionCheckerError):
                check(value)

    def test_invalid_project_episode(self):
        for pid in ('x', '../foo', None, 'a' * 31):
            with self.subTest(pid=pid), self.assertRaises(RepetitionCheckerError):
                check_repetition(pid, 1, '본문.')
        for ep in (0, True, 1.5, 1_000_001):
            with self.subTest(ep=ep), self.assertRaises(RepetitionCheckerError):
                check_repetition(PID, ep, '본문.')

    def test_invalid_watched_phrase(self):
        bad = (WatchedPhrase('bad key', 'x'), WatchedPhrase('key', ''),
               WatchedPhrase('key', 'a\nb'), WatchedPhrase('key', 'x', -1),
               WatchedPhrase('key', 'x', True), WatchedPhrase('key', 'x', 1, 1))
        for spec in bad:
            with self.subTest(spec=repr(spec)[:40]), self.assertRaises(RepetitionCheckerError):
                check('본문.', watched_phrases=(spec,))
        with self.assertRaises(RepetitionCheckerError):
            check('본문.', watched_phrases=(WatchedPhrase('a', 'a'), WatchedPhrase('a', 'b')))
        with self.assertRaises(RepetitionCheckerError):
            check('본문.', watched_phrases=[WatchedPhrase('a', 'a')])

    def test_invalid_policy(self):
        bad = (RepetitionPolicy(max_auto_phrase_occurrences=0),
               RepetitionPolicy(min_phrase_words=4, max_phrase_words=2),
               RepetitionPolicy(min_sentence_chars=True),
               RepetitionPolicy(sentence_similarity_threshold=float('nan')),
               RepetitionPolicy(sentence_similarity_threshold=0.2))
        for policy in bad:
            with self.subTest(policy=repr(policy)), self.assertRaises(RepetitionCheckerError):
                check('본문.', policy=policy)

    def test_reports_have_only_hashes_not_manuscript(self):
        text = '바람은 창문을 천천히 두드렸다.\n바람은 창문을 천천히 두드렸다.'
        r = check(text)
        self.assertEqual(r.manuscript_sha256, sha256(text.encode()).hexdigest())
        self.assertNotIn('창문을', repr(r))

    def test_no_findings_is_not_general_quality_approval(self):
        r = check('짧은 첫 문장. 다음은 전혀 다른 내용이다.')
        self.assertTrue(r.passed_checked_scope)
        self.assertEqual(r.status, 'REQUIRES_HUMAN_REVIEW_NOT_FULL_QC')
        self.assertFalse(r.publication_approved)

    def test_automatic_token_budget_reported(self):
        r = check(('짧은 단어 여러 개. ' * 20000))
        self.assertIn('automatic_phrase_token_budget_exceeded', r.unexamined)
        self.assertFalse(r.passed_checked_scope)

    def test_many_unique_sentences_budget_reported(self):
        text = '\n'.join('서로 다른 이야기를 전하는 문장 번호 %d.' % i for i in range(3100))
        r = check(text)
        self.assertIn('fuzzy_sentence_count_budget_exceeded', r.unexamined)

    def test_repetition_span_count_truncated_explicitly(self):
        r = check('반복' * 1100, watched_phrases=(WatchedPhrase('repeat', '반복', 3),))
        self.assertEqual(r.findings[0].count, 1100)
        self.assertEqual(len(r.findings[0].spans), 1000)
        self.assertIn('occurrence_offsets_truncated', r.unexamined)

    def test_findings_capacity_fails_closed(self):
        text = '\n'.join('반복 문구 %d 반복 문구 %d 반복 문구 %d 반복 문구 %d.' % (i, i, i, i)
                         for i in range(1200))
        # No unconditional claim of completeness on extreme repetition.
        # Either a bounded report or explicit rejection is acceptable.
        try:
            r = check(text, policy=RepetitionPolicy(max_auto_phrase_occurrences=1))
        except RepetitionCheckerError:
            return
        self.assertLessEqual(len(r.findings), 1000)

    def _preview(self):
        a, b = '별빛은 창문에 내려앉았다.', '별빛은 창문에 내려앉았다.'
        text = a + '\n\n' + b
        h = lambda s: sha256(s.encode()).hexdigest()
        spans = (SceneSpan(1, 0, len(a), h(a), h('prompt1'), ('fact',)),
                 SceneSpan(2, len(a) + 2, len(text), h(b), h('prompt2'), ('fact',)))
        return EpisodeDraftPreview(PID, 7, text, h(text), spans, ('fact',),
                                   'offline-mock-v1', 'DETERMINISTIC_MOCK_NOT_AI')

    def test_episode_preview_integration(self):
        r = check_episode_repetition(self._preview())
        self.assertTrue(any(f.code == 'REPEATED_SENTENCE' for f in r.findings))
        self.assertFalse(r.persisted)

    def test_tampered_preview_rejected(self):
        p = self._preview()
        for altered in (replace(p, draft=p.draft + '변조'),
                        replace(p, status='APPROVED'),
                        replace(p, persisted=True),
                        replace(p, publication_approved=True),
                        replace(p, scenes=()),
                        replace(p, scenes=(replace(p.scenes[0], end=5), p.scenes[1])),
                        replace(p, scenes=(p.scenes[0], replace(p.scenes[1], draft_sha256='0' * 64)))):
            with self.subTest(altered=repr(altered)[:40]), self.assertRaises(RepetitionCheckerError):
                check_episode_repetition(altered)

    def test_no_file_or_database_write(self):
        self.assertFalse(check('짧은 원고.').persisted)


class LargeInputSafetyTests(unittest.TestCase):
    def test_watched_very_many_matches_bounded_offsets(self):
        r = check('x' * 20000, watched_phrases=(WatchedPhrase('x', 'x', 0),))
        f = next(f for f in r.findings if f.code == 'WATCHED_PHRASE_OVERUSED')
        self.assertEqual(f.count, 20000)
        self.assertEqual(len(f.spans), 1000)
        self.assertIn('occurrence_offsets_truncated', r.unexamined)

    def test_long_sentence_fuzzy_unexamined(self):
        r = check(('한글' * 300) + '.\n' + ('한글' * 299) + '나.')
        self.assertIn('fuzzy_sentence_length_budget_exceeded', r.unexamined)
        self.assertFalse(r.passed_checked_scope)


if __name__ == '__main__':
    unittest.main()
