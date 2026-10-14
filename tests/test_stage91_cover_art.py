"""Stage 91 ANF-REQ-062: actual offline JPEG artwork and anti-overwrite gates."""
from __future__ import annotations

import contextlib
from io import BytesIO, StringIO
import hashlib
import importlib.util
import inspect
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory import cover_art as a
from ai_novel_factory.cover_cli import main as cover_main

PIL_INSTALLED = importlib.util.find_spec('PIL') is not None


class Stage91ValidationTests(unittest.TestCase):
    def test_required_title(self):
        with self.assertRaises(a.CoverArtError): a._validate(a.CoverSpec('', 'name'))

    def test_required_author(self):
        with self.assertRaises(a.CoverArtError): a._validate(a.CoverSpec('title', ''))

    def test_missing_title_type(self):
        with self.assertRaises(a.CoverArtError): a._validate(a.CoverSpec(None, 'a'))

    def test_author_type(self):
        with self.assertRaises(a.CoverArtError): a._validate(a.CoverSpec('a', object()))

    def test_wrong_spec_type(self):
        with self.assertRaises(a.CoverArtError): a._validate({'title': 'a'})

    def test_overlong_title(self):
        with self.assertRaises(a.CoverArtError): a._validate(a.CoverSpec('a'*91, 'b'))

    def test_overlong_author(self):
        with self.assertRaises(a.CoverArtError): a._validate(a.CoverSpec('a', 'b'*71))

    def test_overlong_genre(self):
        with self.assertRaises(a.CoverArtError): a._validate(a.CoverSpec('a', 'b', 'c'*51))

    def test_overlong_variation(self):
        with self.assertRaises(a.CoverArtError): a._validate(a.CoverSpec('a', 'b', variation='v'*81))

    def test_controls_rejected(self):
        for title in ['secret\nvisible', 'abc\tdef', 'test\x00xx', 'test\x7f']:
            with self.subTest(title=repr(title)), self.assertRaises(a.CoverArtError):
                a._validate(a.CoverSpec(title, 'b'))

    def test_bidi_rejected(self):
        for token in ['\u202e','\u2066','\u2069','\u202a']:
            with self.subTest(token=ord(token)), self.assertRaises(a.CoverArtError):
                a._validate(a.CoverSpec('a'+token, 'b'))

    def test_invalid_palette(self):
        with self.assertRaises(a.CoverArtError): a._validate(a.CoverSpec('a','b',palette='purple'))

    def test_invalid_style(self):
        with self.assertRaises(a.CoverArtError): a._validate(a.CoverSpec('a','b',style='image-copy'))

    def test_whitespace_normalization(self):
        s=a._validate(a.CoverSpec('  hi  ','  by  ',' fantasy  '))
        self.assertEqual((s.title,s.author,s.genre),('hi','by','fantasy'))

    def test_fixed_dimensions(self):
        self.assertEqual(a.COVER_SIZE,(1600,2560))
        self.assertEqual(a.THUMBNAIL_SIZE,(400,640))

    def test_no_reference_cover_argument(self):
        params=inspect.signature(a.render_cover).parameters
        self.assertEqual(tuple(params),('spec','font_path'))
        self.assertFalse(any('reference' in name.lower() for name in params))

    def test_palette_bounded(self):
        self.assertEqual(len(a.PALETTES),3)


