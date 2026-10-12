"""Step 22: episode structure evidence, privacy and integration regression tests."""
import dataclasses
import unittest

from ai_novel_factory.references import (
    ParsedBlock, ParsedReference, ReferenceParseError, analyze_reference_structure,
    analyze_structure_text, measure_dialogue_reference, measure_reference,
    parse_text, split_episodes,
)


class TextStructureTests(unittest.TestCase):
    def test_three_paragraphs_each_section(self):
        r = analyze_structure_text("문이 열렸다.\n\n갈등이 시작됐다.\n\n마침내 해결했다?")
        self.assertEqual((r.opening.paragraphs, r.middle.paragraphs,
                          r.ending.paragraphs), (1, 1, 1))
        self.assertEqual(r.paragraphs, 3)

    def test_six_paragraphs_two_each(self):
        r = analyze_structure_text("\n\n".join("일." for _ in range(6)))
        self.assertEqual((r.opening.paragraphs, r.middle.paragraphs,
                          r.ending.paragraphs), (2, 2, 2))

    def test_five_paragraphs_distribution(self):
        r = analyze_structure_text("\n\n".join(str(n) for n in range(5)))
        self.assertEqual((r.opening.paragraphs, r.middle.paragraphs,
                          r.ending.paragraphs), (2, 2, 1))

    def test_single_paragraph_treated_as_ending(self):
        r = analyze_structure_text("누구냐?")
        self.assertEqual((r.opening.paragraphs, r.middle.paragraphs,
                          r.ending.paragraphs), (0, 0, 1))
        self.assertEqual(r.ending_hook, "question")

    def test_two_paragraphs_opening_and_ending(self):
        r = analyze_structure_text("시작했다.\n\n끝났다!")
        self.assertEqual((r.opening.paragraphs, r.middle.paragraphs,
                          r.ending.paragraphs), (1, 0, 1))

    def test_ending_question_in_quotes(self):
        for ending in ('“무슨 일이야?”', '「누구세요？」', '이유는?'):
            with self.subTest(ending=ending):
                self.assertEqual(analyze_structure_text(ending).ending_hook, "question")

    def test_ending_ellipsis(self):
        for ending in ('말을 잇지 못했다…', '아직도...', '“아직…”'):
            with self.subTest(ending=ending):
                self.assertEqual(analyze_structure_text(ending).ending_hook, "ellipsis")

    def test_ending_exclamation(self):
        self.assertEqual(analyze_structure_text('“위험해!”').ending_hook, "exclamation")

    def test_plain_ending_no_hook(self):
        r = analyze_structure_text('무사히 집에 돌아왔다.')
        self.assertEqual(r.ending_hook, "none")
        self.assertFalse(r.possible_hook)

    def test_question_is_candidate_not_guaranteed_cliffhanger(self):
        r = analyze_structure_text('오늘 점심 뭐 먹지?')
        self.assertTrue(r.possible_hook)
        self.assertNotIn('confirmed', repr(r))

    def test_conflict_keyword_boundary(self):
        r = analyze_structure_text('하지만 상황은 달랐다. 그러나 그는 웃었다.')
        self.assertEqual(r.ending.cues.conflict, 2)
        self.assertEqual(r.ending.cues.reversal, 0)

    def test_progression_and_payoff_keywords(self):
        r = analyze_structure_text('그리고 걸었다. 결국 성공!')
        self.assertEqual(r.ending.cues.progression, 1)
        self.assertEqual(r.ending.cues.payoff, 2)

    def test_inflected_keyword_is_not_counted(self):
        # This version counts token-matched cue terms, not morphological roots.
        r = analyze_structure_text('성공했다. 위험해졌다.')
        self.assertEqual((r.ending.cues.payoff, r.ending.cues.conflict), (0, 0))

    def test_reversal_keywords(self):
        r = analyze_structure_text('그런데 알고 보니 사실은 함정이었다.')
        self.assertEqual(r.ending.cues.reversal, 3)

    def test_no_cues_means_zero(self):
        r = analyze_structure_text('나무는 높았다.')
        self.assertEqual(dataclasses.astuple(r.ending.cues), (0, 0, 0, 0))

    def test_dialogue_ratios_per_section(self):
        r = analyze_structure_text('“안녕!”\n\n인물이 걸었다.\n\n“가자!”')
        self.assertEqual((r.opening.dialogue_ratio, r.middle.dialogue_ratio,
                          r.ending.dialogue_ratio), (1.0, 0.0, 1.0))

    def test_preserves_non_whitespace_character_count(self):
        text = '첫 문단.\n\n“둘째 말.”\n\n셋째 끝!'
        r = analyze_structure_text(text)
        self.assertEqual(r.characters_no_whitespace,
                         sum(not c.isspace() for c in text))
        self.assertEqual(r.characters_no_whitespace,
                         sum(x.characters_no_whitespace for x in
                             (r.opening, r.middle, r.ending)))

    def test_empty_is_safe(self):
        r = analyze_structure_text(' \n\n  ')
        self.assertEqual(r.paragraphs, 0)
        self.assertEqual(r.characters_no_whitespace, 0)
        self.assertEqual(r.ending_hook, "none")

    def test_mixed_line_endings(self):
        r = analyze_structure_text('시작\r\n\r\n중간\r\n\r\n끝!')
        self.assertEqual(r.paragraphs, 3)

    def test_number_validation(self):
        for bad in (-1, 0, 10001, True, 3.14, '1'):
            with self.subTest(bad=bad), self.assertRaises(ReferenceParseError):
                analyze_structure_text('text', number=bad)

    def test_rejects_wrong_text_type(self):
        with self.assertRaises(ReferenceParseError):
            analyze_structure_text(None)

    def test_immutable_no_raw_text_repr(self):
        r = analyze_structure_text('비공개 원고의 중요한 비밀.\n\n반전!')
        self.assertNotIn('비공개', repr(r))
        self.assertNotIn('비밀', str(r))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.ending_hook = 'none'

    def test_deterministic(self):
        text = '처음에는 평온했다.\n\n하지만 위험이 찾아왔다.\n\n어떻게 될까?'
        self.assertEqual(analyze_structure_text(text), analyze_structure_text(text))


