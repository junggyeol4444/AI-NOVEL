"""Stage 25: offline cliffhanger signal classifier regression tests."""
import dataclasses
import unittest
from ai_novel_factory.references import (
    LEXICAL_TYPES, PUNCTUATION_TYPES, TYPE_PRIORITY,
    ReferenceParseError, analyze_cliffhanger_text,
    analyze_reference_cliffhangers, parse_text, split_episodes,
)


class CliffhangerTextTests(unittest.TestCase):
    def test_plain_ending_no_hook(self):
        result = analyze_cliffhanger_text("그는 집으로 돌아갔다.")
        self.assertEqual(result.primary_type, "none")
        self.assertFalse(result.possible_cliffhanger)
        self.assertEqual(result.ending_punctuation, "none")

    def test_question(self):
        result = analyze_cliffhanger_text("그는 돌아올까?")
        self.assertEqual(result.primary_type, "question")
        self.assertEqual(result.candidate_types, ("question",))

    def test_korean_question_with_closing_quotes(self):
        self.assertEqual(analyze_cliffhanger_text('“왜 왔니?”').primary_type, 'question')

    def test_question_exclamation_follows_stage22_terminal_punctuation(self):
        self.assertEqual(analyze_cliffhanger_text('어째서?!').primary_type, 'exclamation')

    def test_ellipsis_unicode(self):
        self.assertEqual(analyze_cliffhanger_text('그의 말은 이어졌다…').primary_type, 'ellipsis')

    def test_ellipsis_ascii(self):
        self.assertEqual(analyze_cliffhanger_text('그는 말을 멈췄다...').primary_type, 'ellipsis')

    def test_exclamation(self):
        self.assertEqual(analyze_cliffhanger_text('그들이 돌아왔다!').primary_type, 'exclamation')

    def test_revelation(self):
        result=analyze_cliffhanger_text('사실은 그가 진짜 주인이었다.')
        self.assertEqual(result.primary_type,'revelation')
        self.assertEqual(result.lexical_signals.revelation,1)

    def test_danger(self):
        result=analyze_cliffhanger_text('그의 앞에는 총구가 있었다.')
        self.assertEqual(result.primary_type,'danger')
        self.assertEqual(result.lexical_signals.danger,1)

    def test_interruption(self):
        result=analyze_cliffhanger_text('그 순간, 문이 열렸다.')
        self.assertEqual(result.primary_type,'interruption')
        self.assertEqual(result.lexical_signals.interruption,2)

    def test_decision(self):
        self.assertEqual(analyze_cliffhanger_text('둘 중 하나를 선택해야 했다.').primary_type,'decision')

    def test_multiple_types_use_explicit_priority(self):
        result=analyze_cliffhanger_text('사실은 그가 위기에 있었다?')
        self.assertEqual(result.primary_type,'revelation')
        self.assertEqual(result.candidate_types, ('revelation','danger','question'))

    def test_no_raw_evidence_in_repr(self):
        source='내부기밀이름Z 사실은 그가 말했다?'
        result=analyze_cliffhanger_text(source)
        self.assertNotIn('내부기밀이름Z',repr(result))
        self.assertNotIn('그가 말했다',repr(result))
        self.assertFalse(hasattr(result,'evidence_snippet'))

    def test_output_immutable(self):
        result=analyze_cliffhanger_text('위기!')
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.primary_type='danger'

    def test_deterministic(self):
        source='사실은 그가 돌아왔다…'
        self.assertEqual(analyze_cliffhanger_text(source), analyze_cliffhanger_text(source))

    def test_empty(self):
        result=analyze_cliffhanger_text(' \n\t ')
        self.assertEqual(result.primary_type,'none')
        self.assertEqual(result.analyzed_tail_paragraphs,0)
        self.assertEqual(result.body_characters,0)

    def test_first_three_paragraphs_not_in_last_quarter(self):
        result=analyze_cliffhanger_text('폭발했다.\n\n평범했다.\n\n조용했다.\n\n집으로 돌아왔다.')
        self.assertEqual(result.primary_type,'none')
        self.assertEqual(result.analyzed_tail_paragraphs,1)

    def test_five_paragraphs_tail_is_two(self):
        result=analyze_cliffhanger_text('A\n\nB\n\nC\n\n그 순간 있었다.\n\n그리고 끝났다.')
        self.assertEqual(result.analyzed_tail_paragraphs,2)
        self.assertEqual(result.primary_type,'interruption')

    def test_many_paragraphs_cap_tail_at_three(self):
        result=analyze_cliffhanger_text('\n\n'.join(['평범했다.']*20))
        self.assertEqual(result.analyzed_tail_paragraphs,3)

    def test_visible_count_and_tail_count(self):
        result=analyze_cliffhanger_text('가 나\n\n다 라\n\n마 바\n\n위기!')
        self.assertEqual(result.body_characters,9)
        self.assertEqual(result.analyzed_tail_characters,3)

    def test_invalid_type(self):
        for bad in (None,42,[],{},b'hi'):
            with self.subTest(bad=bad),self.assertRaises(ReferenceParseError):
                analyze_cliffhanger_text(bad)

    def test_invalid_number(self):
        for bad in (0,-1,10001,True,'2',2.5):
            with self.subTest(bad=bad),self.assertRaises(ReferenceParseError):
                analyze_cliffhanger_text('끝?',number=bad)

    def test_fixed_taxonomy(self):
        self.assertEqual(len(set((*LEXICAL_TYPES,*PUNCTUATION_TYPES))),7)
        self.assertEqual(len(TYPE_PRIORITY),7)


