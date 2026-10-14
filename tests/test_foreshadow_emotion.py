"""Stage 28 tests: cue-based foreshadow hints and emotion-word curves."""
import dataclasses
import unittest

from ai_novel_factory.references import (
    MAX_FORESHADOW_EMOTION_CUES, MAX_ANALYZED_TEXT_CHARS,
    analyze_foreshadow_emotion_text, analyze_reference_foreshadow_emotion,
)
from ai_novel_factory.references.episode_splitter import split_episodes
from ai_novel_factory.references.plaintext_parser import parse_text, ReferenceParseError


class TextCueTests(unittest.TestCase):
    def test_blank_text_emotion_has_no_evidence(self):
        result = analyze_foreshadow_emotion_text('')
        self.assertEqual(result.paragraph_count, 0)
        self.assertEqual(result.cues.count, 0)
        self.assertEqual(result.emotion_balance, 0.0)
        self.assertEqual(result.emotion_direction, 'no_cues')

    def test_setup_count(self):
        out = analyze_foreshadow_emotion_text('수상한 단서가 있었다. 예언도 남겼다.')
        self.assertEqual(out.cues.setup, 3)
        self.assertEqual(out.cues.reveal, 0)

    def test_reveal_count(self):
        out = analyze_foreshadow_emotion_text('알고 보니 정체가 드러났다. 진실은 밝혀졌다.')
        self.assertEqual(out.cues.reveal, 5)

    def test_positive_count_and_direction(self):
        out = analyze_foreshadow_emotion_text('행복했다. 기쁘고 안심했다.')
        self.assertEqual(out.cues.positive, 3)
        self.assertEqual(out.emotion_balance, 1)
        self.assertEqual(out.emotion_direction, 'more_positive_cues')

    def test_negative_count_and_direction(self):
        out = analyze_foreshadow_emotion_text('슬프고 불안했다. 절망했다.')
        self.assertEqual(out.cues.negative, 3)
        self.assertEqual(out.emotion_balance, -1)
        self.assertEqual(out.emotion_direction, 'more_negative_cues')

    def test_balanced_polarity_words(self):
        out = analyze_foreshadow_emotion_text('행복했다. 불안했다.')
        self.assertEqual(out.emotion_balance, 0)
        self.assertEqual(out.emotion_direction, 'balanced_cues')

    def test_curves_have_five_windows(self):
        out = analyze_foreshadow_emotion_text('행복했다.\n\n불안했다.\n\n슬프다.\n\n희망이 있다.\n\n그저 걸었다.')
        self.assertEqual([x.quintile for x in out.emotion_curve], [1, 2, 3, 4, 5])
        self.assertEqual([x.paragraph_count for x in out.emotion_curve], [1, 1, 1, 1, 1])
        self.assertEqual([x.direction for x in out.emotion_curve], [
            'more_positive_cues', 'more_negative_cues', 'more_negative_cues',
            'more_positive_cues', 'no_cues'
        ])

    def test_short_episode_has_empty_windows(self):
        out = analyze_foreshadow_emotion_text('행복했다.')
        self.assertEqual([x.paragraph_count for x in out.emotion_curve], [1, 0, 0, 0, 0])
        self.assertTrue(all(x.balance == 0 for x in out.emotion_curve[1:]))

    def test_two_paragraphs_use_fixed_positions(self):
        out = analyze_foreshadow_emotion_text('행복했다.\n\n불안했다.')
        self.assertEqual([x.paragraph_count for x in out.emotion_curve], [1, 0, 1, 0, 0])

    def test_paragraph_character_count_matches_windows(self):
        out = analyze_foreshadow_emotion_text('안녕 세상.\n\n행복 했다.')
        self.assertEqual(sum(w.characters_no_whitespace for w in out.emotion_curve),
                         out.characters_no_whitespace)
        self.assertEqual(sum(w.paragraph_count for w in out.emotion_curve), out.paragraph_count)

    def test_crlf_normalized(self):
        a = analyze_foreshadow_emotion_text('행복.\r\n\r\n불안.')
        b = analyze_foreshadow_emotion_text('행복.\n\n불안.')
        self.assertEqual(a, b)

    def test_do_not_match_inside_arbitrary_word(self):
        out = analyze_foreshadow_emotion_text('매우행복하거나 단서처럼보인다.')
        self.assertEqual(out.cues.positive, 0)
        self.assertEqual(out.cues.setup, 1)  # standalone word-start '단서' is a cue

    def test_no_double_count_overlapping_cues(self):
        out = analyze_foreshadow_emotion_text('단서는 단서였다.')
        self.assertEqual(out.cues.setup, 2)

    def test_single_text_never_claims_prior_episode_setup(self):
        out = analyze_foreshadow_emotion_text('단서가 드러났다.')
        self.assertFalse(out.prior_setup_before_reveal_candidate)

    def test_can_use_different_valid_episode_number(self):
        out = analyze_foreshadow_emotion_text('행복.', number=777)
        self.assertEqual(out.number, 777)

    def test_invalid_text(self):
        for value in (None, 3, {}, b'bytes', ['happy']):
            with self.subTest(value=type(value)), self.assertRaises(ReferenceParseError):
                analyze_foreshadow_emotion_text(value)

    def test_too_large_text_rejected(self):
        with self.assertRaises(ReferenceParseError):
            analyze_foreshadow_emotion_text('가' * (MAX_ANALYZED_TEXT_CHARS + 1))

    def test_invalid_number(self):
        for n in (-1, 0, 10001, True, '1', 1.5):
            with self.subTest(n=n), self.assertRaises(ReferenceParseError):
                analyze_foreshadow_emotion_text('행복', number=n)

    def test_invalid_budget(self):
        for n in (-1, 0, MAX_FORESHADOW_EMOTION_CUES + 1, True, '2', 2.5):
            with self.subTest(n=n), self.assertRaises(ReferenceParseError):
                analyze_foreshadow_emotion_text('행복', max_cues=n)

    def test_exact_budget_accepted(self):
        out = analyze_foreshadow_emotion_text('단서. 행복.', max_cues=2)
        self.assertEqual(out.cues.count, 2)

    def test_over_budget_rejected(self):
        with self.assertRaises(ReferenceParseError):
            analyze_foreshadow_emotion_text('단서. 행복.', max_cues=1)

    def test_empty_budget_used_up_but_no_more_cues_is_allowed(self):
        out = analyze_foreshadow_emotion_text('단서. 지나갔다.', max_cues=1)
        self.assertEqual(out.cues.count, 1)

    def test_determinism(self):
        text = '단서.\n\n진실.\n\n불안.\n\n행복.'
        self.assertEqual(analyze_foreshadow_emotion_text(text), analyze_foreshadow_emotion_text(text))

    def test_frozen_results(self):
        out = analyze_foreshadow_emotion_text('단서.\n\n불안.')
        with self.assertRaises(dataclasses.FrozenInstanceError):
            out.number = 9
        with self.assertRaises(dataclasses.FrozenInstanceError):
            out.emotion_curve[0].balance = 0.77

    def test_returns_only_fixed_labels_and_numbers(self):
        secret = '행복한비밀고유토큰'
        out = analyze_foreshadow_emotion_text(secret)
        self.assertNotIn(secret, repr(out))
        self.assertNotIn(secret, str(dataclasses.asdict(out)))


