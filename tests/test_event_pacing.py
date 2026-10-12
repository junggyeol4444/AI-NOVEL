"""Stage 24: deterministic local pacing proxy and gap tests."""
import dataclasses
import unittest

from ai_novel_factory.references import (
    MAX_EVENT_MARKERS,
    GapMetrics,
    ReferenceParseError,
    analyze_pacing_text,
    analyze_reference_event_timing,
    analyze_reference_pacing,
    parse_text,
    split_episodes,
)


class PacingTextTests(unittest.TestCase):
    def test_empty_body_returns_zero_density(self):
        item = analyze_pacing_text('  \n\n  ')
        self.assertEqual(item.characters_no_whitespace, 0)
        self.assertEqual(item.candidate_count, 0)
        self.assertEqual(item.quintile_rates, (0.0,) * 5)
        self.assertEqual(item.gaps.longest_span, 0)
        self.assertIsNone(item.gaps.mean)

    def test_no_candidates_full_boundary_span(self):
        item = analyze_pacing_text('가 나 다')
        self.assertEqual(item.characters_no_whitespace, 3)
        self.assertEqual(item.candidate_count, 0)
        self.assertEqual(item.gaps.longest_span, 3)
        self.assertEqual(item.gaps.sample_count, 0)
        self.assertIsNone(item.gaps.minimum)
        self.assertIsNone(item.gaps.maximum)

    def test_one_candidate_has_no_inter_candidate_gap(self):
        item = analyze_pacing_text('하지만')
        self.assertEqual(item.candidate_count, 1)
        self.assertEqual(item.gaps.sample_count, 0)
        self.assertEqual(item.gaps.longest_span, 3)
        self.assertIsNone(item.gaps.mean)
        self.assertEqual(item.quintile_counts[0], 1)
        self.assertEqual(item.quintile_rates[0], 1000)

    def test_two_cues_gap_uses_nonwhitespace_offset(self):
        item = analyze_pacing_text('하지만 가가가 결국')
        self.assertEqual(item.characters_no_whitespace, 8)
        self.assertEqual(item.candidate_count, 2)
        self.assertEqual(item.gaps.minimum, 6)
        self.assertEqual(item.gaps.maximum, 6)
        self.assertEqual(item.gaps.mean, 6.0)
        self.assertEqual(item.gaps.median, 6.0)
        self.assertEqual(item.gaps.standard_deviation, 0.0)
        self.assertEqual(item.gaps.coefficient_of_variation, 0.0)
        self.assertEqual(item.gaps.longest_span, 6)
        self.assertEqual(item.candidates_per_1000_characters, 250.0)

    def test_three_cues_with_regular_spacing(self):
        item = analyze_pacing_text('하지만 그러나 결국')
        self.assertEqual(item.gaps.sample_count, 2)
        self.assertEqual(item.gaps.mean, 3)
        self.assertEqual(item.gaps.standard_deviation, 0)
        self.assertEqual(item.gaps.longest_span, 3)

    def test_variable_spacing(self):
        item = analyze_pacing_text('하지만 결국 ' + '가'*10 + ' 그리고')
        self.assertEqual(item.gaps.sample_count, 2)
        self.assertEqual(item.gaps.minimum, 3)
        self.assertEqual(item.gaps.maximum, 12)
        self.assertEqual(item.gaps.mean, 7.5)
        self.assertEqual(item.gaps.median, 7.5)
        self.assertEqual(item.gaps.standard_deviation, 4.5)
        self.assertEqual(item.gaps.coefficient_of_variation, round(4.5/7.5,4))

    def test_blank_line_does_not_change_gap(self):
        a = analyze_pacing_text('하지만\n\n결국')
        b = analyze_pacing_text('하지만 결국')
        self.assertEqual(a.gaps, b.gaps)
        self.assertEqual(a.candidates_per_1000_characters,
                         b.candidates_per_1000_characters)

    def test_more_than_one_quote_or_category_is_not_scene(self):
        item = analyze_pacing_text('하지만 결국, 그러나 그날은 평범했다.')
        self.assertGreater(item.candidate_count, 0)
        self.assertFalse(hasattr(item, 'confirmed_scene_count'))
        self.assertFalse(hasattr(item, 'true_narrative_pacing'))

    def test_short_episodes_have_correct_quintile_denominators(self):
        item = analyze_pacing_text('하지만')
        self.assertEqual(item.quintile_counts, (1,0,0,0,0))
        self.assertEqual(item.quintile_rates, (1000.0,0,0,0,0))

    def test_very_short_single_character_no_candidates(self):
        item = analyze_pacing_text('가')
        self.assertEqual(item.quintile_rates, (0,0,0,0,0))

    def test_quintile_counts_match_step23_without_relabeling(self):
        item = analyze_pacing_text('하지만 ' + '가'*40 + ' 결국')
        self.assertEqual(sum(item.quintile_counts), item.candidate_count)
        self.assertEqual(item.quintile_counts[0], 1)
        self.assertEqual(item.quintile_counts[-1], 1)

    def test_repeated_results_deterministic(self):
        text = '그러나 결국 시작했다.\n\n그런데 다시 싸웠다.'
        self.assertEqual(analyze_pacing_text(text), analyze_pacing_text(text))

    def test_source_text_not_in_result_repr(self):
        secret = '기밀원고 그러나 이 이야기는 외부에 알려지면 안 된다.'
        item = analyze_pacing_text(secret)
        self.assertNotIn('기밀원고', repr(item))
        self.assertNotIn('알려지면 안 된다', str(item))

    def test_output_is_immutable(self):
        item = analyze_pacing_text('하지만')
        self.assertIsInstance(item.gaps, GapMetrics)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            item.gaps.minimum = 200

    def test_unsupported_text_type_raises(self):
        for value in (None, 10, [], {}):
            with self.subTest(value=value), self.assertRaises(ReferenceParseError):
                analyze_pacing_text(value)

    def test_invalid_limits_rejected(self):
        for value in (0, -1, None, True, False, 0.5, str(10), MAX_EVENT_MARKERS+1):
            with self.subTest(value=value), self.assertRaises(ReferenceParseError):
                analyze_pacing_text('하지만', max_markers=value)

    def test_invalid_episode_number_rejected(self):
        for value in (0, 10001, True, '1'):
            with self.subTest(value=value), self.assertRaises(ReferenceParseError):
                analyze_pacing_text('하지만', number=value)

    def test_limits_carried_through(self):
        with self.assertRaisesRegex(ReferenceParseError, '허용 개수'):
            analyze_pacing_text('하지만 그리고', max_markers=1)


