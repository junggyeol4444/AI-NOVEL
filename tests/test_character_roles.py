"""Stage 26: character mention/role-hint regression tests (no source persistence)."""
import dataclasses
import unittest

from ai_novel_factory.references import (
    CharacterSpec, ReferenceParseError, analyze_character_text,
    analyze_reference_character_roles, parse_text, split_episodes,
)


def sample():
    return [CharacterSpec('hero', ('하린',)), CharacterSpec('foe', ('태수',))]


class CharacterTextTests(unittest.TestCase):
    def test_particle_aware_korean_mentions(self):
        v = analyze_character_text('하린은 떠났다. 하린이 왔다. 하린에게 말했다. 태수는 웃었다.', sample())
        self.assertEqual(dict(v.mentions), {'hero': 3, 'foe': 1})

    def test_no_substring_false_positive(self):
        v = analyze_character_text('하린별, 김하린, 태수성. 하린은.', sample())
        self.assertEqual(dict(v.mentions), {'hero': 1, 'foe': 0})

    def test_english_word_boundaries_and_casefold(self):
        v = analyze_character_text('Ann met ANN. Annie cannot be Annabelle.', [CharacterSpec('c1', ('Ann',))])
        self.assertEqual(dict(v.mentions), {'c1': 2})

    def test_no_diacritic_or_unicode_equivalence_assumptions(self):
        v = analyze_character_text('Anne met Ana.', [CharacterSpec('one', ('Ann',))])
        self.assertEqual(v.total_mentions, 0)

    def test_multiple_aliases_same_person(self):
        v = analyze_character_text('하린은 말했다. 윤하린도 말했다.', [CharacterSpec('hero', ('하린', '윤하린'))])
        self.assertEqual(v.total_mentions, 2)

    def test_alias_collision_rejected(self):
        with self.assertRaises(ReferenceParseError):
            analyze_character_text('하린은', [CharacterSpec('a', ('하린',)), CharacterSpec('b', ('하린',))])

    def test_casefold_alias_collision_rejected(self):
        with self.assertRaises(ReferenceParseError):
            analyze_character_text('Ann', [CharacterSpec('a', ('Ann',)), CharacterSpec('b', ('ann',))])

    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ReferenceParseError):
            analyze_character_text('하린', [CharacterSpec('a', ('하린',)), CharacterSpec('a', ('태수',))])

    def test_bad_ids_rejected(self):
        for bad in ('../folder', '1hero', 'has space', '', '가'):
            with self.subTest(bad=bad), self.assertRaises(ReferenceParseError):
                analyze_character_text('하린', [CharacterSpec(bad, ('하린',))])

    def test_blank_alias_rejected(self):
        for aliases in ((), ('',), (' ',), ('\n',), ('하린\n',)):
            with self.subTest(aliases=aliases), self.assertRaises(ReferenceParseError):
                analyze_character_text('하린', [CharacterSpec('one', aliases)])

    def test_invalid_spec_type_rejected(self):
        for bad in (None, 42, [], {}, 'hello', [None], [dict(id='x')]):
            with self.subTest(value=repr(bad)), self.assertRaises(ReferenceParseError):
                analyze_character_text('하린', bad)

    def test_empty_text_zero_metrics(self):
        result = analyze_character_text(' ', sample())
        self.assertEqual(result.total_mentions, 0)
        self.assertEqual(dict(result.mentions), {'hero': 0, 'foe': 0})

    def test_no_raw_name_in_output_repr(self):
        result = analyze_character_text('비밀이름수현은 갔다.', [CharacterSpec('c001', ('비밀이름수현',))])
        self.assertNotIn('비밀이름수현', repr(result))
        self.assertIn('c001', repr(result))

    def test_spec_repr_redacts_aliases(self):
        self.assertNotIn('비밀이름수현', repr(CharacterSpec('id', ('비밀이름수현',))))

    def test_immutable_result(self):
        result = analyze_character_text('하린', sample())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.total_mentions = 5

    def test_deterministic(self):
        self.assertEqual(analyze_character_text('하린과 태수',sample()), analyze_character_text('하린과 태수',sample()))

    def test_role_prefix_explicit(self):
        result=analyze_character_text('주인공 하린은 떠났다. 악역 태수는 막았다.', sample())
        self.assertEqual(result.explicit_role_hints, (('foe','antagonist',1), ('hero','protagonist',1)))

    def test_role_suffix_explicit(self):
        result=analyze_character_text('하린은 주인공이다. 태수는 악역이었다.', sample())
        self.assertEqual(result.explicit_role_hints, (('foe','antagonist',1), ('hero','protagonist',1)))

    def test_role_object_is_not_assignment(self):
        result=analyze_character_text('하린은 악역을 싫어했다. 태수는 스승을 만났다.', sample())
        self.assertEqual(result.explicit_role_hints, ())

    def test_role_merely_far_away_is_not_evidence(self):
        result=analyze_character_text('악역은 저기 있었다. 하린은 도망갔다.', sample())
        self.assertEqual(result.explicit_role_hints, ())

    def test_character_name_with_regex_symbols_is_escaped(self):
        result=analyze_character_text('R.A.가 웃었다.', [CharacterSpec('x', ('R.A.',))])
        self.assertEqual(result.total_mentions,1)

    def test_marker_budget(self):
        with self.assertRaises(ReferenceParseError):
            analyze_character_text('하린 하린 하린', sample(), max_mentions=2)

    def test_bad_budgets(self):
        for budget in (0, True, 20001, -1, '2'):
            with self.subTest(budget=budget),self.assertRaises(ReferenceParseError):
                analyze_character_text('하린', sample(), max_mentions=budget)

    def test_invalid_number(self):
        for number in (0, -2, True, 10001, 'a'):
            with self.subTest(number=number),self.assertRaises(ReferenceParseError):
                analyze_character_text('하린', sample(), number=number)


