"""Stage 92: ANF-REQ-063 self-contained offline draft schema tests."""
from __future__ import annotations
from dataclasses import replace
from contextlib import redirect_stdout
from io import StringIO
import inspect
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory import publication_metadata as m
from ai_novel_factory.metadata_cli import main


class Stage92ContractTests(unittest.TestCase):
    def setUp(self):
        self.base = m.MetadataDraft('book-01', '새벽의 지도', '나의 필명',
                                    '독자적인 세계에서 시작하는 여정.', '판타지',
                                    ('모험', '성장'), '4500')

    def test_contract_required_fields(self):
        self.assertEqual(m.validate_metadata(self.base), self.base)
        self.assertEqual(m.validate_metadata(self.base).status, m.STATUS)
        self.assertFalse(self.base.published)
        self.assertFalse(self.base.publication_approved)

    def test_required_text(self):
        for field in ('title','author','description','category'):
            with self.subTest(field=field), self.assertRaises(m.MetadataError):
                m.validate_metadata(replace(self.base, **{field:' '}))

    def test_nonstring_text(self):
        for field in ('title','author','description','category'):
            with self.subTest(field=field), self.assertRaises(m.MetadataError):
                m.validate_metadata(replace(self.base, **{field:None}))

    def test_text_limits(self):
        for field, maximum in [('title',90),('author',70),('description',2000),('category',60)]:
            with self.subTest(field=field), self.assertRaises(m.MetadataError):
                m.validate_metadata(replace(self.base, **{field:'가'*(maximum+1)}))

    def test_unicode_nfc_normalization(self):
        v=m.validate_metadata(replace(self.base,title=' 가 '))
        self.assertEqual(v.title,'가')

    def test_multiline_synopsis_allowed(self):
        v=m.validate_metadata(replace(self.base, description='첫 장면\r\n두 번째 장면'))
        self.assertEqual(v.description, '첫 장면\n두 번째 장면')

    def test_title_no_newline(self):
        with self.assertRaises(m.MetadataError):
            m.validate_metadata(replace(self.base,title='one\ntwo'))

    def test_c0_tab_rejected_in_description(self):
        with self.assertRaises(m.MetadataError):
            m.validate_metadata(replace(self.base,description='abc\tsecret'))

    def test_c1_and_bidi_rejected(self):
        for token in ('\u0099','\u202e','\u2066','\u200b','\u200e','\ufeff','\ud800'):
            with self.subTest(token=repr(token)), self.assertRaises(m.MetadataError):
                m.validate_metadata(replace(self.base,description='foo'+token))

    def test_project_id(self):
        for token in ('','../secret','a/b','a b','-' ,'a'*81, '\uac00'):
            with self.subTest(value=token), self.assertRaises(m.MetadataError):
                m.validate_metadata(replace(self.base,project_id=token))

    def test_keywords_required(self):
        for token in ((), ('a',)*13, [], None):
            with self.subTest(value=repr(token)), self.assertRaises(m.MetadataError):
                m.validate_metadata(replace(self.base,keywords=token))

    def test_keyword_types(self):
        with self.assertRaises(m.MetadataError):
            m.validate_metadata(replace(self.base,keywords=('a',42)))

    def test_keyword_duplicates_casefold(self):
        with self.assertRaises(m.MetadataError):
            m.validate_metadata(replace(self.base,keywords=('Fantasy','fantasy')))

    def test_keyword_nfc_duplicates(self):
        with self.assertRaises(m.MetadataError):
            m.validate_metadata(replace(self.base,keywords=('가','가')))

    def test_keyword_normalization(self):
        got=m.validate_metadata(replace(self.base,keywords=(' space ',)))
        self.assertEqual(got.keywords,('space',))

    def test_keyword_length(self):
        with self.assertRaises(m.MetadataError):
            m.validate_metadata(replace(self.base,keywords=('a'*41,)))

    def test_price_currency_krw(self):
        self.assertEqual(m.validate_metadata(self.base).price_amount,'4500')
        self.assertEqual(m.validate_metadata(replace(self.base,price_amount='0')).price_amount,'0')

    def test_price_usd_cents(self):
        v=replace(self.base,price_amount='12.50',currency='USD')
        self.assertEqual(m.validate_metadata(v).price_amount,'12.50')

    def test_price_negative_and_float_invalid(self):
        for val in ('-1','1e4','1,000','NaN','inf',' 1','01','1.234',1.3,None,True):
            with self.subTest(val=val),self.assertRaises(m.MetadataError):
                m.validate_metadata(replace(self.base,price_amount=val))

    def test_krw_fraction_invalid(self):
        with self.assertRaises(m.MetadataError):
            m.validate_metadata(replace(self.base,price_amount='1.25'))

    def test_price_above_maximum(self):
        with self.assertRaises(m.MetadataError):
            m.validate_metadata(replace(self.base,price_amount='10000001'))

    def test_price_currency_invalid(self):
        for currency in ('XYZ','usd','KRW\n',None):
            with self.subTest(currency=currency),self.assertRaises(m.MetadataError):
                m.validate_metadata(replace(self.base,currency=currency))

    def test_language_invalid(self):
        with self.assertRaises(m.MetadataError):
            m.validate_metadata(replace(self.base,language='undefined'))

    def test_forbid_approved_and_published(self):
        for field in ('publication_approved','published'):
            with self.subTest(field=field), self.assertRaises(m.MetadataError):
                m.validate_metadata(replace(self.base,**{field:True}))

    def test_forbid_other_status_or_origin(self):
        for kw in ({'status':'PUBLISHED'},{'source':'REFERENCE_PROFILE'},{'version':2},{'version':True}):
            with self.subTest(kw=kw),self.assertRaises(m.MetadataError):
                m.validate_metadata(replace(self.base,**kw))

    def test_cover_alignment(self):
        self.assertEqual(m.validate_metadata(self.base,cover_title='새벽의 지도',cover_author='나의 필명'),self.base)
        for kw in ({'cover_title':'다른 제목'},{'cover_author':'다른 저자'}):
            with self.subTest(kw=kw),self.assertRaises(m.MetadataError):
                m.validate_metadata(self.base,**kw)

    def test_input_uses_original_user_logline(self):
        data=dict(project_id=self.base.project_id,title=self.base.title,
                  author=self.base.author, original_logline=self.base.description,
                  category=self.base.category, keywords=self.base.keywords,
                  price_amount=self.base.price_amount)
        self.assertEqual(m.draft_from_original_premise(**data),self.base)

    def test_no_reference_input_or_network_function(self):
        sig=inspect.signature(m.draft_from_original_premise)
        self.assertFalse(any('reference' in x for x in sig.parameters))
        self.assertFalse(any('reference' in x for x in m.MetadataDraft.__dataclass_fields__))


