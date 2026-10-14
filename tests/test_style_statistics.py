"""Stage 29 deterministic style measurements and regression constraints."""
from __future__ import annotations

from dataclasses import asdict, FrozenInstanceError
import unittest

from ai_novel_factory.references import (
    MAX_STYLE_TEXT_CHARS, MAX_STYLE_TOKENS, ReferenceParseError,
    analyze_style_text, analyze_reference_style, measure_reference,
    measure_dialogue_reference, parse_text, split_episodes,
)
from ai_novel_factory.references.style_statistics import _length_summary


class TextStyleTests(unittest.TestCase):
    def test_empty_text_is_zero_safe(self):
        m = analyze_style_text('').metrics
        self.assertEqual((m.paragraphs, m.sentences, m.words, m.analyzed_tokens), (0, 0, 0, 0))
        self.assertEqual((m.type_token_ratio, m.repetition_ratio, m.dialogue_ratio), (0.0, 0.0, 0.0))
        self.assertEqual(m.sentence_length.p90, 0)
        self.assertEqual(m.paragraph_length.standard_deviation, 0.0)

    def test_only_whitespace_is_zero(self):
        m = analyze_style_text('\n \t \r\n').metrics
        self.assertEqual(m.paragraphs, 0)
        self.assertEqual(m.scripts.hangul, 0)

    def test_sentence_punctuation_and_final_fragment(self):
        m = analyze_style_text('안녕. 반가워! 아직').metrics
        self.assertEqual(m.sentences, 3)
        self.assertEqual(m.sentence_length.count, 3)

    def test_sentence_closing_quotes(self):
        m = analyze_style_text('그는 “왔다.” 말했다.').metrics
        self.assertEqual(m.sentences, 2)

    def test_multiple_marks_one_sentence(self):
        m = analyze_style_text('왜?! 정말?!').metrics
        self.assertEqual(m.sentences, 2)
        self.assertEqual(m.punctuation.question, 2)
        self.assertEqual(m.punctuation.exclamation, 2)

    def test_no_punctuation_one_sentence(self):
        m = analyze_style_text('아주 조용한 세상').metrics
        self.assertEqual(m.sentences, 1)

    def test_paragraphs_with_newlines(self):
        a = analyze_style_text('하나\r\n\r\n둘\r\n\r\n셋').metrics
        b = analyze_style_text('하나\n\n둘\n\n셋').metrics
        self.assertEqual(a, b)
        self.assertEqual(a.paragraphs, 3)

    def test_length_distribution_single(self):
        m = analyze_style_text('가나다.').metrics
        s = m.sentence_length
        self.assertEqual((s.count, s.minimum, s.maximum, s.mean, s.median, s.p90,
                          s.standard_deviation), (1, 4, 4, 4.0, 4, 4, 0.0))

    def test_length_summary_even_median(self):
        s = _length_summary([1, 4])
        self.assertEqual((s.mean, s.median, s.p90, s.standard_deviation), (2.5, 2.5, 4, 1.5))

    def test_length_summary_nearest_rank_n10(self):
        s = _length_summary(list(range(1, 11)))
        self.assertEqual(s.p90, 9)
        self.assertEqual(s.median, 5.5)

    def test_length_summary_unsorted(self):
        self.assertEqual(_length_summary([3, 1, 2]), _length_summary([1, 2, 3]))

    def test_paragraph_length_distribution(self):
        m = analyze_style_text('가.\n\n가나다.').metrics
        self.assertEqual(m.paragraph_length.count, 2)
        self.assertEqual((m.paragraph_length.minimum, m.paragraph_length.maximum), (2, 4))
        self.assertEqual(m.paragraph_length.mean, 3.0)

    def test_no_split_on_internal_newline(self):
        m = analyze_style_text('첫줄\n둘째줄').metrics
        self.assertEqual(m.paragraphs, 1)
        self.assertEqual(m.sentences, 1)

    def test_casefold_and_terminal_punctuation_normalized(self):
        m = analyze_style_text('Hello, hello! HELLO?').metrics
        self.assertEqual((m.words, m.analyzed_tokens, m.unique_tokens), (3, 3, 1))
        self.assertEqual(m.type_token_ratio, 0.3333)
        self.assertEqual(m.repeated_token_occurrences, 2)
        self.assertEqual(m.repetition_ratio, 0.6667)

    def test_korean_whitespace_tokens_not_morphemes(self):
        m = analyze_style_text('사람이 사람을 사람은').metrics
        self.assertEqual(m.unique_tokens, 3)
        self.assertEqual(m.words, 3)

    def test_punctuation_only_tokens_are_ignored_for_vocabulary(self):
        m = analyze_style_text('!!! ... ???').metrics
        self.assertEqual(m.words, 3)
        self.assertEqual(m.analyzed_tokens, 0)
        self.assertEqual(m.unique_tokens, 0)
        self.assertEqual(m.repetition_ratio, 0.0)

    def test_punctuation_is_not_double_counted_for_ellipsis(self):
        p = analyze_style_text('... …… ... . ..').metrics.punctuation
        self.assertEqual(p.ellipsis, 3)
        self.assertEqual(p.period, 3)  # lone dot plus two-dot group

    def test_punctuation_fullwidth(self):
        p = analyze_style_text('예。 왜？ 그래！ ,， ：: ；;').metrics.punctuation
        self.assertEqual((p.period, p.question, p.exclamation), (1, 1, 1))
        self.assertEqual((p.comma, p.colon, p.semicolon), (2, 2, 2))

    def test_nonwhite_character_script_partition(self):
        m = analyze_style_text('가aZ09!?中').metrics
        self.assertEqual((m.scripts.hangul, m.scripts.ascii_latin,
                          m.scripts.digits, m.scripts.other), (1, 2, 2, 3))
        self.assertEqual(sum(asdict(m.scripts).values()), m.characters_no_whitespace)

    def test_hangul_jamo(self):
        m = analyze_style_text('ᄀㄱ각').metrics
        self.assertEqual(m.scripts.hangul, 3)

    def test_unicode_decimal_digits(self):
        m = analyze_style_text('١２').metrics
        self.assertEqual(m.scripts.digits, 2)

    def test_accented_letters_are_documented_other(self):
        m = analyze_style_text('é').metrics
        self.assertEqual(m.scripts.other, 1)

    def test_whitespace_does_not_count_as_script(self):
        m = analyze_style_text('가 \n나 \t다').metrics
        self.assertEqual(m.scripts.hangul, 3)
        self.assertEqual(m.characters_no_whitespace, 3)

    def test_dialogue_ratio_crosschecked(self):
        text = '“안녕!” 인사했다.\n\n그가 걸었다.'
        m = analyze_style_text(text).metrics
        from ai_novel_factory.references import measure_dialogue_text
        self.assertEqual(m.dialogue_ratio, measure_dialogue_text(text).dialogue_ratio)

    def test_custom_episode_number(self):
        self.assertEqual(analyze_style_text('안녕', number=987).number, 987)

    def test_invalid_number(self):
        for value in (0, -1, 10001, True, 1.0, '1', None):
            with self.subTest(value=value), self.assertRaises(ReferenceParseError):
                analyze_style_text('안녕', number=value)

    def test_invalid_token_budget(self):
        for value in (0, -1, MAX_STYLE_TOKENS + 1, True, '2', 2.5, None):
            with self.subTest(value=value), self.assertRaises(ReferenceParseError):
                analyze_style_text('안녕', max_tokens=value)

    def test_boundary_budget_exact(self):
        m = analyze_style_text('하나 둘', max_tokens=2).metrics
        self.assertEqual(m.words, 2)

    def test_budget_overflow(self):
        with self.assertRaises(ReferenceParseError):
            analyze_style_text('하나 둘 셋', max_tokens=2)

    def test_invalid_text_type(self):
        for value in (None, b'abc', [], {}, 23, 2.5):
            with self.subTest(value=type(value)), self.assertRaises(ReferenceParseError):
                analyze_style_text(value)

    def test_text_length_limit(self):
        with self.assertRaises(ReferenceParseError):
            analyze_style_text('가' * (MAX_STYLE_TEXT_CHARS + 1))

    def test_deterministic_results(self):
        text = '행복했다.\n\n그녀는 “안녕!” 말했다.'
        self.assertEqual(analyze_style_text(text), analyze_style_text(text))

    def test_results_are_frozen(self):
        result = analyze_style_text('반갑다.')
        with self.assertRaises(FrozenInstanceError):
            result.metrics.paragraphs = 100
        with self.assertRaises(FrozenInstanceError):
            result.number = 2

    def test_no_source_in_result_or_serialization(self):
        secret = '아무도모르는비밀번호ABC123가나다'
        result = analyze_style_text(secret + ' ' + secret)
        self.assertNotIn(secret, repr(result))
        self.assertNotIn(secret, str(asdict(result)))
        self.assertEqual(result.metrics.unique_tokens, 1)

    def test_no_external_io_in_text_analyzer(self):
        import unittest.mock as mock
        with mock.patch('builtins.open', side_effect=AssertionError('unexpected file')):
            self.assertEqual(analyze_style_text('반갑다.').metrics.sentences, 1)


