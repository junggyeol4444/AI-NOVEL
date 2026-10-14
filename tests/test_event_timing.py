"""Stage 23: deterministic cue timing without source text persistence."""
import dataclasses
import unittest

from ai_novel_factory.references import (
    MAX_EVENT_MARKERS,
    ParsedBlock, ParsedReference, ReferenceParseError,
    analyze_event_timing_text, analyze_reference_event_timing,
    analyze_structure_text, parse_text, split_episodes,
)


class EventTimingTextTests(unittest.TestCase):
    def test_empty_text_has_no_candidates(self):
        result = analyze_event_timing_text('  \n\n ')
        self.assertEqual(result.candidate_count, 0)
        self.assertEqual(result.characters_no_whitespace, 0)
        self.assertEqual(result.quintile_counts, (0, 0, 0, 0, 0))
        self.assertIsNone(result.peak_quintile)

    def test_plain_text_has_no_candidates(self):
        result = analyze_event_timing_text('그는 조용히 걸어갔다.\n\n집으로 돌아왔다.')
        self.assertEqual(result.candidates, ())
        self.assertIsNone(result.peak_quintile)

    def test_single_hit_first_character(self):
        result = analyze_event_timing_text('하지만\n\n사건은 끝났다.')
        self.assertEqual(result.candidate_count, 1)
        candidate = result.candidates[0]
        self.assertEqual(candidate.category, 'conflict')
        self.assertEqual(candidate.character_offset, 0)
        self.assertEqual(candidate.position_percent, 0.0)
        self.assertEqual(candidate.quintile, 1)
        self.assertEqual(candidate.paragraph_number, 1)
        self.assertEqual(result.peak_quintile, 1)

    def test_movement_within_paragraph(self):
        result = analyze_event_timing_text('가나 다라 하지만 마바')
        marker = result.candidates[0]
        self.assertEqual(marker.character_offset, 4)
        self.assertEqual(marker.position_percent,
                         round(100 * 4 / len('가나다라하지만마바'), 2))
        self.assertEqual(marker.paragraph_number, 1)

    def test_cues_sorted_in_source_order_not_category_order(self):
        result = analyze_event_timing_text('결국 그리고 하지만 그런데')
        self.assertEqual([m.category for m in result.candidates],
                         ['payoff', 'progression', 'conflict', 'reversal'])
        offsets = [m.character_offset for m in result.candidates]
        self.assertEqual(offsets, sorted(offsets))

    def test_hit_in_second_paragraph_has_global_offset(self):
        text = '가나다.\n\n마바사 하지만'
        result = analyze_event_timing_text(text)
        candidate = result.candidates[0]
        self.assertEqual(candidate.paragraph_number, 2)
        self.assertEqual(candidate.character_offset, len('가나다.마바사'))

    def test_newlines_and_whitespace_do_not_count(self):
        a = analyze_event_timing_text('가 나 다 하지만')
        b = analyze_event_timing_text('가\t나   다\n하지만')
        self.assertEqual(a.candidates[0].character_offset,
                         b.candidates[0].character_offset)

    def test_crlf_normalization(self):
        a = analyze_event_timing_text('시작.\n\n하지만 위험.')
        b = analyze_event_timing_text('시작.\r\n\r\n하지만 위험.')
        self.assertEqual(a, b)

    def test_hint_not_semantic_event(self):
        result = analyze_event_timing_text('하지만 점심은 맛있었다.')
        self.assertEqual(result.candidate_count, 1)
        self.assertFalse(hasattr(result, 'confirmed_major_events'))

    def test_keyword_inflection_limit(self):
        r = analyze_event_timing_text('성공했다. 위험해졌다.')
        self.assertEqual(r.candidate_count, 0)

    def test_simultaneous_categories_in_short_episode(self):
        r = analyze_event_timing_text('하지만 결국 성공!')
        self.assertEqual(r.cue_totals.conflict, 1)
        self.assertEqual(r.cue_totals.payoff, 2)
        self.assertEqual(sum(r.quintile_counts), r.candidate_count)

    def test_tie_peak_is_ambiguous(self):
        r = analyze_event_timing_text('하지만 ' + '가'*100 + ' 결국')
        self.assertEqual(r.candidate_count, 2)
        self.assertIsNone(r.peak_quintile)

    def test_peak_is_unique_when_multiple_hits_in_one_band(self):
        r = analyze_event_timing_text('하지만 그러나 ' + '가'*100)
        self.assertEqual(r.peak_quintile, 1)
        self.assertEqual(r.quintile_counts[0], 2)

    def test_marker_limit_enforced(self):
        with self.assertRaisesRegex(ReferenceParseError, '허용 개수'):
            analyze_event_timing_text('하지만 그러나', max_markers=1)

    def test_limit_one_is_allowed(self):
        r = analyze_event_timing_text('하지만', max_markers=1)
        self.assertEqual(r.candidate_count, 1)

    def test_invalid_marker_limit_rejected(self):
        for bad in (None, True, False, 0, -1, 2.0, '5', MAX_EVENT_MARKERS+1):
            with self.subTest(bad=bad), self.assertRaises(ReferenceParseError):
                analyze_event_timing_text('하지만', max_markers=bad)

    def test_invalid_episode_numbers_rejected(self):
        for number in (True, False, 0, -1, 10001, '1', 1.0):
            with self.subTest(value=number), self.assertRaises(ReferenceParseError):
                analyze_event_timing_text('하지만', number=number)

    def test_text_type_rejected(self):
        with self.assertRaises(ReferenceParseError):
            analyze_event_timing_text(None)

    def test_record_is_immutable_and_does_not_retain_text(self):
        secret = '극비장면 하지만 그의 비밀.'
        r = analyze_event_timing_text(secret)
        self.assertNotIn('극비장면', repr(r))
        self.assertNotIn('그의 비밀', str(r))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.candidates[0].category = 'private'

    def test_repeated_run_is_deterministic(self):
        txt = '시작했다.\n\n그러나 반전.\n\n결국 성공.'
        self.assertEqual(analyze_event_timing_text(txt), analyze_event_timing_text(txt))

    def test_category_totals_agree_with_stage22(self):
        txt = '하지만 그러나\n\n그리고 그래서\n\n결국 성공\n\n그런데 반전'
        timeline = analyze_event_timing_text(txt)
        structure = analyze_structure_text(txt)
        for category in ('conflict', 'progression', 'payoff', 'reversal'):
            expected = sum(getattr(getattr(getattr(structure, s), 'cues'), category)
                           for s in ('opening', 'middle', 'ending'))
            self.assertEqual(getattr(timeline.cue_totals, category), expected)


