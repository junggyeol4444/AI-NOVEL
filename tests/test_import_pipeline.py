"""Stage 20: offline end-to-end input->parse->split->statistics->metadata tests."""
from __future__ import annotations

from io import BytesIO
import hashlib
from pathlib import Path
import sqlite3
from contextlib import closing
import tempfile
import unittest

from ai_novel_factory.database import ReferenceCatalog
from ai_novel_factory.references import ReferenceParseError, import_reference_file

try:
    from docx import Document
except ImportError:
    Document = None
try:
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
except ImportError:
    PdfWriter = None


def sample_docx() -> bytes:
    document = Document()
    document.add_heading('제1화', 1)
    document.add_paragraph('안전한 창작 테스트입니다.')
    document.add_heading('제2화', 1)
    document.add_paragraph('다음 회차의 내용입니다.')
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def sample_pdf() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=400, height=500)
    font = DictionaryObject({
        NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/Helvetica'),
    })
    page[NameObject('/Resources')] = DictionaryObject({
        NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})
    })
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 30 400 Td (Test paragraph.) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class ImportPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.catalog = ReferenceCatalog(self.root / 'reference.sqlite3')
        self.addCleanup(self.catalog.close)

    def write(self, filename, raw: bytes):
        path = self.root / filename
        path.write_bytes(raw)
        return path

    def test_txt_end_to_end(self):
        payload = '서문 안내\n\n제1화 첫 사건\n\n첫 번째 이야기입니다.\n\n제2화 반전\n\n다음 이야기입니다.'
        raw = payload.encode('utf-8')
        file = self.write('소설.txt', raw)
        result = import_reference_file(file, catalog=self.catalog)
        self.assertEqual(result.statistics.episode_count, 2)
        self.assertEqual([e.number for e in result.statistics.episodes], [1, 2])
        self.assertEqual(result.statistics.preface.paragraphs, 1)
        self.assertEqual(result.reference.file_name, '소설.txt')
        self.assertEqual(result.reference.byte_count, len(raw))
        self.assertEqual(result.reference.sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(result.reference.status, 'analyzed')
        self.assertEqual(self.catalog.count(), 1)
        self.assertEqual(file.read_bytes(), raw)

    def test_markdown_setext_heading_and_alias(self):
        f = self.write('작품.markdown', '# 제1화\n\n한 문단입니다.\n\n# 제2화\n\n둘째 문단입니다.'.encode())
        result = import_reference_file(f, catalog=self.catalog)
        self.assertEqual(result.statistics.episode_count, 2)
        self.assertEqual(result.reference.source_format, 'md')
        self.assertEqual(result.statistics.total.paragraphs, 2)

    def test_markdown_no_chapter_marker_is_one_episode(self):
        f = self.write('notes.md', b'# title\n\nContent only.')
        self.assertEqual(import_reference_file(f, catalog=self.catalog).statistics.episode_count, 1)

    def test_utf16_bom(self):
        f = self.write('utf16.txt', '제1화\n\n안녕하세요.'.encode('utf-16'))
        self.assertEqual(import_reference_file(f, catalog=self.catalog).statistics.episode_count, 1)

    def test_cp949_requires_explicit_opt_in(self):
        f = self.write('legacy.txt', '한글 문장입니다.'.encode('cp949'))
        with self.assertRaises(ReferenceParseError):
            import_reference_file(f, catalog=self.catalog)
        self.assertEqual(self.catalog.count(), 0)
        self.assertGreater(import_reference_file(f, catalog=self.catalog, encoding='cp949').statistics.total.characters, 0)

    @unittest.skipUnless(Document is not None, 'python-docx missing')
    def test_docx_parsing_catalog_and_episode_split(self):
        raw = sample_docx()
        file = self.write('fiction.docx', raw)
        out = import_reference_file(file, catalog=self.catalog)
        self.assertEqual(out.statistics.episode_count, 2)
        self.assertEqual(out.statistics.total.paragraphs, 2)
        self.assertEqual(out.reference.status, 'analyzed')
        self.assertEqual(file.read_bytes(), raw)

    @unittest.skipUnless(PdfWriter is not None, 'pypdf missing')
    def test_pdf_parser_and_catalog(self):
        raw = sample_pdf()
        file = self.write('fiction.pdf', raw)
        out = import_reference_file(file, catalog=self.catalog)
        self.assertEqual(out.statistics.episode_count, 1)
        self.assertEqual(out.statistics.total.paragraphs, 1)
        self.assertEqual(out.reference.source_format, 'pdf')
        self.assertEqual(file.read_bytes(), raw)

    def test_same_content_different_path_deduplicated(self):
        raw = b'Chapter 1\n\nContent.'
        a = import_reference_file(self.write('a.txt', raw), catalog=self.catalog)
        b = import_reference_file(self.write('b.txt', raw), catalog=self.catalog)
        self.assertEqual(a.reference.reference_id, b.reference.reference_id)
        self.assertEqual(self.catalog.count(), 1)
        self.assertEqual(b.reference.status, 'analyzed')

    def test_failed_parse_does_not_create_record(self):
        f = self.write('failed.txt', b'\x00\x01binary')
        with self.assertRaises(ReferenceParseError):
            import_reference_file(f, catalog=self.catalog)
        self.assertEqual(self.catalog.count(), 0)

    def test_bad_episode_numbers_do_not_create_record(self):
        f = self.write('bad.txt', '제2화\n\n장면.\n\n제1화\n\n장면.'.encode())
        with self.assertRaises(ReferenceParseError):
            import_reference_file(f, catalog=self.catalog)
        self.assertEqual(self.catalog.count(), 0)

    def test_unsupported_epub_fails_closed(self):
        f = self.write('book.epub', b'not currently supported')
        with self.assertRaisesRegex(ReferenceParseError, 'EPUB'):
            import_reference_file(f, catalog=self.catalog)
        self.assertEqual(self.catalog.count(), 0)

    def test_file_limit_enforced_and_no_record(self):
        f = self.write('big.txt', b'Hello there.')
        with self.assertRaisesRegex(ReferenceParseError, '크기'):
            import_reference_file(f, catalog=self.catalog, max_bytes=5)
        self.assertEqual(self.catalog.count(), 0)

    def test_reject_invalid_limit(self):
        f = self.write('ok.txt', b'Hello.')
        for value in [True, 0, -1, 1.5]:
            with self.subTest(value=value), self.assertRaises(ReferenceParseError):
                import_reference_file(f, catalog=self.catalog, max_bytes=value)
        self.assertEqual(self.catalog.count(), 0)

    def test_reject_symlink(self):
        f = self.write('original.txt', b'Hello.')
        link = self.root / 'link.txt'
        try:
            link.symlink_to(f)
        except (OSError, NotImplementedError):
            self.skipTest('symlink not available')
        with self.assertRaisesRegex(ReferenceParseError, '심볼릭'):
            import_reference_file(link, catalog=self.catalog)
        self.assertEqual(self.catalog.count(), 0)

    def test_errors_do_not_reveal_original_path(self):
        f = self.root / 'private_password_secret.txt'
        with self.assertRaises(ReferenceParseError) as cm:
            import_reference_file(f, catalog=self.catalog)
        self.assertNotIn('private_password_secret', str(cm.exception))

    def test_database_does_not_store_original_passages(self):
        content = '제1화\n\nPRIVATE_TEST_NOVEL_PASSAGE'
        f = self.write('secret.txt', content.encode())
        out = import_reference_file(f, catalog=self.catalog)
        self.assertNotIn('PRIVATE_TEST_NOVEL_PASSAGE', repr(out))
        self.assertNotIn(str(self.root), repr(out))
        with closing(sqlite3.connect(self.root / 'reference.sqlite3')) as con:
            fields = con.execute('select * from reference_files').fetchone()
            flat = repr(fields)
            self.assertNotIn('PRIVATE_TEST_NOVEL_PASSAGE', flat)
            self.assertNotIn(str(self.root), flat)

    def test_sqlite_persistence_on_reopen(self):
        f = self.write('persist.txt', b'Something that stays.')
        entry = import_reference_file(f, catalog=self.catalog)
        with ReferenceCatalog(self.root / 'reference.sqlite3') as new_catalog:
            self.assertEqual(new_catalog.get(entry.reference.reference_id).status, 'analyzed')
            self.assertEqual(new_catalog.count(), 1)

    def test_failed_after_success_does_not_break_existing_record(self):
        good = self.write('valid.txt', b'Valid example.')
        old = import_reference_file(good, catalog=self.catalog)
        broken = self.write('broken.txt', b'\x00broken')
        with self.assertRaises(ReferenceParseError):
            import_reference_file(broken, catalog=self.catalog)
        self.assertEqual(self.catalog.count(), 1)
        self.assertEqual(self.catalog.get(old.reference.reference_id).status, 'analyzed')


if __name__ == '__main__':
    unittest.main()
