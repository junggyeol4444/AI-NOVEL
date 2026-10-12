"""Stage 21 local, deterministic quotation statistics regression tests."""
import dataclasses
import unittest

from ai_novel_factory.references import (
    ParsedReference, ParsedBlock, ReferenceParseError, measure_dialogue_text,
    measure_dialogue_reference, measure_reference, parse_text, split_episodes,
)


class DialogueTextTests(unittest.TestCase):
    def test_straight_double_quotes(self):
        s = measure_dialogue_text('"안녕하세요." 그는 웃었다.')
        self.assertEqual(s.dialogue_characters, len('"안녕하세요."'))
        self.assertEqual(s.total_characters, len('"안녕하세요."그는웃었다.'))
        self.assertEqual(s.dialogue_characters + s.narration_characters, s.total_characters)

    def test_korean_curly_and_corner_quotes(self):
        s = measure_dialogue_text('“어서 와.” 그가 말했다.\n\n「반갑다!」')
        self.assertEqual(s.dialogue_characters, len('“어서와.”')+len('「반갑다!」'))
        self.assertEqual(s.paragraphs, 2)
        self.assertEqual(s.unclosed_quote_paragraphs, 0)

    def test_nested_quotes(self):
        s = measure_dialogue_text('“그는 『기다려』라고 말했다.”')
        self.assertEqual(s.dialogue_characters, s.total_characters)
        self.assertEqual(s.dialogue_ratio, 1.0)

    def test_single_quoted_thought_is_narration(self):
        s = measure_dialogue_text("'이건 생각이야.' 라고 혼잣말했다.")
        self.assertEqual(s.dialogue_characters, 0)
        self.assertEqual(s.narration_ratio, 1.0)

    def test_unbalanced_quotes_are_not_dialogue(self):
        s = measure_dialogue_text('“닫히지 않은 대화')
        self.assertEqual(s.dialogue_characters, 0)
        self.assertEqual(s.unclosed_quote_paragraphs, 1)

    def test_mixed_complete_and_incomplete_quotes(self):
        s = measure_dialogue_text('“완성” 다음 “미완성')
        self.assertEqual(s.dialogue_characters, len('“완성”'))
        self.assertEqual(s.unclosed_quote_paragraphs, 1)

    def test_unclosed_quote_does_not_leak_into_next_paragraph(self):
        s = measure_dialogue_text('“미완성\n\n다음 문단.')
        self.assertEqual(s.dialogue_characters, 0)
        self.assertEqual(s.paragraphs, 2)
        self.assertEqual(s.unclosed_quote_paragraphs, 1)

    def test_escaped_straight_quote_ignored(self):
        s = measure_dialogue_text(r'\"닫히지않음')
        self.assertEqual(s.dialogue_characters, 0)
        self.assertEqual(s.unclosed_quote_paragraphs, 0)

    def test_whitespace_not_counted(self):
        s = measure_dialogue_text('“가 나”   서 술')
        self.assertEqual(s.total_characters, len('“가나”서술'))
        self.assertEqual(s.dialogue_characters, len('“가나”'))

    def test_empty_input(self):
        s = measure_dialogue_text(' \n\n   ')
        self.assertEqual((s.total_characters, s.dialogue_ratio, s.narration_ratio), (0, 0.0, 0.0))
        self.assertEqual(s.paragraphs, 0)

    def test_bad_type(self):
        with self.assertRaises(ReferenceParseError):
            measure_dialogue_text(None)

    def test_no_source_exposure_and_immutable(self):
        s = measure_dialogue_text('“비밀 원고 내용”')
        self.assertNotIn('비밀', repr(s))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            s.dialogue_ratio = 0.2

    def test_deterministic(self):
        text = '“첫 장면.” 고개를 끄덕였다.\n\n“좋아.”'
        self.assertEqual(measure_dialogue_text(text), measure_dialogue_text(text))


class DialogueReferenceTests(unittest.TestCase):
    def test_multi_episode_and_preface(self):
        d = parse_text('작품 안내\n\n1화\n\n“첫 대사!”\n\n서술.\n\n2화\n\n“두번째!”')
        r = measure_dialogue_reference(d)
        self.assertEqual([e.number for e in r.episodes], [1, 2])
        self.assertEqual(r.preface.total_characters, len('작품안내'))
        self.assertEqual(r.preface.dialogue_characters, 0)
        self.assertEqual(r.episodes[0].counts.dialogue_characters, len('“첫대사!”'))
        self.assertEqual(r.total.total_characters, measure_reference(d).total.characters_no_whitespace)

    def test_single_episode_without_markers(self):
        d = parse_text('“대사.” 그리고 이어진 서술.')
        r = measure_dialogue_reference(d)
        self.assertEqual(len(r.episodes), 1)
        self.assertEqual(r.preface.total_characters, 0)

    def test_markdown_code_excluded(self):
        d = parse_text('## 1화\n\n“실제 대사”\n\n```\n“코드의 따옴표”\n```', format='markdown')
        s = measure_dialogue_reference(d)
        self.assertEqual(s.total.dialogue_characters, len('“실제대사”'))

    def test_docx_table_and_pdf(self):
        for fmt in ('docx','pdf'):
            d = ParsedReference(fmt, None, '', (
                ParsedBlock('heading', 1, 1, '1화', 1),
                ParsedBlock('paragraph', 2, 2, '그가 인사했다.'),
                ParsedBlock('table', 3, 3, '“안녕!”\t대답'),
            ))
            r = measure_dialogue_reference(d)
            self.assertEqual(r.total.total_characters, measure_reference(d).total.characters_no_whitespace)
            self.assertEqual(r.total.dialogue_characters, len('“안녕!”'))

    def test_stale_split_rejected(self):
        d = parse_text('1화\n\n“한번”')
        bad = split_episodes(parse_text('1화\n\n“다른 내용”'))
        with self.assertRaises(ReferenceParseError):
            measure_dialogue_reference(d, split=bad)

    def test_wrong_doc_rejected(self):
        with self.assertRaises(ReferenceParseError):
            measure_dialogue_reference('raw text')


if __name__ == '__main__':
    unittest.main()
