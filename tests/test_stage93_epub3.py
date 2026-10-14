"""Offline Stage 93 EPUB3 builder and adversarial validation tests."""
from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from xml.etree import ElementTree as ET

from ai_novel_factory import epub3 as e
from ai_novel_factory.publication_metadata import MetadataDraft, save_metadata


class Stage93Epub3Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)
        self.meta=MetadataDraft('story-1','초록 별과 기억','테스트 작가','독자적인 설정\n세계관 소개','공상과학',('우주','모험'),'0')
        self.chapters=[e.Chapter('제1화 <출발>', '첫 줄 & 사건.\n이어지는 대화.\n\n끝 <문장>.'),e.Chapter('마지막 회차','그녀가 자신이 선택한 길을 걷는다.')]

    def build(self, **kw):
        return e.create_epub(self.meta,self.chapters,self.path,**kw)

    def alter_zip(self, modify):
        f=self.path/e.EPUB_NAME
        with zipfile.ZipFile(f) as z:
            old=[(v.filename, z.read(v.filename), v.compress_type) for v in z.infolist()]
        f.unlink()
        with zipfile.ZipFile(f,'w') as z:
            for name,body,compression in old:
                changed=modify(name,body)
                if changed is not None:
                    z.writestr(name,changed,compress_type=compression)
        return f

    def test_epub3_generation_roundtrip(self):
        result=self.build()
        self.assertEqual(result.chapters,2)
        self.assertFalse(result.contains_cover)
        self.assertFalse(result.publication_approved)
        self.assertFalse(result.published)
        self.assertEqual(result.path.name,'book.epub')
        self.assertEqual(result.sha256,hashlib.sha256(result.path.read_bytes()).hexdigest())
        self.assertEqual(e.verify_epub(result.path, expected_sha256=result.sha256,expected_chapters=2,expect_cover=False).chapters,2)

    def test_valid_epub_zip_structure(self):
        with zipfile.ZipFile(self.build().path) as z:
            first=z.infolist()[0]
            self.assertEqual(first.filename,'mimetype')
            self.assertEqual(first.compress_type, zipfile.ZIP_STORED)
            self.assertEqual(z.read('mimetype'),b'application/epub+zip')
            self.assertIn('EPUB/package.opf',z.namelist())
            self.assertIn('META-INF/container.xml',z.namelist())
            self.assertIn('EPUB/nav.xhtml',z.namelist())
            ET.fromstring(z.read('EPUB/package.opf'))
            ET.fromstring(z.read('EPUB/nav.xhtml'))

    def test_unicode_escaped_not_markup(self):
        with zipfile.ZipFile(self.build().path) as z:
            chapter=z.read('EPUB/chapters/ch0001.xhtml')
            self.assertIn('제1화'.encode(),chapter)
            self.assertIn(b'&lt;',chapter)
            self.assertIn(b'&amp;',chapter)
            root=ET.fromstring(chapter)
            self.assertEqual(root.find('.//{http://www.w3.org/1999/xhtml}h1').text, '제1화 <출발>')

    def test_multiline_paragraphs_and_breaks(self):
        with zipfile.ZipFile(self.build().path) as z:
            root=ET.fromstring(z.read('EPUB/chapters/ch0001.xhtml'))
            ps=root.findall('.//{http://www.w3.org/1999/xhtml}p')
            self.assertEqual(len(ps),2)
            self.assertIsNotNone(ps[0].find('{http://www.w3.org/1999/xhtml}br'))

    def test_metadata_is_serialized(self):
        with zipfile.ZipFile(self.build().path) as z:
            src=z.read(e.OPF).decode()
            self.assertIn('초록 별과 기억',src)
            self.assertIn('테스트 작가',src)
            self.assertIn('<dc:language>ko</dc:language>',src)
            self.assertIn('dcterms:modified',src)
            self.assertNotIn('publication_approved',src)

    def test_navigation_order(self):
        with zipfile.ZipFile(self.build().path) as z:
            root=ET.fromstring(z.read(e.NAV))
            links=root.findall('.//{http://www.w3.org/1999/xhtml}a')
            self.assertEqual([x.attrib['href'] for x in links],['chapters/ch0001.xhtml','chapters/ch0002.xhtml'])

    def test_stage92_metadata_file_integration(self):
        out=save_metadata(self.meta,self.path)
        with tempfile.TemporaryDirectory() as td:
            result=e.create_epub_from_metadata_file(out.path,self.chapters,td)
            self.assertTrue(e.verify_epub(result.path).valid)

    def test_cover_integration(self):
        cover=self.path/'cover.jpg'
        cover.write_bytes(b'\xff\xd8\xff'+b'JPEG DEMO' * 20 + b'\xff\xd9')
        result=self.build(cover_path=cover)
        self.assertTrue(result.contains_cover)
        self.assertTrue(e.verify_epub(result.path,expect_cover=True).contains_cover)
        with zipfile.ZipFile(result.path) as z:
            self.assertEqual(z.read('EPUB/images/cover.jpg'),cover.read_bytes())
            self.assertIn('EPUB/cover.xhtml',z.namelist())

    def test_cover_invalid_format(self):
        fake=self.path/'cover.jpg'
        fake.write_bytes(b'not a real jpeg')
        with self.assertRaises(e.EpubError): self.build(cover_path=fake)

    def test_cover_symlink_rejected(self):
        dest=self.path/'original.jpg'; dest.write_bytes(b'x'*40)
        alias=self.path/'alias.jpg'; alias.symlink_to(dest)
        with self.assertRaises(e.EpubError): self.build(cover_path=alias)

    def test_missing_output_directory(self):
        with self.assertRaises(e.EpubError): e.create_epub(self.meta,self.chapters,self.path/'missing')

    def test_output_directory_symlink(self):
        link=self.path/'alias';link.symlink_to(self.path,target_is_directory=True)
        with self.assertRaises(e.EpubError): e.create_epub(self.meta,self.chapters,link)

    def test_no_overwrite(self):
        result=self.build()
        old=result.path.read_bytes()
        with self.assertRaises(e.EpubError):self.build()
        self.assertEqual(result.path.read_bytes(),old)

    def test_no_follow_output_symlink(self):
        target=self.path/'secret';target.write_text('DO NOT CHANGE')
        (self.path/'book.epub').symlink_to(target)
        with self.assertRaises(e.EpubError): self.build()
        self.assertEqual(target.read_text(),'DO NOT CHANGE')

    def test_rollback_when_zip_writestr_fails(self):
        old=zipfile.ZipFile.writestr
        def fail(z,*args,**kw):
            if args[0]=='EPUB/nav.xhtml': raise OSError('private')
            return old(z,*args,**kw)
        with patch.object(zipfile.ZipFile,'writestr',fail):
            with self.assertRaises(OSError):self.build()
        self.assertFalse((self.path/'book.epub').exists())

    def test_rollback_when_verification_fails(self):
        with patch.object(e,'verify_epub',side_effect=e.EpubError('no')):
            with self.assertRaises(e.EpubError):self.build()
        self.assertFalse((self.path/'book.epub').exists())

    def test_zero_chapters(self):
        with self.assertRaises(e.EpubError):e.create_epub(self.meta,[],self.path)

    def test_too_many_chapters(self):
        with self.assertRaises(e.EpubError):e.create_epub(self.meta,[e.Chapter('a','b')]*201,self.path)

    def test_wrong_chapter_type(self):
        for cs in ([{'title':'hi','text':'hello'}],['abc'],None):
            with self.subTest(cs=cs), self.assertRaises(e.EpubError):e.create_epub(self.meta,cs,self.path)

    def test_empty_title_or_text(self):
        for ch in (e.Chapter(' ','text'),e.Chapter('title',' ')):
            with self.subTest(ch=ch),self.assertRaises(e.EpubError):e.create_epub(self.meta,[ch],self.path)

    def test_invisible_text_rejected(self):
        for s in ('abc\x00def','word\u202eword','yes\tno','x\ud800y'):
            with self.subTest(s=repr(s)),self.assertRaises(e.EpubError):e.create_epub(self.meta,[e.Chapter('first',s)],self.path)

    def test_large_chapter_rejected(self):
        with self.assertRaises(e.EpubError):e.create_epub(self.meta,[e.Chapter('a','가'*700000)],self.path)

    def test_invalid_metadata_rejected(self):
        with self.assertRaises(ValueError): e.create_epub(replace(self.meta,published=True),self.chapters,self.path)

    def test_expected_wrong_chapter_count(self):
        p=self.build().path
        with self.assertRaises(e.EpubError):e.verify_epub(p,expected_chapters=1)

    def test_expected_wrong_cover(self):
        p=self.build().path
        with self.assertRaises(e.EpubError):e.verify_epub(p,expect_cover=True)

    def test_bad_hash(self):
        p=self.build().path
        with self.assertRaises(e.EpubError):e.verify_epub(p,expected_sha256='0'*64)

    def test_invalid_checksum_form(self):
        with self.assertRaises(e.EpubError):e.verify_epub(self.build().path,expected_sha256='oops')

    def test_invalid_zip(self):
        p=self.path/'bad.epub'; p.write_bytes(b'invalid archive')
        with self.assertRaises(e.EpubError):e.verify_epub(p)

    def test_bad_mimetype(self):
        self.build()
        p=self.alter_zip(lambda n,b: b'x' if n=='mimetype' else b)
        with self.assertRaises(e.EpubError):e.verify_epub(p)

    def test_missing_nav(self):
        self.build()
        p=self.alter_zip(lambda n,b: None if n==e.NAV else b)
        with self.assertRaises(e.EpubError):e.verify_epub(p)

    def test_bad_container_path(self):
        self.build()
        p=self.alter_zip(lambda n,b: b.replace(b'EPUB/package.opf',b'EPUB/wrong.opf') if n==e.OCF else b)
        with self.assertRaises(e.EpubError):e.verify_epub(p)

    def test_tamper_xhtml(self):
        self.build()
        p=self.alter_zip(lambda n,b: b'BROKEN XML' if n.endswith('ch0002.xhtml') else b)
        with self.assertRaises(e.EpubError):e.verify_epub(p)

    def test_active_html_script_blocked(self):
        self.build()
        p=self.alter_zip(lambda n,b: b.replace(b'</body>',b'<script>bad()</script></body>') if n.endswith('ch0002.xhtml') else b)
        with self.assertRaises(e.EpubError):e.verify_epub(p)

    def test_xml_doctype_blocked(self):
        self.build()
        p=self.alter_zip(lambda n,b: b'<!DOCTYPE html>'+b if n==e.NAV else b)
        with self.assertRaises(e.EpubError):e.verify_epub(p)

    def test_remote_link_blocked(self):
        self.build()
        p=self.alter_zip(lambda n,b: b.replace(b'href="styles/book.css"',b'href="https://site.example/script"') if n.endswith('ch0001.xhtml') else b)
        with self.assertRaises(e.EpubError):e.verify_epub(p)

    def test_missing_chapter(self):
        self.build()
        p=self.alter_zip(lambda n,b: None if n.endswith('ch0002.xhtml') else b)
        with self.assertRaises(e.EpubError):e.verify_epub(p)

    def test_unexpected_asset(self):
        p=self.build().path
        with zipfile.ZipFile(p,'a') as z:z.writestr('EPUB/executable.js','alert(1)')
        with self.assertRaises(e.EpubError):e.verify_epub(p)

    def test_duplicate_filename(self):
        p=self.build().path
        with zipfile.ZipFile(p,'a') as z:z.writestr('EPUB/nav.xhtml',b'extra')
        with self.assertRaises(e.EpubError):e.verify_epub(p)

    def test_traversal_asset(self):
        p=self.build().path
        with zipfile.ZipFile(p,'a') as z:z.writestr('../path','bad')
        with self.assertRaises(e.EpubError):e.verify_epub(p)

    def test_spine_tamper(self):
        self.build()
        p=self.alter_zip(lambda n,b: b.replace(b'idref="c0002"',b'idref="c0001"') if n==e.OPF else b)
        with self.assertRaises(e.EpubError):e.verify_epub(p)

    def test_nav_tamper(self):
        self.build()
        p=self.alter_zip(lambda n,b: b.replace(b'href="chapters/ch0002.xhtml"',b'href="chapters/ch0001.xhtml"') if n==e.NAV else b)
        with self.assertRaises(e.EpubError):e.verify_epub(p)

    def test_opf_wrong_version(self):
        self.build()
        p=self.alter_zip(lambda n,b: b.replace(b'version="3.0"',b'version="2.0"') if n==e.OPF else b)
        with self.assertRaises(e.EpubError):e.verify_epub(p)

    def test_no_model_network_publishing_apis(self):
        self.assertFalse(any('reference' in k for k in e.create_epub.__code__.co_varnames))
        self.assertFalse(any('upload' in k or 'publish' in k for k in e.create_epub.__code__.co_names))