class EventTimingReferenceTests(unittest.TestCase):
    def test_two_episodes_preface_excluded(self):
        document = parse_text('하지만 서문.\n\n1화\n\n그러나 일이 있었다.\n\n2화\n\n결국 해결.')
        r = analyze_reference_event_timing(document)
        self.assertEqual(r.episode_count, 2)
        self.assertEqual([e.episode_number for e in r.episodes], [1, 2])
        self.assertEqual([e.candidate_count for e in r.episodes], [1, 2])
        self.assertEqual(r.total_candidates, 3)
        self.assertEqual(sum(r.quintile_counts), 3)

    def test_no_explicit_episode_marker(self):
        document = parse_text('그러나 위기.\n\n결국 성공.')
        r = analyze_reference_event_timing(document)
        self.assertEqual(r.episode_count, 1)
        self.assertEqual(r.total_candidates, 4)

    def test_markdown_headings_and_code_are_excluded(self):
        document = parse_text('# 하지만\n\n## 1화\n\n시작했다.\n\n```\n반전 결국 그러나\n```\n\n그런데 끝.', format='markdown')
        r = analyze_reference_event_timing(document)
        self.assertEqual(r.total_candidates, 1)
        self.assertEqual(r.episodes[0].candidates[0].category, 'reversal')

    def test_docx_pdf_common_block_types(self):
        for fmt in ('docx', 'pdf'):
            with self.subTest(fmt=fmt):
                doc = ParsedReference(fmt, None, '', (
                    ParsedBlock('heading', 1, 1, '1화', 1),
                    ParsedBlock('paragraph', 2, 2, '하지만 위험.'),
                    ParsedBlock('table', 3, 3, '마침내 해결'),
                ))
                r = analyze_reference_event_timing(doc)
                self.assertEqual(r.episode_count, 1)
                self.assertEqual(r.total_candidates, 4)
                self.assertEqual(r.episodes[0].paragraph_count, 2)

    def test_empty_episode_after_heading(self):
        doc = parse_text('1화')
        r = analyze_reference_event_timing(doc)
        self.assertEqual(r.episode_count, 1)
        self.assertEqual(r.episodes[0].candidate_count, 0)
        self.assertEqual(r.episodes[0].characters_no_whitespace, 0)

    def test_global_limit_is_not_per_episode(self):
        doc = parse_text('1화\n\n하지만\n\n2화\n\n결국')
        with self.assertRaisesRegex(ReferenceParseError, '허용 개수'):
            analyze_reference_event_timing(doc, max_markers=1)

    def test_limit_exhausted_but_no_extra_hit(self):
        doc = parse_text('1화\n\n하지만\n\n2화\n\n한밤이었다.')
        r = analyze_reference_event_timing(doc, max_markers=1)
        self.assertEqual(r.total_candidates, 1)

    def test_mismatching_split_rejected(self):
        doc = parse_text('1화\n\n하지만 간다.')
        split = split_episodes(parse_text('1화\n\n전혀 다르다.'))
        with self.assertRaises(ReferenceParseError):
            analyze_reference_event_timing(doc, split=split)

    def test_wrong_document_rejected(self):
        with self.assertRaises(ReferenceParseError):
            analyze_reference_event_timing('잘못된 문서')

    def test_invalid_episode_order_rejected(self):
        doc = parse_text('2화\n\n그러나\n\n1화\n\n결국')
        with self.assertRaises(ReferenceParseError):
            analyze_reference_event_timing(doc)

    def test_reference_result_never_exposes_source(self):
        doc = parse_text('1화\n\n유출하면안되는비밀 하지만 누군가 말했다.')
        r = analyze_reference_event_timing(doc)
        self.assertNotIn('유출하면안되는비밀', repr(r))
        self.assertNotIn('누군가 말했다', str(r))

    def test_reference_matches_stage22_count(self):
        doc = parse_text('1화\n\n하지만 위험.\n\n그리고 걸었다.\n\n2화\n\n결국 보상.\n\n그러나 어두워졌다.')
        r = analyze_reference_event_timing(doc)
        from ai_novel_factory.references import analyze_reference_structure
        structures = analyze_reference_structure(doc)
        self.assertEqual(r.episode_count, structures.episode_count)
        self.assertEqual([x.characters_no_whitespace for x in r.episodes],
                         [x.characters_no_whitespace for x in structures.episodes])


if __name__ == '__main__':
    unittest.main()