class Stage92PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory=Path(self.tmp.name)
        self.value=m.MetadataDraft('book-01','새벽의 지도','나의 필명','소개\n두 번째 줄','판타지',('모험','성장'),'0')

    def save(self):
        return m.save_metadata(self.value,self.directory)

    def test_roundtrip_korean(self):
        res=self.save()
        self.assertEqual(res.path.name,m.FILE_NAME)
        self.assertFalse(res.publication_approved)
        self.assertFalse(res.published)
        self.assertEqual(m.load_metadata(res.path), self.value)
        self.assertIn('새벽의 지도',res.path.read_text(encoding='utf-8'))

    def test_is_actual_utf8_json(self):
        v=json.loads(self.save().path.read_text(encoding='utf-8'))
        self.assertEqual(v['metadata']['price']['currency'],'KRW')
        self.assertEqual(v['metadata']['price']['amount'],'0')
        self.assertFalse(v['metadata']['published'])

    def test_stable_canonical_bytes(self):
        a=self.save()
        with tempfile.TemporaryDirectory() as td:
            b=m.save_metadata(self.value,td)
            self.assertEqual(a.sha256,b.sha256)
            self.assertEqual(a.path.read_bytes(),b.path.read_bytes())

    def test_no_overwrite(self):
        res=self.save()
        contents=res.path.read_bytes()
        with self.assertRaises(m.MetadataError):self.save()
        self.assertEqual(contents,res.path.read_bytes())

    def test_no_symlink_output(self):
        link=self.directory/'alias'
        link.symlink_to(self.directory, target_is_directory=True)
        with self.assertRaises(m.MetadataError):m.save_metadata(self.value,link)

    def test_no_symlink_file(self):
        other=self.directory/'other'
        other.write_text('not ours')
        (self.directory/m.FILE_NAME).symlink_to(other)
        with self.assertRaises(m.MetadataError):self.save()
        self.assertEqual(other.read_text(),'not ours')

    def test_missing_output_dir(self):
        with self.assertRaises(m.MetadataError):m.save_metadata(self.value,self.directory/'missing')

    def test_tampered_checksum(self):
        path=self.save().path
        obj=json.loads(path.read_text())
        obj['metadata']['title']='변경됨'
        path.write_text(json.dumps(obj),encoding='utf-8')
        with self.assertRaises(m.MetadataError):m.load_metadata(path)

    def test_invalid_hash(self):
        path=self.save().path
        obj=json.loads(path.read_text())
        obj['sha256']='0'*64
        path.write_text(json.dumps(obj))
        with self.assertRaises(m.MetadataError):m.load_metadata(path)

    def test_forged_approval_rejected_even_with_new_hash(self):
        path=self.save().path
        doc=json.loads(path.read_text())
        doc['metadata']['publication_approved']=True
        doc['sha256']=m.sha256(m._canonical(doc['metadata'])).hexdigest()
        path.write_text(json.dumps(doc))
        with self.assertRaises(m.MetadataError):m.load_metadata(path)

    def test_extra_field_rejected_even_with_hash(self):
        path=self.save().path
        doc=json.loads(path.read_text())
        doc['metadata']['upload_token']='secret'
        doc['sha256']=m.sha256(m._canonical(doc['metadata'])).hexdigest()
        path.write_text(json.dumps(doc))
        with self.assertRaises(m.MetadataError):m.load_metadata(path)

    def test_duplicate_json_key_rejected(self):
        path=self.directory/m.FILE_NAME
        path.write_text('{"metadata": {}, "metadata": {}, "sha256": "x"}')
        with self.assertRaises(m.MetadataError):m.load_metadata(path)

    def test_too_large_rejected(self):
        path=self.directory/m.FILE_NAME
        path.write_bytes(b'x'*17000)
        with self.assertRaises(m.MetadataError):m.load_metadata(path)

    def test_symlink_read_rejected(self):
        target=self.save().path
        link=self.directory/'alias.json'
        link.symlink_to(target)
        with self.assertRaises(m.MetadataError):m.load_metadata(link)

    def test_no_log_or_publish_calls(self):
        with patch('urllib.request.urlopen',side_effect=AssertionError('network')):
            self.save()

    def test_cli_creates_only_draft_and_never_prints_private_prose(self):
        source=self.directory/'in.json'
        source.write_text(json.dumps({'project_id':'book-01', 'title':'나만의 비밀제목',
             'author':'나', 'original_logline':'비공개 설명', 'category':'판타지',
             'keywords':['신비'], 'price_amount':'0', 'currency':'KRW', 'language':'ko'},ensure_ascii=False),encoding='utf-8')
        dest=self.directory/'dest';dest.mkdir()
        stdout=StringIO()
        with redirect_stdout(stdout): rc=main(['--input',str(source),'--directory',str(dest)])
        self.assertEqual(rc,0)
        self.assertNotIn('비공개',stdout.getvalue())
        self.assertNotIn('비밀제목',stdout.getvalue())
        self.assertTrue((dest/m.FILE_NAME).exists())

    def test_cli_bad_input_safe_error(self):
        source=self.directory/'bad.json'
        source.write_text('{invalid secret}')
        stdout=StringIO()
        with redirect_stdout(stdout):rc=main(['--input',str(source),'--directory',str(self.directory)])
        self.assertEqual(rc,2)
        self.assertNotIn('secret',stdout.getvalue())

    def test_cli_reject_extra_reference_fields(self):
        source=self.directory/'in.json'
        source.write_text(json.dumps({'reference_text':'secret'}))
        stdout=StringIO()
        with redirect_stdout(stdout):rc=main(['--input',str(source),'--directory',str(self.directory)])
        self.assertEqual(rc,2)
        self.assertFalse((self.directory/m.FILE_NAME).exists())


if __name__=='__main__':unittest.main()
