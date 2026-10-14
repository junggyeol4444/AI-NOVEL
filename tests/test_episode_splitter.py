"""Stage 17 split behavior and safety regression tests."""
import unittest
from ai_novel_factory.references import parse_text
from ai_novel_factory.references.episode_splitter import split_episodes
from ai_novel_factory.references.plaintext_parser import ParsedBlock, ParsedReference, ReferenceParseError


class EpisodeSplitTests(unittest.TestCase):
    def test_korean_headings(self):
        doc = parse_text("제1화 시작\n\n첫 장면\n\n제2화 반격\n\n두 번째 장면")
        result = split_episodes(doc)
        self.assertEqual([e.number for e in result.episodes], [1, 2])
        self.assertEqual(result.episodes[1].title, "반격")
        self.assertEqual(result.episodes[0].text, "첫 장면")

    def test_english_markdown(self):
        doc = parse_text("# Episode 1: Start\n\nHello\n\n## Chapter 2 - Next\n\nWorld", format="markdown")
        result = split_episodes(doc)
        self.assertEqual(result.count, 2)
        self.assertEqual(result.episodes[0].title, "Start")

    def test_no_markers_is_one_episode(self):
        doc = parse_text("첫 단락\n\n다음 단락")
        self.assertFalse(split_episodes(doc).detected_markers)
        self.assertEqual(split_episodes(doc).episodes[0].text, "첫 단락\n\n다음 단락")

    def test_preface_not_lost(self):
        doc = parse_text("작품 소개\n\n1화\n\n본문")
        result = split_episodes(doc)
        self.assertEqual(result.preface, "작품 소개")
        self.assertEqual(result.episodes[0].text, "본문")

    def test_not_split_prose_reference(self):
        doc = parse_text("그는 1화의 내용을 떠올렸다.\n\n아무 일도 없었다.")
        self.assertEqual(split_episodes(doc).count, 1)
        self.assertFalse(split_episodes(doc).detected_markers)

    def test_no_split_code_blocks(self):
        doc = parse_text("```\n1화\n```\n\n2화\n\n본문", format="markdown")
        self.assertEqual([e.number for e in split_episodes(doc).episodes], [2])

    def test_nonsequential_supported(self):
        doc = parse_text("10화\n\n본문\n\n12화\n\n결말")
        self.assertEqual([e.number for e in split_episodes(doc).episodes], [10, 12])

    def test_duplicate_rejected(self):
        doc = parse_text("1화\n\n내용\n\n1화\n\n내용")
        with self.assertRaises(ReferenceParseError):
            split_episodes(doc)

    def test_reverse_rejected(self):
        doc = parse_text("3화\n\n내용\n\n2화\n\n내용")
        with self.assertRaises(ReferenceParseError):
            split_episodes(doc)

    def test_limit_enforced(self):
        doc = parse_text("1화\n\n하나\n\n2화\n\n둘")
        with self.assertRaises(ReferenceParseError):
            split_episodes(doc, max_episodes=1)

    def test_invalid_limit(self):
        doc = parse_text("1화\n\n내용")
        for limit in [True, 0, 10001, 1.2]:
            with self.subTest(limit=limit), self.assertRaises(ReferenceParseError):
                split_episodes(doc, max_episodes=limit)

    def test_pdf_style_block_order(self):
        doc = ParsedReference("pdf", None, "", (
            ParsedBlock("paragraph", 1, 1, "제1화"),
            ParsedBlock("paragraph", 1, 1, "첫 페이지"),
            ParsedBlock("paragraph", 2, 2, "제2화"),
            ParsedBlock("paragraph", 2, 2, "다음 페이지"),
        ))
        self.assertEqual(split_episodes(doc).episodes[1].text, "다음 페이지")

    def test_source_not_modified(self):
        doc = parse_text("1화\n\n원문 보존\n\n2화\n\n다음 내용")
        before = doc.text
        split_episodes(doc)
        self.assertEqual(doc.text, before)

    def test_no_markdown_nested_line_false_positive(self):
        doc = parse_text("한 줄 내용\n1화\n다른 줄 내용")
        self.assertFalse(split_episodes(doc).detected_markers)

    def test_incompatible_input(self):
        with self.assertRaises(ReferenceParseError):
            split_episodes("1화")

if __name__ == '__main__':
    unittest.main()
