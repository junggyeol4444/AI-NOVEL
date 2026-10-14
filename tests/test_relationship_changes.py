"""Stage 27: local-only, observable interaction-cue changes."""
import unittest
from dataclasses import FrozenInstanceError

from ai_novel_factory.references.character_roles import CharacterSpec
from ai_novel_factory.references.relationship_changes import (
    MAX_PAIR_OBSERVATIONS, MAX_PAIR_DISTANCE, analyze_relationship_text,
    analyze_reference_relationships,
)
from ai_novel_factory.references.episode_splitter import split_episodes
from ai_novel_factory.references.plaintext_parser import parse_text, ReferenceParseError


def cast():
    return [CharacterSpec('hero', ('하린',)), CharacterSpec('foe', ('태수',))]


class OneEpisodeTests(unittest.TestCase):
    def test_positive_sentence(self):
        result = analyze_relationship_text('하린은 태수를 도와주었다.', cast())
        self.assertEqual(result.number, 1)
        self.assertEqual(result.joint_sentence_observations, 1)
        pair = result.pairs[0]
        self.assertEqual(pair.character_ids, ('foe', 'hero'))
        self.assertEqual((pair.joint_sentences, pair.positive_cues, pair.negative_cues,
                          pair.neutral_cues, pair.cue_balance), (1, 1, 0, 0, 1.0))

    def test_negative_sentence(self):
        row = analyze_relationship_text('태수가 하린을 공격했다.', cast()).pairs[0]
        self.assertEqual((row.positive_cues, row.negative_cues, row.cue_balance), (0, 1, -1.0))

    def test_neutral_sentence(self):
        row = analyze_relationship_text('하린이 태수를 바라보았다.', cast()).pairs[0]
        self.assertEqual((row.neutral_cues, row.cue_balance), (1, 0.0))

    def test_mixed_sentence_has_two_cue_flags(self):
        row = analyze_relationship_text('하린과 태수는 협력하다 배신했다.', cast()).pairs[0]
        self.assertEqual((row.joint_sentences, row.positive_cues, row.negative_cues,
                          row.neutral_cues, row.cue_balance), (1, 1, 1, 0, 0.0))

    def test_two_characters_in_separate_sentences_do_not_match(self):
        result = analyze_relationship_text('하린은 도왔다. 태수는 웃었다.', cast())
        self.assertEqual((result.joint_sentence_observations, len(result.pairs)), (0, 0))

    def test_two_characters_in_separate_paragraphs_do_not_match(self):
        result = analyze_relationship_text('하린은 웃었다.\n\n태수는 웃었다.', cast())
        self.assertEqual(len(result.pairs), 0)

    def test_two_characters_in_separate_lines_do_not_match(self):
        result = analyze_relationship_text('하린은 웃었다\n태수는 웃었다', cast())
        self.assertEqual(len(result.pairs), 0)

    def test_sentence_punctuation_keeps_quotes(self):
        result = analyze_relationship_text('하린이 말했다. "태수를 믿는다."\n태수는 갔다.', cast())
        self.assertEqual(len(result.pairs), 0)

    def test_nearby_threshold(self):
        result = analyze_relationship_text('하린 ' + '나' * MAX_PAIR_DISTANCE + ' 태수는 떠났다.', cast())
        self.assertEqual(len(result.pairs), 0)
        short = analyze_relationship_text('하린 ' + '나' * 20 + ' 태수는 떠났다.', cast())
        self.assertEqual(len(short.pairs), 1)

    def test_three_characters_make_three_pairs(self):
        crew = cast() + [CharacterSpec('third', ('민지',))]
        result = analyze_relationship_text('하린은 태수와 민지를 도왔다.', crew)
        self.assertEqual(result.joint_sentence_observations, 3)
        self.assertEqual(tuple(p.character_ids for p in result.pairs),
                         (('foe', 'hero'), ('foe', 'third'), ('hero', 'third')))

    def test_alias_overlap_not_double_counted(self):
        crew = [CharacterSpec('hero', ('하린', '린')), CharacterSpec('foe', ('태수',))]
        result = analyze_relationship_text('하린은 태수를 도왔다.', crew)
        self.assertEqual(result.joint_sentence_observations, 1)

    def test_repeated_pair_in_same_sentence_counts_once(self):
        result = analyze_relationship_text('하린과 태수가 떠났고 하린과 태수가 다시 만났다.', cast())
        self.assertEqual(result.pairs[0].joint_sentences, 1)

    def test_repeated_pair_across_sentences(self):
        result = analyze_relationship_text('하린과 태수는 협력했다. 하린과 태수는 다퉜다.', cast())
        self.assertEqual(result.pairs[0].joint_sentences, 2)
        self.assertEqual(result.pairs[0].cue_balance, 0.0)

    def test_requires_explicit_characters(self):
        with self.assertRaises(ReferenceParseError):
            analyze_relationship_text('하린과 태수', [])

    def test_single_character_is_ok(self):
        result = analyze_relationship_text('하린은 웃었다.', cast()[:1])
        self.assertEqual(result.pairs, ())

    def test_invalid_number(self):
        for value in (0, -1, 10001, True, '1'):
            with self.subTest(value=value), self.assertRaises(ReferenceParseError):
                analyze_relationship_text('하린은 태수를 도왔다.', cast(), number=value)

    def test_invalid_budget(self):
        for value in (0, -1, True, '2', MAX_PAIR_OBSERVATIONS + 1):
            with self.subTest(value=value), self.assertRaises(ReferenceParseError):
                analyze_relationship_text('하린은 태수를 도왔다.', cast(), max_observations=value)

    def test_budget_overflow(self):
        with self.assertRaises(ReferenceParseError):
            analyze_relationship_text('하린과 태수. 하린과 태수.', cast(), max_observations=1)

    def test_budget_equal_accepted(self):
        result = analyze_relationship_text('하린과 태수. 하린과 태수.', cast(), max_observations=2)
        self.assertEqual(result.joint_sentence_observations, 2)

    def test_invalid_text(self):
        for val in (None, b'content', {}, 5):
            with self.subTest(val=val), self.assertRaises(ReferenceParseError):
                analyze_relationship_text(val, cast())

    def test_oversize_text_rejected(self):
        with self.assertRaises(ReferenceParseError):
            analyze_relationship_text('가' * 2_000_001, cast())

    def test_unknown_id_rejected(self):
        with self.assertRaises(ReferenceParseError):
            analyze_relationship_text('하린과 태수', [CharacterSpec('bad/name', ('하린',))])

    def test_cannot_mutate_result(self):
        result = analyze_relationship_text('하린은 태수를 도왔다.', cast())
        with self.assertRaises(FrozenInstanceError):
            result.number = 42

    def test_no_source_alias_in_repr(self):
        result = analyze_relationship_text('비밀별명하린이 비밀별명태수를 도왔다.', [
            CharacterSpec('a', ('비밀별명하린',)), CharacterSpec('b', ('비밀별명태수',))])
        for token in ('비밀별명하린', '비밀별명태수', '도왔다'):
            self.assertNotIn(token, repr(result))

    def test_deterministic(self):
        a = analyze_relationship_text('하린이 태수를 믿었고 태수는 하린을 도왔다.', cast())
        b = analyze_relationship_text('하린이 태수를 믿었고 태수는 하린을 도왔다.', cast())
        self.assertEqual(a, b)

    def test_no_signal_without_pair_even_if_positive_word(self):
        self.assertEqual(analyze_relationship_text('협력했다. 하린은 나갔다. 태수도 나갔다.',cast()).pairs, ())

    def test_co_mention_without_positive_word_keeps_neutral(self):
        p = analyze_relationship_text('하린과 태수가 함께 걸었다.', cast()).pairs[0]
        self.assertEqual(p.neutral_cues, 1)