class ReferenceStyleTests(unittest.TestCase):
    def test_two_episodes_and_preface(self):
        document = parse_text('서문입니다.\n\n1화\n\n안녕.\n\n2화\n\n안녕. 다른 이야기.')
        r = analyze_reference_style(document)
        self.assertEqual(r.episode_count, 2)
        self.assertEqual([e.number for e in r.episodes], [1, 2])
        self.assertEqual(r.preface.paragraphs, 1)
        self.assertEqual(r.total.paragraphs, 3)
        self.assertEqual(r.total.words, 5)

    def test_whole_reference_vocabulary_not_mean_of_episodes(self):
        document = parse_text('1화\n\n단어.\n\n2화\n\n단어.')
        r = analyze_reference_style(document)
        self.assertEqual(r.total.unique_tokens, 1)
        self.assertEqual(r.total.repeated_token_occurrences, 1)
        self.assertEqual([e.metrics.unique_tokens for e in r.episodes], [1, 1])

    def test_markdown_heading_and_code_ignored(self):
        doc = parse_text('## 1화\n\n# EXCLUDEDHEADERWORD\n\n가나다.\n\n```\nSECRET_CODE_WORD\n```', format='markdown')
        r = analyze_reference_style(doc)
        self.assertEqual(r.total.words, 1)
        self.assertEqual(r.total.paragraphs, 1)
        self.assertEqual(r.total.scripts.ascii_latin, 0)

    def test_preface_and_headings_not_part_of_episode(self):
        doc = parse_text('PREFACEWORD.\n\n1화\n\n한 문장.')
        r = analyze_reference_style(doc)
        self.assertEqual(r.episodes[0].metrics.scripts.ascii_latin, 0)
        self.assertGreater(r.preface.scripts.ascii_latin, 0)

    def test_no_explicit_markers_one_episode(self):
        doc = parse_text('안녕.\n\n만나서 반가워.')
        r = analyze_reference_style(doc)
        self.assertEqual(r.episode_count, 1)
        self.assertEqual(r.preface.paragraphs, 0)
        self.assertEqual(r.total, r.episodes[0].metrics)

    def test_splits_with_nonconsecutive_numbers(self):
        doc = parse_text('5화\n\n여기.\n\n7화\n\n저기.')
        r = analyze_reference_style(doc)
        self.assertEqual([ep.number for ep in r.episodes], [5, 7])

    def test_explicit_matching_split(self):
        doc = parse_text('1화\n\n첫째.\n\n2화\n\n둘째.')
        self.assertEqual(analyze_reference_style(doc),
                         analyze_reference_style(doc, split=split_episodes(doc)))

    def test_wrong_document_split_rejected(self):
        a = parse_text('1화\n\n첫째.')
        b = parse_text('1화\n\n둘째.')
        with self.assertRaises(ReferenceParseError):
            analyze_reference_style(b, split=split_episodes(a))

    def test_invalid_reference_type(self):
        for value in (None, '글', 7):
            with self.subTest(type=type(value)), self.assertRaises(ReferenceParseError):
                analyze_reference_style(value)

    def test_invalid_reference_budget(self):
        doc = parse_text('안녕.')
        for value in (0, -1, True, '1', MAX_STYLE_TOKENS + 1):
            with self.subTest(value=value), self.assertRaises(ReferenceParseError):
                analyze_reference_style(doc, max_tokens=value)

    def test_budget_includes_preface(self):
        doc = parse_text('서문 단어\n\n1화\n\n본문 단어')
        with self.assertRaises(ReferenceParseError):
            analyze_reference_style(doc, max_tokens=3)
        self.assertEqual(analyze_reference_style(doc, max_tokens=4).total.words, 4)

    def test_reference_length_cap(self):
        # Use an in-memory already parsed source, bypassing normal file 16MB cap.
        from ai_novel_factory.references.plaintext_parser import ParsedReference
        doc = ParsedReference('txt', None, '가' * (MAX_STYLE_TEXT_CHARS + 1), ())
        with self.assertRaises(ReferenceParseError):
            analyze_reference_style(doc)

    def test_reference_metrics_agree_with_stages_18_and_21(self):
        doc = parse_text('서문.\n\n1화\n\n“안녕!” 인사했다.\n\n2화\n\n그는 갔다.')
        style = analyze_reference_style(doc)
        baseline = measure_reference(doc)
        dialogue = measure_dialogue_reference(doc)
        self.assertEqual(style.total.words, baseline.total.words)
        self.assertEqual(style.total.sentences, baseline.total.sentences)
        self.assertEqual(style.total.characters_no_whitespace,
                         baseline.total.characters_no_whitespace)
        self.assertEqual(style.total.dialogue_ratio, dialogue.total.dialogue_ratio)
        for i, ep in enumerate(style.episodes):
            self.assertEqual(ep.metrics.words, baseline.episodes[i].statistics.words)
            self.assertEqual(ep.metrics.dialogue_ratio, dialogue.episodes[i].counts.dialogue_ratio)

    def test_metrics_partition_characters_and_paragraphs(self):
        doc = parse_text('시작.\n\n1화\n\n한 문단.\n\n다음.\n\n2화\n\n끝.')
        result = analyze_reference_style(doc)
        self.assertEqual(result.total.characters_no_whitespace,
                         result.preface.characters_no_whitespace +
                         sum(e.metrics.characters_no_whitespace for e in result.episodes))
        self.assertEqual(result.total.paragraphs,
                         result.preface.paragraphs + sum(e.metrics.paragraphs for e in result.episodes))
        self.assertEqual(result.total.sentences,
                         result.preface.sentences + sum(e.metrics.sentences for e in result.episodes))

    def test_script_counts_partition_across_episodes(self):
        doc = parse_text('1화\n\n가abc1?\n\n2화\n\n나다2!')
        r = analyze_reference_style(doc)
        self.assertEqual(sum(asdict(r.total.scripts).values()), r.total.characters_no_whitespace)

    def test_only_heading_document_zero_metrics(self):
        doc = parse_text('# 제목', format='markdown')
        r = analyze_reference_style(doc)
        self.assertEqual(r.total.words, 0)
        self.assertEqual(r.total.paragraphs, 0)

    def test_repeatability_across_references(self):
        doc = parse_text('1화\n\n하나 둘.\n\n2화\n\n셋 넷.')
        self.assertEqual(analyze_reference_style(doc), analyze_reference_style(doc))

    def test_no_original_source_in_reference_output(self):
        secret = '특별한임의기밀문구찾을수없음'
        doc = parse_text('1화\n\n' + secret)
        style = analyze_reference_style(doc)
        self.assertNotIn(secret, repr(style))
        self.assertNotIn(secret, str(asdict(style)))

    def test_empty_chapter_metrics_are_zero(self):
        doc = parse_text('1화\n\n2화\n\n끝.')
        r = analyze_reference_style(doc)
        self.assertEqual(r.episodes[0].metrics.words, 0)
        self.assertEqual(r.episodes[0].metrics.sentences, 0)
        self.assertEqual(r.episodes[1].metrics.words, 1)

    def test_public_exports_present(self):
        from ai_novel_factory.references import ReferenceStyle, StyleMetrics, LengthSummary
        self.assertTrue(ReferenceStyle)
        self.assertTrue(StyleMetrics)
        self.assertTrue(LengthSummary)


if __name__ == '__main__':
    unittest.main()
