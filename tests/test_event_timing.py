"""Regression coverage for stage 23 lexical event-candidate locations."""
import dataclasses
import unittest
from ai_novel_factory.references import (
    MAX_EVENT_MARKERS, ParsedBlock, ParsedReference, ReferenceParseError,
    analyze_event_timing_text, analyze_reference_event_timing,
    analyze_structure_text, analyze_reference_structure,
    parse_text, split_episodes,
)


class TextEventTimingTests(unittest.TestCase):
    def test_empty(self):
        r = analyze_event_timing_text(' \n\n ')
        self.assertEqual(r.candidate_count, 0)
        self.assertEqual(r.quintile_counts, (0, 0, 0, 0, 0))
        self.assertIsNone(r.peak_quintile)

    def test_no_cues(self):
        self.assertEqual(analyze_event_timing_text('조용한 날이었다.').candidates, ())

    def test_first_marker(self):
        r = analyze_event_timing_text('하지만\n\n그는 걸었다.')
        self.assertEqual(r.candidate_count, 1)
        m = r.candidates[0]
        self.assertEqual((m.category, m.character_offset, m.position_percent,
                          m.quintile, m.paragraph_number),
                         ('conflict', 0, 0.0, 1, 1))

    def test_marker_offset_ignores_whitespace(self):
        r = analyze_event_timing_text('가나 다라 하지만 마바')
        self.assertEqual(r.candidates[0].character_offset, 4)
        self.assertEqual(r.candidates[0].position_percent,
                         round(4 * 100 / len('가나다라하지만마바'), 2))

    def test_document_order_not_category_order(self):
        r = analyze_event_timing_text('결국 그리고 하지만 그런데')
        self.assertEqual([m.category for m in r.candidates],
                         ['payoff', 'progression', 'conflict', 'reversal'])

    def test_paragraph_offsets(self):
        r = analyze_event_timing_text('가나다.\n\n마바사 하지만')
        self.assertEqual(r.candidates[0].paragraph_number, 2)
        self.assertEqual(r.candidates[0].character_offset, len('가나다.마바사'))

    def test_whitespace_variants(self):
        a = analyze_event_timing_text('가 나 다 하지만')
        b = analyze_event_timing_text('가\t나  다\n하지만')
        self.assertEqual(a.candidates[0].character_offset,
                         b.candidates[0].character_offset)

    def test_crlf_consistency(self):
        self.assertEqual(analyze_event_timing_text('가\n\n하지만'),
                         analyze_event_timing_text('가\r\n\r\n하지만'))

    def test_nonsemantic_cues(self):
        r = analyze_event_timing_text('하지만 점심은 맛있었다.')
        self.assertEqual(r.candidate_count, 1)
        self.assertFalse(hasattr(r, 'confirmed_major_events'))

    def test_inflection_missed(self):
        self.assertEqual(analyze_event_timing_text('성공했다. 위험해졌다.').candidate_count, 0)

    def test_cue_categories(self):
        r = analyze_event_timing_text('하지만 결국 성공!')
        self.assertEqual((r.cue_totals.conflict, r.cue_totals.payoff), (1, 2))
        self.assertEqual(sum(r.quintile_counts), r.candidate_count)

    def test_tied_peak_none(self):
        self.assertIsNone(analyze_event_timing_text(
            '하지만 ' + '가' * 100 + ' 결국').peak_quintile)

    def test_unique_peak(self):
        r = analyze_event_timing_text('하지만 그러나 ' + '가' * 100)
        self.assertEqual(r.peak_quintile, 1)

    def test_budget_exceeded(self):
        with self.assertRaises(ReferenceParseError):
            analyze_event_timing_text('하지만 그러나', max_markers=1)

    def test_budget_one(self):
        self.assertEqual(analyze_event_timing_text('하지만', max_markers=1).candidate_count, 1)

    def test_invalid_budget(self):
        for value in (None, True, False, 0, -1, 2.0, '5', MAX_EVENT_MARKERS+1):
            with self.subTest(value=value), self.assertRaises(ReferenceParseError):
                analyze_event_timing_text('하지만', max_markers=value)

    def test_invalid_number(self):
        for value in (True, False, 0, -1, 10001, '1', 1.0):
            with self.subTest(value=value), self.assertRaises(ReferenceParseError):
                analyze_event_timing_text('하지만', number=value)

    def test_invalid_text(self):
        with self.assertRaises(ReferenceParseError):
            analyze_event_timing_text(None)

    def test_immutable_private(self):
        r = analyze_event_timing_text('극비장면 하지만 그의 비밀.')
        self.assertNotIn('극비장면', repr(r))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.candidates[0].category = 'secret'

    def test_deterministic(self):
        text = '처음.\n\n하지만 위기.\n\n결국 해결.'
        self.assertEqual(analyze_event_timing_text(text), analyze_event_timing_text(text))

    def test_matches_stage22(self):
        text = '하지만 그러나\n\n그리고 그래서\n\n결국 성공\n\n그런데 반전'
        r = analyze_event_timing_text(text)
        s = analyze_structure_text(text)
        for key in ('conflict', 'progression', 'payoff', 'reversal'):
            expected = sum(getattr(getattr(getattr(s, region), 'cues'), key)
                           for region in ('opening', 'middle', 'ending'))
            self.assertEqual(getattr(r.cue_totals, key), expected)


