"""Read-only verified EPUB3; synthetic fixtures never certify AI literature."""
from __future__ import annotations
from pathlib import Path
import tempfile
import unittest
from ai_novel_factory.epub3 import Chapter, EpubError, create_epub
from ai_novel_factory.epub_reader import read_private_epub
from ai_novel_factory.publication_metadata import MetadataDraft


class PrivateEpubReadingTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.meta=MetadataDraft('epub-test', '읽기 검증', '가상 작가',
                                '완전한 가상의 설정', '판타지', ('검사',), '0')

    def test_paragraphs_xml_metacharacters_and_linebreaks_roundtrip(self):
        chapters=[Chapter('첫 회', '가상의 & 나무.\n둘째 줄.\n\n다음 <문단>.'),
                  Chapter('둘째 회', '새 사건과 독창적 행동.')]
        out=create_epub(self.meta,chapters,self.root)
        self.assertEqual(read_private_epub(out.path),tuple(chapters))
        self.assertFalse(out.publication_approved)

    def test_epub_chapter_css_is_available_to_private_reader(self):
        import posixpath
        from zipfile import ZipFile
        chapters = [Chapter('첫 회', '그는 낡은 열쇠를 찾았다.')]
        out = create_epub(self.meta, chapters, self.root)
        with ZipFile(out.path) as archive:
            self.assertIn(posixpath.normpath('EPUB/chapters/../styles/book.css'),
                          archive.namelist())
        self.assertEqual(read_private_epub(out.path), tuple(chapters))

    def test_verified_250_chapter_epub3_roundtrip(self):
        # Real EPUB creation/read, only synthetic stored text (NOT AI 250화).
        chapters=tuple(Chapter(f'{n}화', f'{n}번째 가상 원고.')
                       for n in range(1,251))
        out=create_epub(self.meta,chapters,self.root)
        loaded=read_private_epub(out.path)
        self.assertEqual(len(loaded),250)
        self.assertEqual(loaded[0],chapters[0])
        self.assertEqual(loaded[-1],chapters[-1])

    def test_corrupt_archive_or_nonlocal_uri_fail_closed(self):
        bad=self.root/'corrupt.epub'
        bad.write_bytes(b'bad zip')
        for candidate in (bad,'novel.epub','file:///tmp/novel.epub'):
            with self.subTest(candidate=candidate),self.assertRaises(EpubError):
                read_private_epub(candidate)


if __name__ == '__main__':
    unittest.main()
