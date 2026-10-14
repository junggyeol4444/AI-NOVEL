"""Stage 13: synthetic, permission-free TXT/Markdown fixtures only."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_novel_factory.references.plaintext_parser import (
    ReferenceParseError,
    parse_reference_file,
    parse_text,
)


class TestTextParser(unittest.TestCase):
    def test_txt_preserves_korean_and_line_breaks(self) -> None:
        parsed = parse_text("첫 줄\r\n둘째 줄\r\n\r\n셋째 줄\n")
        self.assertEqual(parsed.text, "첫 줄\n둘째 줄\n\n셋째 줄\n")
        self.assertEqual([block.text for block in parsed.blocks], ["첫 줄\n둘째 줄", "셋째 줄"])
        self.assertEqual([(b.start_line, b.end_line) for b in parsed.blocks], [(1, 2), (4, 4)])

    def test_markdown_atx_heading_and_paragraph(self) -> None:
        parsed = parse_text("# 제1화 시작\n\n문장 하나.\n문장 둘.\n\n## 다음 장\n", format="markdown")
        self.assertEqual([b.kind for b in parsed.blocks], ["heading", "paragraph", "heading"])
        self.assertEqual([b.text for b in parsed.blocks], ["제1화 시작", "문장 하나.\n문장 둘.", "다음 장"])
        self.assertEqual([b.heading_level for b in parsed.blocks], [1, None, 2])

    def test_markdown_setext_heading(self) -> None:
        parsed = parse_text("서장\n====\n\n시작.\n", format="markdown")
        self.assertEqual(parsed.blocks[0].kind, "heading")
        self.assertEqual(parsed.blocks[0].heading_level, 1)
        self.assertEqual(parsed.blocks[0].end_line, 2)

    def test_markdown_multiline_setext_heading(self) -> None:
        parsed = parse_text("첫째 줄\n둘째 줄\n---\n\n본문", format="markdown")
        self.assertEqual([b.kind for b in parsed.blocks], ["heading", "paragraph"])
        self.assertEqual(parsed.blocks[0].text, "첫째 줄\n둘째 줄")
        self.assertEqual((parsed.blocks[0].start_line, parsed.blocks[0].end_line), (1, 3))
        self.assertEqual(parsed.blocks[0].heading_level, 2)

    def test_markdown_setext_after_blank_line(self) -> None:
        parsed = parse_text("서론\n\n다음 제목\n===\n\n본문", format="markdown")
        self.assertEqual([b.kind for b in parsed.blocks], ["paragraph", "heading", "paragraph"])
        self.assertEqual(parsed.blocks[1].text, "다음 제목")
        self.assertEqual((parsed.blocks[1].start_line, parsed.blocks[1].end_line), (3, 4))
        self.assertEqual(parsed.blocks[1].heading_level, 1)

    def test_markdown_unattached_rule_is_not_heading(self) -> None:
        parsed = parse_text("---\n\n본문", format="markdown")
        self.assertFalse(any(b.kind == "heading" for b in parsed.blocks))

    def test_markdown_fenced_content_is_not_heading(self) -> None:
        parsed = parse_text("```text\n# 코드 안\n```\n\n본문", format="markdown")
        self.assertEqual([b.kind for b in parsed.blocks], ["code", "paragraph"])
        self.assertEqual(parsed.blocks[0].text, "# 코드 안")

    def test_txt_hash_sign_not_heading(self) -> None:
        parsed = parse_text("# 원문 표기\n계속", format="txt")
        self.assertEqual(parsed.blocks[0].text, "# 원문 표기\n계속")

    def test_empty_and_binary_rejected(self) -> None:
        for value in ("", "  \n  ", "정상\x00바이너리", "x\x01y"):
            with self.subTest(value=repr(value)), self.assertRaises(ReferenceParseError):
                parse_text(value)

    def test_unsupported_format_rejected(self) -> None:
        with self.assertRaises(ReferenceParseError):
            parse_text("본문", format="pdf")

    def test_reprs_do_not_leak_reference_text(self) -> None:
        parsed = parse_text("기밀 원문 샘플")
        self.assertNotIn("기밀 원문", repr(parsed))
        self.assertNotIn("기밀 원문", repr(parsed.blocks[0]))


class TestFileParser(unittest.TestCase):
    def test_utf8_bom_txt_file_is_read_only(self) -> None:
        with TemporaryDirectory() as temp:
            file = Path(temp) / "example.txt"
            original = "\ufeff가나다\n\n라마바".encode("utf-8")
            file.write_bytes(original)
            parsed = parse_reference_file(file)
            self.assertEqual(parsed.encoding, "utf-8-sig")
            self.assertEqual(parsed.text, "가나다\n\n라마바")
            self.assertEqual(file.read_bytes(), original)

    def test_utf16_bom_markdown(self) -> None:
        with TemporaryDirectory() as temp:
            file = Path(temp) / "example.md"
            file.write_bytes("# 제목\n\n내용".encode("utf-16"))
            parsed = parse_reference_file(file)
            self.assertEqual(parsed.encoding, "utf-16")
            self.assertEqual(parsed.blocks[0].text, "제목")

    def test_cp949_is_explicit_only(self) -> None:
        with TemporaryDirectory() as temp:
            file = Path(temp) / "example.txt"
            file.write_bytes("한글 문장".encode("cp949"))
            with self.assertRaises(ReferenceParseError):
                parse_reference_file(file)
            parsed = parse_reference_file(file, encoding="cp949")
            self.assertEqual(parsed.text, "한글 문장")

    def test_invalid_utf8_is_rejected_without_leaking_path(self) -> None:
        with TemporaryDirectory() as temp:
            file = Path(temp) / "sensitive-title.txt"
            file.write_bytes(b"\xff\xff\xff")
            with self.assertRaises(ReferenceParseError) as captured:
                parse_reference_file(file)
            self.assertNotIn("sensitive-title", str(captured.exception))

    def test_size_limit_enforced_before_parsing(self) -> None:
        with TemporaryDirectory() as temp:
            file = Path(temp) / "example.txt"
            file.write_bytes(b"abcdefgh")
            with self.assertRaises(ReferenceParseError):
                parse_reference_file(file, max_bytes=7)

    def test_extension_restriction(self) -> None:
        with TemporaryDirectory() as temp:
            file = Path(temp) / "example.pdf"
            file.write_text("가나다", encoding="utf-8")
            with self.assertRaises(ReferenceParseError):
                parse_reference_file(file)

    def test_no_file_written_beside_source(self) -> None:
        with TemporaryDirectory() as temp:
            file = Path(temp) / "example.markdown"
            file.write_text("# 제목\n\n본문", encoding="utf-8")
            parse_reference_file(file)
            self.assertEqual([p.name for p in Path(temp).iterdir()], ["example.markdown"])

    def test_missing_file_safe_error(self) -> None:
        with TemporaryDirectory() as temp:
            file = Path(temp) / "not-here.txt"
            with self.assertRaises(ReferenceParseError) as captured:
                parse_reference_file(file)
            self.assertNotIn("not-here", str(captured.exception))


if __name__ == "__main__":
    unittest.main()