class ReferenceEventTimingTests(unittest.TestCase):
    def test_episodes_and_preface(self):
        d = parse_text('하지만 서문.\n\n1화\n\n그러나 시작.\n\n2화\n\n결국 해결.')
        r = analyze_reference_event_timing(d)
        self.assertEqual(r.episode_count, 2)
        self.assertEqual(r.total_candidates, 3)
        self.assertEqual([x.episode_number for x in r.episodes], [1, 2])

    def test_unmarked_single_episode(self):
        r = analyze_reference_event_timing(parse_text('그러나 위기.\n\n결국 성공.'))
        self.assertEqual((r.episode_count, r.total_candidates), (1, 4))

    def test_markdown_heading_and_code_excluded(self):
        d = parse_text('# 하지만\n\n## 1화\n\n시작.\n\n' +
                       '\x60\x60\x60\n반전 결국 그러나\n\x60\x60\x60\n\n그런데 끝.', format='markdown')
        r = analyze_reference_event_timing(d)
        self.assertEqual((r.episode_count, r.total_candidates), (1, 1))

    def test_docx_and_pdf_blocks(self):
        for fmt in ('docx', 'pdf'):
            with self.subTest(format=fmt):
                d = ParsedReference(fmt, None, '', (
                    ParsedBlock('heading', 1, 1, '1화', 1),
                    ParsedBlock('paragraph', 2, 2, '하지만 위험.'),
                    ParsedBlock('table', 3, 3, '마침내 해결')))
                r = analyze_reference_event_timing(d)
                self.assertEqual(r.total_candidates, 4)
                self.assertEqual(r.episodes[0].paragraph_count, 2)

    def test_empty_body(self):
        r = analyze_reference_event_timing(parse_text('1화'))
        self.assertEqual(r.episodes[0].candidate_count, 0)

    def test_global_limit(self):
        d = parse_text('1화\n\n하지만\n\n2화\n\n결국')
        with self.assertRaises(ReferenceParseError):
            analyze_reference_event_timing(d, max_markers=1)

    def test_no_hits_after_budget_exhaustion(self):
        d = parse_text('1화\n\n하지만\n\n2화\n\n걷는다.')
        self.assertEqual(analyze_reference_event_timing(d, max_markers=1).total_candidates, 1)

    def test_stale_split(self):
        d = parse_text('1화\n\n하지만 간다.')
        s = split_episodes(parse_text('1화\n\n전혀 다르다.'))
        with self.assertRaises(ReferenceParseError):
            analyze_reference_event_timing(d, split=s)

    def test_invalid_document(self):
        with self.assertRaises(ReferenceParseError):
            analyze_reference_event_timing('원고')

    def test_reversed_episode_numbers(self):
        with self.assertRaises(ReferenceParseError):
            analyze_reference_event_timing(parse_text('2화\n\n그러나\n\n1화\n\n결국'))

    def test_no_source_retained(self):
        r = analyze_reference_event_timing(parse_text('1화\n\n유출금지 하지만 누가 말했다.'))
        self.assertNotIn('유출금지', repr(r))

    def test_consistent_stage22_character_counts(self):
        d = parse_text('1화\n\n하지만 위험.\n\n2화\n\n결국 보상.')
        r = analyze_reference_event_timing(d)
        s = analyze_reference_structure(d)
        self.assertEqual([x.characters_no_whitespace for x in r.episodes],
                         [x.characters_no_whitespace for x in s.episodes])


if __name__ == '__main__':
    unittest.main()