@unittest.skipUnless(PIL_INSTALLED, 'optional Pillow unavailable')
class Stage91RenderedTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)
        self.spec=a.CoverSpec('별빛 아래의 지도','테스트 작가','판타지', 'nocturne','orbital')

    def test_render_real_jpeg(self):
        from PIL import Image
        payload=a.render_cover(self.spec)
        self.assertTrue(payload.startswith(b'\xff\xd8\xff'))
        with Image.open(BytesIO(payload)) as img:
            self.assertEqual(img.format,'JPEG')
            self.assertEqual(img.size,a.COVER_SIZE)
            self.assertEqual(img.mode,'RGB')
            self.assertEqual(img.getexif().__len__(),0)

    def test_korean_title_generates(self):
        result=a.render_cover(self.spec)
        self.assertGreater(len(result),40000)

    def test_deterministic(self):
        self.assertEqual(a.render_cover(self.spec),a.render_cover(self.spec))

    def test_variation_changes_artwork(self):
        b=a.CoverSpec(self.spec.title,self.spec.author,self.spec.genre,variation='different')
        self.assertNotEqual(hashlib.sha256(a.render_cover(self.spec)).hexdigest(),
                            hashlib.sha256(a.render_cover(b)).hexdigest())

    def test_style_changes_artwork(self):
        hashes=set()
        for style in sorted(a.STYLES):
            hashes.add(hashlib.sha256(a.render_cover(a.CoverSpec('제목','작가',style=style))).hexdigest())
        self.assertEqual(len(hashes),3)

    def test_palettes_change_artwork(self):
        hashes=set()
        for palette in a.PALETTES:
            hashes.add(hashlib.sha256(a.render_cover(a.CoverSpec('title','author',palette=palette))).hexdigest())
        self.assertEqual(len(hashes),3)

    def test_long_unspaced_hangul(self):
        payload=a.render_cover(a.CoverSpec('가'*68,'나'))
        self.assertTrue(payload.startswith(b'\xff\xd8'))

    def test_long_spaced_title(self):
        payload=a.render_cover(a.CoverSpec('고요한 바다의 조용한 약속 ' * 6,'나'))
        self.assertTrue(payload.startswith(b'\xff\xd8'))

    def test_no_font_fails_closed(self):
        with self.assertRaises(a.CoverArtError): a.render_cover(self.spec,font_path=self.path/'none.ttf')

    def test_thumb_dimensions_and_bytes(self):
        from PIL import Image
        thumb=a._thumbnail(a.render_cover(self.spec))
        self.assertTrue(thumb.startswith(b'\xff\xd8'))
        with Image.open(BytesIO(thumb)) as image:
            self.assertEqual((image.size,image.mode,image.format),((400,640),'RGB','JPEG'))

    def test_pair_created(self):
        result=a.save_cover_pair(self.spec,self.path)
        self.assertEqual(result.cover_path,self.path/'cover.jpg')
        self.assertEqual(result.thumbnail_path,self.path/'thumbnail.jpg')
        self.assertEqual(hashlib.sha256(result.cover_path.read_bytes()).hexdigest(),result.cover_sha256)
        self.assertEqual(hashlib.sha256(result.thumbnail_path.read_bytes()).hexdigest(),result.thumbnail_sha256)
        self.assertFalse(result.published)
        self.assertFalse(result.originality_reviewed)

    def test_pair_does_not_mutate_input(self):
        before=self.spec
        a.save_cover_pair(self.spec,self.path)
        self.assertEqual(self.spec,before)

    def test_output_contains_no_exif(self):
        from PIL import Image
        result=a.save_cover_pair(self.spec,self.path)
        for path in (result.cover_path,result.thumbnail_path):
            with Image.open(path) as img:
                self.assertEqual(len(img.getexif()),0)
                self.assertIsNone(img.info.get('comment'))

    def test_preexisting_cover_unmodified(self):
        f=self.path/'cover.jpg'
        f.write_bytes(b'important artwork')
        with self.assertRaises(a.CoverArtError): a.save_cover_pair(self.spec,self.path)
        self.assertEqual(f.read_bytes(),b'important artwork')
        self.assertFalse((self.path/'thumbnail.jpg').exists())

    def test_preexisting_thumbnail_unmodified(self):
        f=self.path/'thumbnail.jpg'
        f.write_bytes(b'important thumbnail')
        with self.assertRaises(a.CoverArtError): a.save_cover_pair(self.spec,self.path)
        self.assertEqual(f.read_bytes(),b'important thumbnail')
        self.assertFalse((self.path/'cover.jpg').exists())

    def test_no_auto_mkdir(self):
        with self.assertRaises(a.CoverArtError):
            a.save_cover_pair(self.spec,self.path/'does-not-exist')
        self.assertFalse((self.path/'does-not-exist').exists())

    def test_not_directory(self):
        p=self.path/'x'
        p.write_bytes(b'a')
        with self.assertRaises(a.CoverArtError): a.save_cover_pair(self.spec,p)

    def test_directory_symlink_rejected(self):
        alias=self.path/'alias'
        try: alias.symlink_to(self.path,target_is_directory=True)
        except (OSError,NotImplementedError): self.skipTest('symlink unsupported')
        with self.assertRaises(a.CoverArtError): a.save_cover_pair(self.spec,alias)

    def test_symlinked_file_not_overwritten(self):
        original=self.path/'original.jpg'
        original.write_bytes(b'private')
        symlink=self.path/'cover.jpg'
        try: symlink.symlink_to(original)
        except (OSError,NotImplementedError): self.skipTest('symlink unsupported')
        with self.assertRaises(a.CoverArtError): a.save_cover_pair(self.spec,self.path)
        self.assertEqual(original.read_bytes(),b'private')

    def test_rollback_second_file_failure(self):
        original_open=os.open
        def fail_second(path,*args,**kwargs):
            if str(path).endswith('thumbnail.jpg'):
                raise PermissionError('artificial')
            return original_open(path,*args,**kwargs)
        with patch.object(a.os,'open',side_effect=fail_second):
            with self.assertRaises(a.CoverArtError): a.save_cover_pair(self.spec,self.path)
        self.assertFalse((self.path/'cover.jpg').exists())
        self.assertFalse((self.path/'thumbnail.jpg').exists())

    def test_rollback_first_file_failure(self):
        with patch.object(a.os,'open',side_effect=PermissionError('artificial')):
            with self.assertRaises(a.CoverArtError): a.save_cover_pair(self.spec,self.path)
        self.assertFalse((self.path/'cover.jpg').exists())

    def test_cli_success(self):
        out=StringIO()
        with contextlib.redirect_stdout(out):
            code=cover_main(['--title',self.spec.title,'--author',self.spec.author,
                             '--output-dir',str(self.path)])
        self.assertEqual(code,0)
        self.assertTrue((self.path/'cover.jpg').is_file())
        self.assertTrue((self.path/'thumbnail.jpg').is_file())
        self.assertNotIn(self.spec.title,out.getvalue())
        self.assertNotIn(str(self.path),out.getvalue())

    def test_cli_failure_redacts_title_and_path(self):
        err=StringIO()
        with contextlib.redirect_stderr(err):
            code=cover_main(['--title','PRIVATE-TITLE','--author','by',
                             '--output-dir',str(self.path/'missing')])
        self.assertEqual(code,2)
        self.assertNotIn('PRIVATE-TITLE',err.getvalue())
        self.assertNotIn(str(self.path),err.getvalue())

    def test_double_save_denied(self):
        first=a.save_cover_pair(self.spec,self.path)
        with self.assertRaises(a.CoverArtError): a.save_cover_pair(self.spec,self.path)
        self.assertEqual(first.cover_path.read_bytes(),a.render_cover(self.spec))

    def test_no_external_network_used(self):
        with patch('socket.socket',side_effect=AssertionError('network attempt')):
            self.assertGreater(len(a.render_cover(self.spec)),20000)


if __name__=='__main__': unittest.main()