class ReferenceStructureTests(unittest.TestCase):
    def test_two_episodes_and_preface(self):
        d = parse_text('소설 안내\n\n1화\n\n시작.\n\n“하지만 위험해!”\n\n2화\n\n끝났다?')
        result = analyze_reference_structure(d)
        self.assertEqual([e.number for e in result.episodes], [1, 2])
        self.assertEqual(result.preface_characters, len('소설안내'))
        self.assertEqual(result.episodes[0].ending.cues.conflict, 1)
        self.assertEqual(result.episodes[1].ending_hook, 'question')
        self.assertEqual(result.episode_count, 2)
        self.assertEqual(result.total_body_characters,
                         measure_reference(d).total.characters_no_whitespace)

    def test_unmarked_single_episode(self):
        d = parse_text('문장이 하나.\n\n문장이 둘!')
        result = analyze_reference_structure(d)
        self.assertEqual(result.episode_count, 1)
        self.assertEqual(result.preface_characters, 0)
        self.assertEqual(result.episodes[0].number, 1)

    def test_markdown_headings_and_code_excluded(self):
        d = parse_text('# 제목\n\n## 1화\n\n시작.\n\n```\n하지만 반전!\n```\n\n끝.',
                       format='markdown')
        r = analyze_reference_structure(d)
        self.assertEqual(r.episodes[0].ending.cues.conflict, 0)
        self.assertEqual(r.episodes[0].ending.cues.reversal, 0)
        self.assertEqual(r.total_body_characters,
                         measure_reference(d).total.characters_no_whitespace)

    def test_docx_pdf_table_consistency(self):
        for fmt in ('docx', 'pdf'):
            with self.subTest(format=fmt):
                d = ParsedReference(fmt, None, '', (
                    ParsedBlock('heading', 1, 1, '1화', 1),
                    ParsedBlock('paragraph', 2, 2, '그가 걸었다.'),
                    ParsedBlock('table', 3, 3, '“안녕!”\t그리고 잠시'),
                ))
                result = analyze_reference_structure(d)
                self.assertEqual(result.episodes[0].characters_no_whitespace,
                                 measure_dialogue_reference(d).episodes[0].counts.total_characters)

    def test_stale_split_rejected(self):
        doc = parse_text('1화\n\n일이 벌어졌다.')
        split = split_episodes(parse_text('1화\n\n전혀 다른 문장!'))
        with self.assertRaises(ReferenceParseError):
            analyze_reference_structure(doc, split=split)

    def test_wrong_doc_type_rejected(self):
        with self.assertRaises(ReferenceParseError):
            analyze_reference_structure('원고')

    def test_invalid_episode_order_rejected(self):
        doc = parse_text('2화\n\n문장.\n\n1화\n\n문장.')
        with self.assertRaises(ReferenceParseError):
            analyze_reference_structure(doc)

    def test_reference_records_have_no_source_text(self):
        doc = parse_text('1화\n\n비밀 문장이 있다?')
        result = analyze_reference_structure(doc)
        self.assertNotIn('비밀', repr(result))
        self.assertNotIn('문장이 있다', str(result))


if __name__ == '__main__':
    unittest.main()
