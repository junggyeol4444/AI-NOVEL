"""Stage 17 parser tests; artificial text only."""
import unittest
from ai_novel_factory.references import parse_text
from ai_novel_factory.references.episode_splitter import split_episodes
from ai_novel_factory.references.plaintext_parser import ParsedBlock, ParsedReference, ReferenceParseError

class EpisodeSplitTests(unittest.TestCase):
    def test_korean(self):
        r=split_episodes(parse_text("제1화 시작\n\n첫 장면\n\n제2화 반격\n\n두 번째 장면"))
        self.assertEqual([e.number for e in r.episodes], [1,2])
        self.assertEqual(r.episodes[1].title,"반격")
    def test_english_markdown(self):
        r=split_episodes(parse_text("# Episode 1: Start\n\nHello\n\n## Chapter 2 - Next\n\nWorld", format="markdown"))
        self.assertEqual(r.count,2)
        self.assertEqual(r.episodes[0].title,"Start")
    def test_no_marker(self):
        r=split_episodes(parse_text("한 문장\n\n다음 문장"))
        self.assertFalse(r.detected_markers)
        self.assertEqual(r.count,1)
    def test_preface(self):
        r=split_episodes(parse_text("작품 소개\n\n1화\n\n본문"))
        self.assertEqual(r.preface,"작품 소개")
        self.assertEqual(r.episodes[0].text,"본문")
    def test_embedded_number_not_heading(self):
        self.assertFalse(split_episodes(parse_text("그는 1화의 내용을 떠올렸다.")).detected_markers)
    def test_code_not_heading(self):
        fence = chr(96)*3
        r=split_episodes(parse_text(fence+"\n1화\n"+fence+"\n\n2화\n\n본문",format="markdown"))
        self.assertEqual([e.number for e in r.episodes],[2])
    def test_gaps(self):
        r=split_episodes(parse_text("10화\n\n본문\n\n12화\n\n결말"))
        self.assertEqual([e.number for e in r.episodes],[10,12])
    def test_duplicate(self):
        with self.assertRaises(ReferenceParseError):
            split_episodes(parse_text("1화\n\n내용\n\n1화\n\n내용"))
    def test_reverse(self):
        with self.assertRaises(ReferenceParseError):
            split_episodes(parse_text("3화\n\n내용\n\n2화\n\n내용"))
    def test_max(self):
        with self.assertRaises(ReferenceParseError):
            split_episodes(parse_text("1화\n\n하나\n\n2화\n\n둘"),max_episodes=1)
    def test_limits(self):
        d=parse_text("1화\n\n내용")
        for limit in [0,True,10001,1.2]:
            with self.subTest(limit=limit), self.assertRaises(ReferenceParseError):
                split_episodes(d,max_episodes=limit)
    def test_pdf_blocks(self):
        d=ParsedReference("pdf",None,"",(
            ParsedBlock("paragraph",1,1,"제1화"),
            ParsedBlock("paragraph",1,1,"첫 페이지"),
            ParsedBlock("paragraph",2,2,"제2화"),
            ParsedBlock("paragraph",2,2,"다음 페이지"),
        ))
        self.assertEqual(split_episodes(d).episodes[1].text,"다음 페이지")
    def test_no_mutation(self):
        d=parse_text("1화\n\n본문\n\n2화\n\n다음")
        original=d.text
        split_episodes(d)
        self.assertEqual(d.text,original)
    def test_nested_line_not_marker(self):
        self.assertFalse(split_episodes(parse_text("첫 줄\n1화\n끝")).detected_markers)
    def test_invalid_input(self):
        with self.assertRaises(ReferenceParseError):
            split_episodes("1화")
if __name__=="__main__":
    unittest.main()