class ReferenceCliffhangerTests(unittest.TestCase):
    def test_marked_multi_episodes(self):
        doc=parse_text('1화\n\n그는 돌아왔다?\n\n2화\n\n사실은 거짓이었다.')
        result=analyze_reference_cliffhangers(doc)
        self.assertEqual(result.episode_count,2)
        self.assertEqual(result.possible_cliffhanger_count,2)
        self.assertEqual([e.primary_type for e in result.episodes],['question','revelation'])
        self.assertEqual(dict(result.primary_type_counts)['question'],1)
        self.assertEqual(dict(result.primary_type_counts)['revelation'],1)

    def test_preface_is_ignored(self):
        doc=parse_text('서문: 폭발과 위기?\n\n1화\n\n오늘은 평범했다.')
        result=analyze_reference_cliffhangers(doc)
        self.assertEqual(result.episodes[0].primary_type,'none')

    def test_markdown_code_and_heading_excluded(self):
        doc=parse_text('## 1화\n\n평범했다.\n\n```\n사실은 위기?\n```',format='markdown')
        result=analyze_reference_cliffhangers(doc)
        self.assertEqual(result.episodes[0].primary_type,'none')

    def test_no_episode_markers_means_single_episode(self):
        doc=parse_text('사실은 그러했다.')
        result=analyze_reference_cliffhangers(doc)
        self.assertEqual(result.episode_count,1)
        self.assertEqual(result.episodes[0].primary_type,'revelation')

    def test_empty_marked_episode(self):
        doc=parse_text('1화\n\n2화\n\n그는 떠났다.')
        result=analyze_reference_cliffhangers(doc)
        self.assertEqual(result.episodes[0].primary_type,'none')
        self.assertEqual(result.possible_cliffhanger_count,0)

    def test_stale_split_rejected(self):
        current=parse_text('1화\n\n그는 떠났다?')
        stale=split_episodes(parse_text('1화\n\n2화\n\n그는 떠났다?'))
        with self.assertRaises(ReferenceParseError):
            analyze_reference_cliffhangers(current,split=stale)

    def test_invalid_doc_rejected(self):
        for value in (None,'a',{},[]):
            with self.subTest(value=value), self.assertRaises(ReferenceParseError):
                analyze_reference_cliffhangers(value)

    def test_summary_counts_total(self):
        doc=parse_text('1화\n\n끝?\n\n2화\n\n끝.\n\n3화\n\n끝!')
        result=analyze_reference_cliffhangers(doc)
        self.assertEqual(sum(v for _,v in result.primary_type_counts),3)
        self.assertEqual(result.possible_cliffhanger_count,2)
        self.assertEqual(dict(result.primary_type_counts)['none'],1)

    def test_source_not_in_result_repr(self):
        doc=parse_text('1화\n\n절대노출안됨Z 사실은 그였다.')
        result=analyze_reference_cliffhangers(doc)
        self.assertNotIn('절대노출안됨Z',repr(result))

    def test_uses_supplied_matching_split(self):
        doc=parse_text('1화\n\n위기?')
        s=split_episodes(doc)
        self.assertEqual(analyze_reference_cliffhangers(doc,split=s), analyze_reference_cliffhangers(doc))


if __name__=='__main__':
    unittest.main()
