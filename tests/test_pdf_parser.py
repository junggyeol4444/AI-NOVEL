"""Stage 16 PDF parser: synthetic, local-only fixtures (no novel originals)."""
from __future__ import annotations

from io import BytesIO
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory.references import (
    ParsedPdfReference, ReferenceParseError, parse_pdf_bytes, parse_pdf_file,
)

try:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject, NumberObject
except ImportError:
    PdfReader = PdfWriter = None


def _new_page(writer: object, text: str | None = None, *, image: bool = False) -> None:
    page = writer.add_blank_page(width=612, height=792)
    resources = DictionaryObject()
    instructions = []
    if text is not None:
        font = DictionaryObject({
            NameObject('/Type'): NameObject('/Font'),
            NameObject('/Subtype'): NameObject('/Type1'),
            NameObject('/BaseFont'): NameObject('/Helvetica'),
        })
        resources[NameObject('/Font')] = DictionaryObject({
            NameObject('/F1'): writer._add_object(font),
        })
        # ASCII-only fixture by design; never include private novel text.
        safe = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        instructions.append(f'BT /F1 12 Tf 30 700 Td ({safe}) Tj ET'.encode('ascii'))
    if image:
        image_data = DecodedStreamObject()
        image_data.set_data(b'\xff')  # one pixel; no copyrighted image content
        image_data.update({
            NameObject('/Type'): NameObject('/XObject'),
            NameObject('/Subtype'): NameObject('/Image'),
            NameObject('/Width'): NumberObject(1),
            NameObject('/Height'): NumberObject(1),
            NameObject('/ColorSpace'): NameObject('/DeviceGray'),
            NameObject('/BitsPerComponent'): NumberObject(8),
        })
        resources[NameObject('/XObject')] = DictionaryObject({
            NameObject('/Im1'): writer._add_object(image_data),
        })
        instructions.append(b'q 1 0 0 1 20 20 cm /Im1 Do Q')
    if resources:
        page[NameObject('/Resources')] = resources
    if instructions:
        content = DecodedStreamObject()
        content.set_data(b'\n'.join(instructions))
        page[NameObject('/Contents')] = writer._add_object(content)


def _pdf(*pages: tuple[str | None, bool], password: str | None = None) -> bytes:
    writer = PdfWriter()
    for text, image in pages:
        _new_page(writer, text, image=image)
    if password:
        writer.encrypt(password)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