class ReferenceCueTests(unittest.TestCase):
    def test_reveal_after_previous_episode_setup(self):
        doc = parse_text('1화\n\n수상한 단서가 있었다.\n\n2화\n\n진실이 드러났다.')
        out = analyze_reference_foreshadow_emotion(doc)
        self.assertEqual(out.episode_count, 2)
        self.assertEqual(out.total_cues.setup, 2)
        self.assertEqual(out.total_cues.reveal, 2)
        self.assertEqual(out.prior_setup_before_reveal_episodes, (2,))
        self.assertFalse(out.episodes[0].prior_setup_before_reveal_candidate)
        self.assertTrue(out.episodes[1].prior_setup_before_reveal_candidate)

    def test_same_episode_setup_does_not_count_as_prior(self):
        doc = parse_text('1화\n\n단서가 드러났다.')
        out = analyze_reference_foreshadow_emotion(doc)
        self.assertEqual(out.prior_setup_before_reveal_episodes, ())

    def test_reveal_before_hint_is_not_prior(self):
        doc = parse_text('1화\n\n진실이 밝혀졌다.\n\n2화\n\n단서가 있었다.')
        out = analyze_reference_foreshadow_emotion(doc)
        self.assertEqual(out.prior_setup_before_reveal_episodes, ())

    def test_multiple_later_reveals_are_independently_flagged(self):
        doc = parse_text('1화\n\n단서.\n\n2화\n\n진실.\n\n3화\n\n정체.')
        out = analyze_reference_foreshadow_emotion(doc)
        self.assertEqual(out.prior_setup_before_reveal_episodes, (2, 3))

    def test_non_consecutive_numbers_retained(self):
        doc = parse_text('3화\n\n단서.\n\n9화\n\n정체.')
        out = analyze_reference_foreshadow_emotion(doc)
        self.assertEqual([x.number for x in out.episodes], [3, 9])
        self.assertEqual(out.prior_setup_before_reveal_episodes, (9,))

    def test_preface_excluded(self):
        doc = parse_text('서문에서 단서와 진실이 있었다.\n\n1화\n\n그들은 걸었다.')
        out = analyze_reference_foreshadow_emotion(doc)
        self.assertEqual(out.total_cues.count, 0)
        self.assertEqual(out.prior_setup_before_reveal_episodes, ())

    def test_markdown_code_excluded(self):
        doc = parse_text('## 1화\n\n실제 본문은 평범했다.\n\n```\n단서 진실 불안 행복\n```', format='markdown')
        out = analyze_reference_foreshadow_emotion(doc)
        self.assertEqual(out.total_cues.count, 0)

    def test_markdown_headings_excluded(self):
        doc = parse_text('## 1화\n\n# 행복 비밀\n\n평범한 본문.', format='markdown')
        out = analyze_reference_foreshadow_emotion(doc)
        self.assertEqual(out.total_cues.count, 0)

    def test_no_markers_single_episode(self):
        doc = parse_text('단서가 있었고 행복했다.')
        out = analyze_reference_foreshadow_emotion(doc)
        self.assertEqual(out.episode_count, 1)
        self.assertEqual(out.episodes[0].number, 1)
        self.assertEqual(out.total_cues.count, 2)

    def test_global_budget_across_episodes(self):
        doc = parse_text('1화\n\n단서.\n\n2화\n\n진실.')
        with self.assertRaises(ReferenceParseError):
            analyze_reference_foreshadow_emotion(doc, max_cues=1)
        self.assertEqual(analyze_reference_foreshadow_emotion(doc, max_cues=2).total_cues.count, 2)

    def test_zero_cues_later_episode_allowed_after_budget_exhausted(self):
        doc = parse_text('1화\n\n단서.\n\n2화\n\n그들은 걸었다.')
        out = analyze_reference_foreshadow_emotion(doc, max_cues=1)
        self.assertEqual(out.total_cues.count, 1)

    def test_invalid_document(self):
        for document in (None, 'text', {}, [], 4):
            with self.subTest(v=type(document)), self.assertRaises(ReferenceParseError):
                analyze_reference_foreshadow_emotion(document)

    def test_stale_split_rejected(self):
        doc = parse_text('1화\n\n단서가 있었다.')
        split = split_episodes(parse_text('1화\n\n행복했다.\n\n2화\n\n진실이다.'))
        with self.assertRaises(ReferenceParseError):
            analyze_reference_foreshadow_emotion(doc, split=split)

    def test_match_measure_reference_stats(self):
        from ai_novel_factory.references.basic_statistics import measure_reference
        doc = parse_text('1화\n\n단서가 있었다.\n\n행복했다.\n\n2화\n\n불안했다.')
        baseline = measure_reference(doc)
        out = analyze_reference_foreshadow_emotion(doc)
        for ep, stat in zip(out.episodes, baseline.episodes):
            self.assertEqual(ep.paragraph_count, stat.statistics.paragraphs)
            self.assertEqual(ep.characters_no_whitespace, stat.statistics.characters_no_whitespace)

    def test_total_emotion_balance_uses_cues_not_episode_average(self):
        doc = parse_text('1화\n\n행복. 행복. 행복.\n\n2화\n\n불안.')
        out = analyze_reference_foreshadow_emotion(doc)
        self.assertEqual(out.overall_emotion_balance, .5)
        self.assertEqual(out.total_cues.positive, 3)
        self.assertEqual(out.total_cues.negative, 1)

    def test_no_source_text_in_records(self):
        doc = parse_text('1화\n\n수상한 단서가 비밀이었다.\n\n2화\n\n진실을 밝힌 고유비밀텍스트.')
        out = analyze_reference_foreshadow_emotion(doc)
        for token in ('고유비밀텍스트', '수상한 단서가', '진실을 밝힌'):
            self.assertNotIn(token, repr(out))
            self.assertNotIn(token, str(dataclasses.asdict(out)))

    def test_input_not_mutated(self):
        doc = parse_text('1화\n\n단서가 있었다.')
        before = repr(doc.blocks), doc.text
        analyze_reference_foreshadow_emotion(doc)
        self.assertEqual((repr(doc.blocks), doc.text), before)

    def test_existing_stage22_and_27_unchanged(self):
        from ai_novel_factory.references.episode_structure import analyze_reference_structure
        doc = parse_text('1화\n\n단서가 있었다.\n\n2화\n\n진실이 드러났다.')
        reference = analyze_reference_foreshadow_emotion(doc)
        previous = analyze_reference_structure(doc)
        self.assertEqual([e.number for e in reference.episodes], [e.number for e in previous.episodes])

    def test_reject_oversize_reference(self):
        doc = parse_text('1화\n\n' + '가' * (MAX_ANALYZED_TEXT_CHARS + 1))
        with self.assertRaises(ReferenceParseError):
            analyze_reference_foreshadow_emotion(doc)

    def test_invalid_reference_budget(self):
        doc = parse_text('1화\n\n단서.')
        for n in (0, True, MAX_FORESHADOW_EMOTION_CUES + 1, '4'):
            with self.subTest(n=n), self.assertRaises(ReferenceParseError):
                analyze_reference_foreshadow_emotion(doc, max_cues=n)


if __name__ == '__main__':
    unittest.main()
