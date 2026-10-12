"""Stage 18: numerical, source-free statistics regression tests."""
import dataclasses
import unittest

from ai_novel_factory.references import (
    ParsedBlock, ParsedReference, ReferenceParseError,
    measure_reference, measure_text, parse_text, split_episodes,
)


class TextStatisticTests(unittest.TestCase):
    def test_korean_sentences(self):
        s = measure_text("안녕하세요! 반갑습니다.\n\n오늘도 좋은 하루")
        self.assertEqual((s.sentences, s.paragraphs, s.words), (3, 2, 5))

    def test_empty_input(self):
        s = measure_text(" \n\n ")
        self.assertEqual((s.characters, s.words, s.sentences, s.paragraphs), (0, 0, 0, 0))
        self.assertEqual(s.average_sentence_characters, 0)
        self.assertEqual(s.average_paragraph_characters, 0)

    def test_decimal_not_sentence(self):
        self.assertEqual(measure_text("가격은 3.14원이다. 확인했다!").sentences, 2)

    def test_ellipsis_only_one_sentence(self):
        self.assertEqual(measure_text("왜... 정말?").sentences, 2)

    def test_closing_quotes(self):
        self.assertEqual(measure_text('"좋아." 그리고 떠났다.').sentences, 2)

    def test_unpunctuated_counts_sentence(self):
        self.assertEqual(measure_text("끝맺음 없는 문장").sentences, 1)

    def test_whitespace_length(self):
        s = measure_text("가 나\n\n 다")
        self.assertEqual((s.characters, s.characters_no_whitespace, s.words, s.paragraphs), (4, 3, 3, 2))

    def test_bad_type(self):
        with self.assertRaises(ReferenceParseError):
            measure_text(123)

    def test_result_has_no_original_text(self):
        s = measure_text("비밀 원고! 확인한다.")
        self.assertNotIn("비밀", repr(s))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            s.words = 1


class ReferenceStatisticTests(unittest.TestCase):
    def test_two_episodes_exclude_headings(self):
        d = parse_text("제1화 출발\n\n첫 장면.\n\n제2화 전개\n\n두 번째 장면!")
        s = measure_reference(d)
        self.assertEqual(s.episode_count, 2)
        self.assertEqual([e.number for e in s.episodes], [1, 2])
        self.assertEqual(s.total.paragraphs, 2)
        self.assertEqual(s.total.sentences, 2)
        self.assertEqual(
            s.total.characters_no_whitespace,
            sum(x.statistics.characters_no_whitespace for x in s.episodes),
        )
        self.assertNotIn("장면", repr(s))

    def test_preface_separate_from_episode_length(self):
        d = parse_text("작품 안내\n\n1화\n\n안녕하세요.")
        s = measure_reference(d)
        self.assertEqual(s.preface.paragraphs, 1)
        self.assertEqual(s.total.paragraphs, 2)
        self.assertEqual(s.episodes[0].statistics.paragraphs, 1)
        self.assertEqual(
            s.average_episode_characters,
            s.episodes[0].statistics.characters_no_whitespace,
        )

    def test_no_heading_single_episode(self):
        d = parse_text("첫 문단.\n\n둘째 문단.")
        s = measure_reference(d)
        self.assertEqual((s.episode_count, s.total.paragraphs, s.total.sentences), (1, 2, 2))
        self.assertEqual(s.preface.paragraphs, 0)

    def test_markdown_code_and_headings_ignored(self):
        fence = "~" * 3
        d = parse_text(
            "# 안내\n\n" + fence + "\n비공개 1화\n" + fence + "\n\n## 1화\n\n본문 한 줄.",
            format="markdown",
        )
        s = measure_reference(d)
        self.assertEqual(s.episode_count, 1)
        self.assertEqual(s.total.paragraphs, 1)
        self.assertEqual(s.total.words, 3)

    def test_table_in_docx_counted(self):
        d = ParsedReference("docx", None, "", (
            ParsedBlock("heading", 1, 1, "1화", 1),
            ParsedBlock("paragraph", 2, 2, "안녕하세요."),
            ParsedBlock("table", 3, 3, "이름\t나이\n민수\t20"),
        ))
        s = measure_reference(d)
        self.assertEqual(s.total.paragraphs, 2)
        self.assertEqual(s.episode_count, 1)

    def test_pdf_block_order(self):
        d = ParsedReference("pdf", None, "", (
            ParsedBlock("paragraph", 1, 1, "1화"),
            ParsedBlock("paragraph", 1, 1, "첫 번째. 다시."),
            ParsedBlock("paragraph", 2, 2, "2화"),
            ParsedBlock("paragraph", 2, 2, "세 번째."),
        ))
        self.assertEqual([e.statistics.sentences for e in measure_reference(d).episodes], [2, 1])

    def test_no_mutation(self):
        d = parse_text("1화\n\n소중한 원문\n\n2화\n\n다음 원문")
        prior = d.text
        s = measure_reference(d, split=split_episodes(d))
        self.assertEqual(d.text, prior)
        self.assertNotIn(prior, repr(s))

    def test_invalid_doc(self):
        with self.assertRaises(ReferenceParseError):
            measure_reference("not document")

    def test_invalid_episode_slice(self):
        d = parse_text("1화\n\n내용")
        mismatched = split_episodes(parse_text("1화\n\n내용\n\n2화\n\n다른 내용"))
        with self.assertRaises(ReferenceParseError):
            measure_reference(d, split=mismatched)


if __name__ == "__main__":
    unittest.main()
