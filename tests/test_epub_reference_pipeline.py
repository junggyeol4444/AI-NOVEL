"""Synthetic EPUB regressions; never read real manuscripts or user SQLite."""
from io import BytesIO
from pathlib import Path
import struct
import zlib
import tempfile
import unittest
from zipfile import ZipFile, ZIP_STORED, ZIP_DEFLATED

from ai_novel_factory.database.reference_catalog import ReferenceCatalog
from ai_novel_factory.references.epub_parser import parse_epub_bytes
from ai_novel_factory.references.episode_splitter import split_episodes
from ai_novel_factory.references.import_pipeline import import_reference_file
from ai_novel_factory.references.profile_pipeline import import_reference_profile
from ai_novel_factory.references.plaintext_parser import ReferenceParseError


def synthetic_epub(*, reverse=False, href='two.xhtml', chapter2=None, extra=()):
    one = ('<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>1화 시작</h1>'
           '<p>가상의 연구원이 실험 기록을 작성했다.</p></body></html>')
    two = chapter2 if chapter2 is not None else (
        '<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>2화 다음</h1>'
        '<p>다음 날 연구원은 결과를 검토했다.</p></body></html>')
    spine = '<itemref idref="b"/><itemref idref="a"/>' if reverse else '<itemref idref="a"/><itemref idref="b"/>'
    opf = ('<package><manifest><item id="a" href="one.xhtml" media-type="application/xhtml+xml"/>'
           f'<item id="b" href="{href}" media-type="application/xhtml+xml"/></manifest>'
           f'<spine>{spine}</spine></package>')
    container = ('<container><rootfiles><rootfile full-path="OPS/book.opf" '
                 'media-type="application/oebps-package+xml"/></rootfiles></container>')
    b = BytesIO()
    with ZipFile(b, 'w') as z:
        z.writestr('mimetype', 'application/epub+zip', compress_type=ZIP_STORED)
        for name, value in [('META-INF/container.xml', container), ('OPS/book.opf', opf),
                            ('OPS/one.xhtml', one), ('OPS/two.xhtml', two), *extra]:
            z.writestr(name, value, compress_type=ZIP_DEFLATED)
    return b.getvalue()