class ReferenceCharacterTests(unittest.TestCase):
    def test_multi_episode_mentions_and_coverage(self):
        doc=parse_text('1화\n\n주인공 하린은 웃었다. 하린은 또 웃었다.\n\n2화\n\n하린은 떠났다. 태수는 남았다.')
        output=analyze_reference_character_roles(doc,sample())
        self.assertEqual(output.episode_count,2)
        self.assertEqual(output.total_mentions,4)
        self.assertEqual([x.total_mentions for x in output.episodes], [2,2])
        first,second=output.characters
        self.assertEqual((first.character_id,first.mentions,first.episodes_present,first.episode_coverage), ('hero',3,2,1.0))
        self.assertEqual(first.prominence,'central_candidate')
        self.assertEqual(second.prominence,'minor_candidate')
        self.assertEqual(first.explicit_role_hints, (('protagonist',1),))

    def test_excludes_preface(self):
        doc=parse_text('서문에서 하린은 등장한다.\n\n1화\n\n태수가 웃었다.')
        result=analyze_reference_character_roles(doc,sample())
        self.assertEqual(dict((x.character_id,x.mentions) for x in result.characters), {'hero':0,'foe':1})

    def test_excludes_heading_and_code(self):
        doc=parse_text('## 1화\n\n하린은 웃었다.\n\n```\n하린은 비밀코드에\n```',format='markdown')
        self.assertEqual(analyze_reference_character_roles(doc,sample()).total_mentions,1)

    def test_without_markers_single_episode(self):
        doc=parse_text('하린과 태수는 이야기했다.')
        output=analyze_reference_character_roles(doc,sample())
        self.assertEqual((output.episode_count,output.total_mentions),(1,2))

    def test_unused_character_not_detected(self):
        doc=parse_text('하린은 떠났다.')
        result=analyze_reference_character_roles(doc,sample())
        self.assertEqual(result.characters[1].prominence,'not_detected')

    def test_stale_split_rejected(self):
        doc=parse_text('1화\n\n하린은 갔다.')
        other=split_episodes(parse_text('1화\n\n태수가 갔다.\n\n2화\n\n끝났다.'))
        with self.assertRaises(ReferenceParseError):
            analyze_reference_character_roles(doc,sample(),split=other)

    def test_invalid_doc(self):
        for bad in (None,[],{}, 'abc'):
            with self.subTest(value=str(type(bad))),self.assertRaises(ReferenceParseError):
                analyze_reference_character_roles(bad,sample())

    def test_cumulative_budget_across_episodes(self):
        doc=parse_text('1화\n\n하린은 갔다.\n\n2화\n\n하린은 왔다.')
        with self.assertRaises(ReferenceParseError):
            analyze_reference_character_roles(doc,sample(),max_mentions=1)

    def test_role_counts_across_episodes(self):
        doc=parse_text('1화\n\n악역 태수는 왔다.\n\n2화\n\n태수는 악역이었다.')
        roles=analyze_reference_character_roles(doc,sample())
        self.assertEqual(roles.characters[1].explicit_role_hints,(('antagonist',2),))

    def test_no_names_or_snippets_in_result(self):
        doc=parse_text('1화\n\n비밀별명하린은 나왔다.')
        roles=analyze_reference_character_roles(doc,[CharacterSpec('h',('비밀별명하린',))])
        self.assertNotIn('비밀별명하린',repr(roles))
        self.assertNotIn('나왔다',repr(roles))

    def test_only_body_not_metadata(self):
        doc=parse_text('### 주인공 하린\n\n1화\n\n태수는 웃었다.',format='markdown')
        roles=analyze_reference_character_roles(doc,sample())
        self.assertEqual(roles.total_mentions,1)

    def test_empty_episode_is_valid(self):
        doc=parse_text('1화\n\n2화\n\n하린이 왔다.')
        roles=analyze_reference_character_roles(doc,sample())
        self.assertEqual(roles.episodes[0].total_mentions,0)

    def test_output_no_unvalidated_identifiers(self):
        doc=parse_text('하린은 나왔다.')
        with self.assertRaises(ReferenceParseError):
            analyze_reference_character_roles(doc,[CharacterSpec('path/a',('하린',))])


if __name__ == '__main__':
    unittest.main()