class ReferenceTests(unittest.TestCase):
    def test_two_episode_positive_to_negative(self):
        doc = parse_text('1화\n\n하린이 태수를 도왔다.\n\n2화\n\n태수가 하린을 배신했다.')
        result = analyze_reference_relationships(doc, cast())
        self.assertEqual(result.episode_count, 2)
        self.assertEqual(result.total_joint_sentence_observations, 2)
        self.assertEqual(len(result.pairs), 1)
        self.assertEqual(result.pairs[0].episodes_present, 2)
        change = result.adjacent_changes[0]
        self.assertEqual((change.from_episode, change.to_episode), (1, 2))
        self.assertEqual((change.previous_cue_balance, change.current_cue_balance), (1.0, -1.0))
        self.assertEqual(change.signal, 'more_negative_cues')

    def test_two_episode_negative_to_positive(self):
        doc = parse_text('1화\n\n하린과 태수가 싸웠다.\n\n2화\n\n하린이 태수를 도왔다.')
        res = analyze_reference_relationships(doc, cast())
        self.assertEqual(res.adjacent_changes[0].signal, 'more_positive_cues')

    def test_first_joint_mention(self):
        doc = parse_text('1화\n\n하린만 등장했다.\n\n2화\n\n하린과 태수가 만났다.')
        result = analyze_reference_relationships(doc, cast())
        self.assertEqual(result.adjacent_changes[0].signal, 'first_joint_mention')

    def test_stopped_joint_mention(self):
        doc = parse_text('1화\n\n하린과 태수가 만났다.\n\n2화\n\n태수만 등장했다.')
        result = analyze_reference_relationships(doc, cast())
        self.assertEqual(result.adjacent_changes[0].signal, 'stopped_joint_mention')

    def test_same_cue_balance(self):
        doc = parse_text('1화\n\n하린과 태수가 만났다.\n\n2화\n\n하린과 태수가 다시 만났다.')
        self.assertEqual(analyze_reference_relationships(doc, cast()).adjacent_changes[0].signal,
                         'unchanged_cue_balance')

    def test_preface_excluded(self):
        doc = parse_text('서문: 하린이 태수를 배신했다.\n\n1화\n\n하린이 혼자 떠났다.')
        result = analyze_reference_relationships(doc, cast())
        self.assertEqual(result.total_joint_sentence_observations, 0)

    def test_markdown_fence_and_heading_excluded(self):
        doc = parse_text('## 1화\n\n하린은 나갔다.\n\n```\n하린과 태수가 협력했다.\n```', format='markdown')
        self.assertEqual(analyze_reference_relationships(doc, cast()).pairs, ())

    def test_stale_split_rejected(self):
        doc = parse_text('1화\n\n하린과 태수가 갔다.')
        other = split_episodes(parse_text('1화\n\n태수와 하린이 갔다.\n\n2화\n\n끝'))
        with self.assertRaises(ReferenceParseError):
            analyze_reference_relationships(doc, cast(), split=other)

    def test_no_episode_markers_single_episode(self):
        doc = parse_text('하린과 태수가 함께 떠났다.')
        result = analyze_reference_relationships(doc, cast())
        self.assertEqual(result.episode_count, 1)
        self.assertEqual(result.pairs[0].first_episode, 1)
        self.assertEqual(result.adjacent_changes, ())

    def test_no_pairs_if_no_cooccurrence(self):
        doc = parse_text('1화\n\n하린만 왔다.\n\n2화\n\n태수만 왔다.')
        result = analyze_reference_relationships(doc, cast())
        self.assertEqual((result.pairs, result.adjacent_changes), ((), ()))

    def test_budget_across_episodes(self):
        doc = parse_text('1화\n\n하린과 태수.\n\n2화\n\n하린과 태수.')
        with self.assertRaises(ReferenceParseError):
            analyze_reference_relationships(doc, cast(), max_observations=1)

    def test_invalid_doc(self):
        for bad in (None, '', {}, []):
            with self.subTest(bad=type(bad)), self.assertRaises(ReferenceParseError):
                analyze_reference_relationships(bad, cast())

    def test_preserves_non_contiguous_original_numbers(self):
        doc = parse_text('3화\n\n하린과 태수는 만났다.\n\n5화\n\n하린과 태수는 만났다.')
        res = analyze_reference_relationships(doc, cast())
        self.assertEqual((res.episodes[0].number, res.episodes[1].number), (3, 5))
        self.assertEqual((res.adjacent_changes[0].from_episode, res.adjacent_changes[0].to_episode), (3, 5))

    def test_no_original_text_leak(self):
        doc = parse_text('1화\n\n비밀하린은 비밀태수를 공격했다.')
        res = analyze_reference_relationships(doc, [
            CharacterSpec('a', ('비밀하린',)), CharacterSpec('b', ('비밀태수',))])
        self.assertNotIn('비밀하린', repr(res))
        self.assertNotIn('비밀태수', repr(res))
        self.assertNotIn('공격했다', repr(res))

    def test_unchanged_input(self):
        doc = parse_text('하린과 태수가 만났다.')
        original = doc.text
        analyze_reference_relationships(doc, cast())
        self.assertEqual(doc.text, original)

    def test_existing_character_role_consistency(self):
        from ai_novel_factory.references.character_roles import analyze_reference_character_roles
        doc = parse_text('1화\n\n하린과 태수가 협력했다.\n\n2화\n\n태수만 떠났다.')
        roles = analyze_reference_character_roles(doc, cast())
        relationships = analyze_reference_relationships(doc, cast())
        self.assertEqual(roles.episode_count, relationships.episode_count)
        self.assertEqual(relationships.total_joint_sentence_observations, 1)


if __name__ == '__main__':
    unittest.main()