class ReferencePacingTests(unittest.TestCase):
    def test_two_episodes_no_cross_episode_gap(self):
        doc = parse_text('1화\n\n하지만\n\n2화\n\n결국')
        item = analyze_reference_pacing(doc)
        self.assertEqual(item.episode_count, 2)
        self.assertEqual(item.candidate_count, 2)
        self.assertEqual(item.characters_no_whitespace, len('하지만결국'))
        self.assertEqual(item.gap_sample_count, 0)
        self.assertIsNone(item.mean_gap_characters)

    def test_total_density_weighted_not_simple_mean(self):
        doc = parse_text('1화\n\n하지만\n\n2화\n\n'+'가'*97+' 결국')
        item = analyze_reference_pacing(doc)
        self.assertEqual(item.candidate_count, 2)
        self.assertEqual(item.characters_no_whitespace, 102)
        self.assertEqual(item.candidates_per_1000_characters, round(2000/102,2))

    def test_gap_average_is_pooled_by_interval_count(self):
        doc = parse_text('1화\n\n하지만 결국\n\n2화\n\n그러나 '+'가'*10+' 그리고 반전')
        item = analyze_reference_pacing(doc)
        self.assertEqual(item.gap_sample_count, 3)
        self.assertEqual(item.mean_gap_characters,
                         round((3+13+3)/3, 2))

    def test_preface_not_in_denominator(self):
        doc = parse_text('서문 그러나 서술은 길다.\n\n1화\n\n하지만')
        item = analyze_reference_pacing(doc)
        self.assertEqual(item.episode_count, 1)
        self.assertEqual(item.candidate_count, 1)
        self.assertEqual(item.characters_no_whitespace, 3)

    def test_markdown_code_and_headings_excluded(self):
        doc = parse_text('## 1화\n\n하지만 시작했다.\n\n```\n결국 그러니까\n```', format='markdown')
        item = analyze_reference_pacing(doc)
        self.assertEqual(item.candidate_count, 1)
        self.assertEqual(item.episode_count, 1)

    def test_empty_marked_episode(self):
        doc = parse_text('1화')
        item = analyze_reference_pacing(doc)
        self.assertEqual(item.candidate_count, 0)
        self.assertEqual(item.characters_no_whitespace, 0)
        self.assertEqual(item.episodes[0].gaps.longest_span, 0)

    def test_reference_without_markers_is_one_episode(self):
        doc = parse_text('하지만 위기.\n\n결국 해결.')
        item = analyze_reference_pacing(doc)
        self.assertEqual(item.episode_count, 1)
        self.assertEqual(item.candidate_count, 4)

    def test_matching_cached_timing_permitted(self):
        doc = parse_text('1화\n\n하지만 결국')
        cached = analyze_reference_event_timing(doc)
        item = analyze_reference_pacing(doc, timing=cached)
        self.assertEqual(item.candidate_count, cached.total_candidates)

    def test_stale_cached_timing_rejected(self):
        doc = parse_text('1화\n\n하지만')
        stale = analyze_reference_event_timing(parse_text('1화\n\n결국'))
        with self.assertRaisesRegex(ReferenceParseError, '일치하지 않습니다'):
            analyze_reference_pacing(doc, timing=stale)

    def test_bad_cached_type_rejected(self):
        doc = parse_text('1화\n\n하지만')
        with self.assertRaises(ReferenceParseError):
            analyze_reference_pacing(doc, timing='wrong')

    def test_mismatched_split_rejected(self):
        doc = parse_text('1화\n\n하지만')
        split = split_episodes(parse_text('1화\n\n결국'))
        with self.assertRaises(ReferenceParseError):
            analyze_reference_pacing(doc, split=split)

    def test_invalid_doc_type_rejected(self):
        with self.assertRaises(ReferenceParseError):
            analyze_reference_pacing('원문')

    def test_global_marker_cap_enforced(self):
        doc = parse_text('1화\n\n하지만\n\n2화\n\n결국')
        with self.assertRaises(ReferenceParseError):
            analyze_reference_pacing(doc, max_markers=1)

    def test_source_never_saved_or_logged_in_summary(self):
        doc = parse_text('1화\n\n비밀스러운문장 그러나 사건이 벌어졌다.')
        item = analyze_reference_pacing(doc)
        self.assertNotIn('비밀스러운문장', repr(item))
        self.assertNotIn('사건이 벌어졌다', str(item))