@unittest.skipUnless(PdfWriter is not None, 'pypdf optional dependency missing')
class PdfParserTests(unittest.TestCase):
    def test_page_order_and_metadata(self):
        result = parse_pdf_bytes(_pdf(('FIRST', False), ('SECOND', False)))
        self.assertIsInstance(result, ParsedPdfReference)
        self.assertEqual(result.format, 'pdf')
        self.assertIsNone(result.encoding)
        self.assertEqual(result.page_count, 2)
        self.assertEqual(result.paragraph_count, 2)
        self.assertEqual([b.text for b in result.blocks], ['FIRST', 'SECOND'])
        self.assertEqual([(b.start_line, b.end_line) for b in result.blocks], [(1, 1), (2, 2)])
        self.assertEqual(result.image_only_pages, ())

    def test_text_without_original_content_in_repr(self):
        result = parse_pdf_bytes(_pdf(('TOPSECRET', False)))
        self.assertNotIn('TOPSECRET', repr(result))
        self.assertNotIn('TOPSECRET', repr(result.blocks[0]))

    def test_blank_pages_are_reported_without_failing(self):
        result = parse_pdf_bytes(_pdf((None, False), ('CONTENT', False), (None, False)))
        self.assertEqual(result.empty_pages, (1, 3))
        self.assertEqual(result.page_count, 3)
        self.assertEqual(result.blocks[0].start_line, 2)

    def test_image_only_pdf_requires_ocr(self):
        with self.assertRaisesRegex(ReferenceParseError, 'OCR'):
            parse_pdf_bytes(_pdf((None, True)))

    def test_mixed_image_only_pages_reported(self):
        result = parse_pdf_bytes(_pdf(('TEXT', False), (None, True), ('END', False)))
        self.assertEqual(result.image_only_pages, (2,))
        self.assertEqual(result.empty_pages, ())
        self.assertEqual(result.paragraph_count, 2)

    def test_blank_pdf_rejected(self):
        with self.assertRaisesRegex(ReferenceParseError, '추출할 수 있는 텍스트'):
            parse_pdf_bytes(_pdf((None, False)))

    def test_encrypted_pdf_rejected(self):
        with self.assertRaisesRegex(ReferenceParseError, '암호화'):
            parse_pdf_bytes(_pdf(('X', False), password='example'))

    def test_invalid_header_rejected(self):
        with self.assertRaisesRegex(ReferenceParseError, '헤더'):
            parse_pdf_bytes(b'this is not a PDF')

    def test_corrupted_pdf_error_is_safe(self):
        with self.assertRaises(ReferenceParseError) as ctx:
            parse_pdf_bytes(b'%PDF-1.7\nBROKEN_PRIVATE_SECRET')
        self.assertNotIn('PRIVATE_SECRET', str(ctx.exception))

    def test_empty_and_wrong_type_rejected(self):
        for raw in (b'', '', None, bytearray(b'%PDF-1.7')):
            with self.subTest(raw_type=type(raw).__name__):
                with self.assertRaisesRegex(ReferenceParseError, '바이트'):
                    parse_pdf_bytes(raw)

    def test_pages_limit(self):
        with self.assertRaisesRegex(ReferenceParseError, '페이지 수 제한을 초과'):
            parse_pdf_bytes(_pdf(('ONE', False), ('TWO', False)), max_pages=1)

    def test_total_character_limit(self):
        with self.assertRaisesRegex(ReferenceParseError, '전체 본문 길이'):
            parse_pdf_bytes(_pdf(('TOO LONG', False)), max_text_chars=3)

    def test_per_page_character_limit(self):
        with self.assertRaisesRegex(ReferenceParseError, '페이지 본문 길이'):
            parse_pdf_bytes(_pdf(('TOO LONG', False)), max_page_text_chars=3)

    def test_invalid_limits(self):
        raw = _pdf(('TEXT', False))
        for name, value in [('max_pages', 0), ('max_pages', True),
                            ('max_text_chars', -1), ('max_page_text_chars', False)]:
            with self.subTest(name=name, value=value):
                with self.assertRaises(ReferenceParseError):
                    parse_pdf_bytes(raw, **{name: value})

    def test_file_unmodified(self):
        raw = _pdf(('READONLY', False))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.pdf'
            path.write_bytes(raw)
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            parsed = parse_pdf_file(path)
            self.assertEqual(parsed.blocks[0].text, 'READONLY')
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_invalid_suffix_rejected(self):
        with self.assertRaisesRegex(ReferenceParseError, '확장자'):
            parse_pdf_file('test.docx')

    def test_file_size_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.pdf'
            path.write_bytes(_pdf(('CONTENT', False)))
            with self.assertRaisesRegex(ReferenceParseError, '허용 크기'):
                parse_pdf_file(path, max_bytes=5)

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            original = Path(folder) / 'original.pdf'
            original.write_bytes(_pdf(('TEXT', False)))
            link = Path(folder) / 'link.pdf'
            try:
                link.symlink_to(original)
            except (OSError, NotImplementedError):
                self.skipTest('OS symlinks unavailable')
            with self.assertRaisesRegex(ReferenceParseError, '심볼릭 링크'):
                parse_pdf_file(link)

    def test_io_error_masks_path(self):
        with self.assertRaises(ReferenceParseError) as ctx:
            parse_pdf_file('UNIQUE_NONEXISTENT_SECRET.pdf')
        self.assertNotIn('UNIQUE_NONEXISTENT_SECRET', str(ctx.exception))

    def test_file_size_validation(self):
        with self.assertRaisesRegex(ReferenceParseError, '파일 크기 제한'):
            parse_pdf_file('fake.pdf', max_bytes=True)

    def test_internal_exception_sanitized(self):
        with patch('pypdf.PdfReader', side_effect=RuntimeError('PRIVATE PDF CONTENT')):
            with self.assertRaises(ReferenceParseError) as ctx:
                parse_pdf_bytes(_pdf(('TEST', False)))
        self.assertNotIn('PRIVATE PDF CONTENT', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
