"""Local heuristic regressions: never interpret as real Windows literary PASS."""
import unittest

from ai_novel_factory.korean_draft_quality import screen_korean_draft


class KoreanDraftScreenTests(unittest.TestCase):
    def test_empty_rejected(self):
        self.assertFalse(screen_korean_draft('').format_gate_pass)

    def test_short_korean_rejected(self):
        self.assertFalse(screen_korean_draft('짧은 장면이다.').format_gate_pass)

    def test_long_repeated_korean_rejected(self):
        q = screen_korean_draft('그녀는 책상 앞에서 진실을 기다렸다. ' * 280)
        self.assertGreater(q.total_chars, 5000)
        self.assertFalse(q.format_gate_pass)
        self.assertGreater(q.repeated_sentence_share, .12)

    def test_numbering_does_not_make_repeated_lines_original(self):
        q = screen_korean_draft(' '.join(
            f'{i}. 그녀는 자료를 검토하고 다시 문을 바라보았다.'
            for i in range(260)))
        self.assertFalse(q.format_gate_pass)
        self.assertGreater(q.repeated_sentence_share, .12)

    def test_english_filler_rejected(self):
        q = screen_korean_draft('An English sentence for a novel. ' * 250)
        self.assertFalse(q.format_gate_pass)
        self.assertLess(q.hangul_share, .78)

    def test_repeated_blocks_without_punctuation(self):
        q = screen_korean_draft('긴세월동안기억을돌아보며서류를읽어가는조사자' * 300)
        self.assertFalse(q.format_gate_pass)
        self.assertGreater(q.repeated_chunk_share, .15)

    def test_translation_and_korean_repetition_rejected(self):
        q = screen_korean_draft('Translation: ' + '자료를 읽고 다시 기록을 찾았다. ' * 350)
        self.assertFalse(q.format_gate_pass)

    def test_invalid_limits_and_types_rejected(self):
        for text, target in ((None, 5000), ('', 0), ('', True),
                             ('', 1_000_001), ('가' * 100001, 5000)):
            with self.subTest(target=target), self.assertRaises(ValueError):
                screen_korean_draft(text, target_chars=target)

    def test_real_windows_qwen_language_and_headings_not_format_approved(self):
        # The CI screenshot/source evidence contained these exact categories:
        # Chinese script '起床', headings '### 첫 장면', and '<사서>:' labels.
        # A format PASS must not be obtained by adding otherwise clean prose.
        base = '\\n'.join(
            '탐사자가 단서를 읽었다. ' + ''.join(
                chr(0xAC00 + (i * 61 + j) % 11172) for j in range(65)) +
            ' 사서는 문을 닫았다.' for i in range(90))
        plain = screen_korean_draft(base)
        self.assertTrue(plain.format_gate_pass)
        self.assertEqual(plain.han_script_chars, 0)
        self.assertEqual(plain.non_prose_markers, 0)
        for contamination in ('起床', '### 첫 장면: 도서관',
                              '**제목: 도서관**', '<사서>: 대답',
                              '---', '안녕하세요, 저는 AI입니다.'):
            with self.subTest(contamination=contamination):
                polluted = screen_korean_draft(base + '\\n' + contamination)
                self.assertFalse(polluted.format_gate_pass)
                self.assertTrue(polluted.han_script_chars or polluted.non_prose_markers)

    def test_metrics_not_literary_certificate(self):
        q = screen_korean_draft('한국어 문장도 부족하다. 다음 장면이 없다.')
        self.assertFalse(q.format_gate_pass)
        self.assertFalse(hasattr(q, 'literary_approved'))