class EpubPipelineTests(unittest.TestCase):
    def test_spine_order_and_episode_split(self):
        parsed = parse_epub_bytes(synthetic_epub())
        self.assertEqual(parsed.format, 'epub')
        self.assertEqual([e.number for e in split_episodes(parsed).episodes], [1, 2])
        self.assertTrue(parse_epub_bytes(synthetic_epub(reverse=True)).text.startswith('2화'))

    def test_bad_paths_and_malformed_xml(self):
        for value in (synthetic_epub(href='../outside.xhtml'),
                      synthetic_epub(extra=[('../escape', 'x')]),
                      synthetic_epub(chapter2='<html><p>unclosed')):
            with self.subTest(case=len(value)), self.assertRaises(ReferenceParseError):
                parse_epub_bytes(value)

    def test_manifest_parent_reference_within_archive_is_allowed(self):
        # OPF at OPS/book.opf can legally refer to ../Text/two.xhtml.
        # This is not ZIP traversal: normalized target is Text/two.xhtml.
        raw = synthetic_epub(href='../Text/two.xhtml', extra=[
            ('Text/two.xhtml', '<html><body><h1>2화 다음</h1>'
                               '<p>가상의 두 번째 장면.</p></body></html>'),
        ])
        parsed = parse_epub_bytes(raw)
        self.assertEqual([e.number for e in split_episodes(parsed).episodes], [1, 2])
        self.assertIn('가상의 두 번째 장면.', parsed.text)

    def test_manifest_parent_reference_cannot_escape_archive_root(self):
        for href in ('../../escape.xhtml', '../../../OPS/two.xhtml',
                     '/Text/two.xhtml', 'https://invalid.example/two.xhtml',
                     '..\\Text\\two.xhtml', '%2e%2e/Text/two.xhtml'):
            with self.subTest(href=href), self.assertRaises(ReferenceParseError):
                parse_epub_bytes(synthetic_epub(href=href))

    def test_utf16_encoded_dtd_cannot_bypass_rejection(self):
        # UTF-16 hides ASCII DOCTYPE bytes from a raw-byte regex; ElementTree
        # would otherwise expand the internal entity before safety checks.
        malicious = ('<?xml version="1.0" encoding="UTF-16"?>'
                     '<!DOCTYPE html [<!ENTITY x "SYNTHETIC_EXPANDED">]>'
                     '<html><body><p>&x;</p></body></html>').encode('utf-16')
        with self.assertRaises(ReferenceParseError):
            parse_epub_bytes(synthetic_epub(chapter2=malicious))

    def test_dtd_and_external_entity_rejected(self):
        raw = synthetic_epub(chapter2='<!DOCTYPE html [<!ENTITY x SYSTEM "file:///secret">]><html/>')
        with self.assertRaises(ReferenceParseError):
            parse_epub_bytes(raw)

    def test_declared_xml_encoding_must_match_utf8_bytes(self):
        for encoding in ('UTF-16', 'ISO-8859-1'):
            with self.subTest(encoding=encoding), self.assertRaises(ReferenceParseError):
                raw = synthetic_epub(chapter2=(
                    f'<?xml version="1.0" encoding="{encoding}"?>'
                    '<html><body><p>synthetic</p></body></html>').encode('utf-8'))
                parse_epub_bytes(raw)
        accepted = synthetic_epub(chapter2=(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<html><body><p>synthetic</p></body></html>').encode('utf-8'))
        self.assertIn('synthetic', parse_epub_bytes(accepted).text)

    def test_utf8_bom_xhtml_still_supported(self):
        raw = synthetic_epub(chapter2=b'\xef\xbb\xbf<html><body><p>Visible text</p></body></html>')
        self.assertIn('Visible text', parse_epub_bytes(raw).text)

    def test_compression_bomb_ratio_rejected(self):
        raw = synthetic_epub(extra=[('OPS/padding.bin', b'\0' * (2 * 1024 * 1024))])
        with self.assertRaisesRegex(ReferenceParseError, '압축 비율'):
            parse_epub_bytes(raw)

    def test_epub_encryption_manifest_rejected(self):
        raw = synthetic_epub(extra=[('META-INF/encryption.xml', '<encryption/>')])
        with self.assertRaises(ReferenceParseError):
            parse_epub_bytes(raw)

    def test_head_is_not_counted_as_visible_prose(self):
        raw = synthetic_epub(chapter2=('<html><head><title>HIDDEN_TITLE</title>'
                                     '<p>HIDDEN_PARAGRAPH</p></head><body>'
                                     '<p>Visible synthetic text</p></body></html>'))
        parsed = parse_epub_bytes(raw)
        self.assertNotIn('HIDDEN', parsed.text)
        self.assertIn('Visible synthetic text', parsed.text)

    def test_adversarial_xml_depth_fails_closed(self):
        nested = '<div>' * 180 + '<p>deep synthetic</p>' + '</div>' * 180
        raw = synthetic_epub(chapter2='<html><body>' + nested + '</body></html>')
        with self.assertRaisesRegex(ReferenceParseError, '중첩'):
            parse_epub_bytes(raw)

    def test_nested_active_content_not_extracted(self):
        raw = synthetic_epub(chapter2='<html><body><script><p>HIDDEN_SYNTHETIC</p></script><p>Visible text</p></body></html>')
        self.assertNotIn('HIDDEN_SYNTHETIC', parse_epub_bytes(raw).text)

    def test_nested_blockquote_is_not_double_counted(self):
        raw = synthetic_epub(chapter2='<html><body><blockquote><p>Only once</p></blockquote></body></html>')
        self.assertEqual([b.text for b in parse_epub_bytes(raw).blocks].count('Only once'), 1)

    def test_corrupted_deflate_fails_with_safe_reference_error(self):
        # A corrupt ZIP member may raise zlib.error, not merely BadZipFile.
        source = synthetic_epub()
        with ZipFile(BytesIO(source)) as archive:
            info = archive.getinfo('META-INF/container.xml')
            self.assertEqual(info.compress_type, ZIP_DEFLATED)
            filename_len, extra_len = struct.unpack_from('<HH', source, info.header_offset + 26)
            payload_start = info.header_offset + 30 + filename_len + extra_len
        corrupted = bytearray(source)
        corrupted[payload_start] ^= 0xFF
        with ZipFile(BytesIO(corrupted)) as archive:
            with self.assertRaises(zlib.error) as thrown:
                archive.read('META-INF/container.xml')
            self.assertIsInstance(thrown.exception, (zlib.error, ValueError, OSError))
        with self.assertRaisesRegex(ReferenceParseError, '안전하게 해석') as handled:
            parse_epub_bytes(bytes(corrupted))
        self.assertNotIn('container.xml', str(handled.exception))

    def test_mimetype_size_checked_before_read(self):
        b = BytesIO()
        with ZipFile(BytesIO(synthetic_epub())) as src, ZipFile(b, 'w') as dest:
            for item in src.infolist():
                value = b'X' * (2 * 1024 * 1024) if item.filename == 'mimetype' else src.read(item)
                dest.writestr(item.filename, value, compress_type=item.compress_type)
        with self.assertRaises(ReferenceParseError):
            parse_epub_bytes(b.getvalue())

    def test_html_entities_decoded_once(self):
        raw = synthetic_epub(chapter2='<html><body><p>&amp;lt;literal&amp;gt;</p></body></html>')
        self.assertIn('&lt;literal&gt;', parse_epub_bytes(raw).text)
        self.assertNotIn('<literal>', parse_epub_bytes(raw).text)

    def test_text_cap_and_invalid_archive(self):
        for raw, options in ((synthetic_epub(), {'max_text_chars': 2}), (b'bad', {})):
            with self.assertRaises(ReferenceParseError):
                parse_epub_bytes(raw, **options)

    def test_both_import_pipelines_and_no_original_mutation(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'synthetic.epub'
            raw = synthetic_epub()
            path.write_bytes(raw)
            with ReferenceCatalog(Path(root) / 'catalog.sqlite') as catalog:
                result = import_reference_file(path, catalog=catalog)
                self.assertEqual(result.reference.status, 'analyzed')
                profile = import_reference_profile(path, catalog=catalog)
                self.assertEqual(profile.profile.source_format, 'epub')
                self.assertEqual(profile.reference.reference_id, result.reference.reference_id)
                self.assertEqual(catalog.count(), 1)
            self.assertEqual(path.read_bytes(), raw)

    def test_invalid_epub_never_registers(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'invalid.epub'
            path.write_bytes(synthetic_epub(chapter2='<html><p>unclosed'))
            with ReferenceCatalog(Path(root) / 'catalog.sqlite') as catalog:
                with self.assertRaises(ReferenceParseError):
                    import_reference_file(path, catalog=catalog)
                self.assertEqual(catalog.count(), 0)


if __name__ == '__main__':
    unittest.main()