if __name__=='__main__':unittest.main()

class Stage93CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.directory=Path(self.tmp.name)
        self.meta=MetadataDraft('novel-1','마지막 보석','작가','소설 소개','소설',('성장',),'0')
        self.metadata_path=save_metadata(self.meta,self.directory).path
        self.chapters=self.directory/'user_chapters.json'
        self.chapters.write_text('[{"title":"첫 화","text":"한글 & 개인 초고"}]',encoding='utf-8')

    def test_load_user_chapters(self):
        from ai_novel_factory.epub_cli import load_user_chapters
        self.assertEqual(load_user_chapters(self.chapters), (e.Chapter('첫 화','한글 & 개인 초고'),))

    def test_cli_generates_preview(self):
        import io,json
        from contextlib import redirect_stdout
        from ai_novel_factory.epub_cli import main
        out=io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(['--metadata',str(self.metadata_path),'--chapters',str(self.chapters),'--output-dir',str(self.directory)]),0)
        obj=json.loads(out.getvalue())
        self.assertEqual(obj['file'],'book.epub')
        self.assertEqual(obj['chapters'],1)
        self.assertFalse(obj['published'])
        self.assertTrue(e.verify_epub(self.directory/'book.epub').valid)

    def test_chapter_json_duplicate_fields(self):
        from ai_novel_factory.epub_cli import load_user_chapters
        self.chapters.write_text('[{"title":"a","title":"b","text":"x"}]')
        with self.assertRaises(e.EpubError):load_user_chapters(self.chapters)

    def test_chapter_json_unknown_fields(self):
        from ai_novel_factory.epub_cli import load_user_chapters
        self.chapters.write_text('[{"title":"a","text":"b","published":true}]')
        with self.assertRaises(e.EpubError):load_user_chapters(self.chapters)

    def test_chapter_json_symlink(self):
        from ai_novel_factory.epub_cli import load_user_chapters
        link=self.directory/'link';link.symlink_to(self.chapters)
        with self.assertRaises(e.EpubError):load_user_chapters(link)

    def test_chapter_json_not_array(self):
        from ai_novel_factory.epub_cli import load_user_chapters
        self.chapters.write_text('{"title":"a"}')
        with self.assertRaises(e.EpubError):load_user_chapters(self.chapters)
