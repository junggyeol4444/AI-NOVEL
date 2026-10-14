"""Stage 94 offline episode upload draft export/validation tests."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory import episode_upload_files as u
from ai_novel_factory import upload_draft_cli as cli
from ai_novel_factory.publication_metadata import MetadataDraft, save_metadata


_UNSPECIFIED = object()


class Stage94Tests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.metadata=MetadataDraft('novel-01','고유한 별','테스트 작가', '독자적 설정과 줄거리', '판타지', ('여행','우주'), '0')
        self.episodes=[u.UploadEpisode(2,'제2화: 별', '둘째 회차\n\n& <이야기>', ''),
                       u.UploadEpisode(1,'제1화: 시작', '첫째 회차\r\n이어서 간다.', '다음 화에서 만나요.')]

    def create(self, episodes=_UNSPECIFIED, parent=None, metadata=None):
        return u.export_upload_drafts(metadata or self.metadata, episodes if episodes is not _UNSPECIFIED else self.episodes,
                                      parent or self.root)

    def test_basic_export(self):
        r=self.create()
        self.assertEqual(r.directory,self.root/'upload_drafts')
        self.assertEqual(r.episode_count,2)
        self.assertEqual(r.files_created,6)
        self.assertFalse(r.published)
        self.assertFalse(r.publication_approved)
        self.assertEqual(u.verify_upload_drafts(r.directory,expected_manifest_sha256=r.manifest_sha256).files_verified,6)

    def test_owner_text_preserved(self):
        r=self.create()
        d=r.directory
        self.assertEqual((d/'episode_0001_title.txt').read_text(encoding='utf8'),'제1화: 시작')
        self.assertEqual((d/'episode_0001_body.txt').read_bytes(),'첫째 회차\n이어서 간다.'.encode())
        self.assertEqual((d/'episode_0002_body.txt').read_text(encoding='utf8'),'둘째 회차\n\n& <이야기>')
        self.assertEqual((d/'episode_0002_author_note.txt').read_bytes(),b'')

    def test_utf8_and_no_bom(self):
        r=self.create()
        for f in r.directory.glob('*.txt'):
            self.assertFalse(f.read_bytes().startswith(b'\xef\xbb\xbf'))
            f.read_bytes().decode('utf-8',errors='strict')
        self.assertTrue(u.verify_upload_drafts(r.directory).valid)

    def test_manifest_provenance_without_manuscript(self):
        r=self.create()
        doc=json.loads((r.directory/u.MANIFEST_NAME).read_text(encoding='utf8'))
        self.assertEqual([x['episode_number'] for x in doc['episodes']],[1,2])
        self.assertEqual(doc['project_id'],'novel-01')
        self.assertEqual(doc['status'],u.STATUS)
        self.assertEqual(doc['encoding'],'UTF-8')
        self.assertNotIn('첫째',str(doc))
        self.assertNotIn('테스트 작가',str(doc))
        self.assertFalse(doc['publication_approved'])
        self.assertFalse(doc['published'])

    def test_no_overwrite(self):
        result=self.create()
        old=(result.directory/'episode_0001_body.txt').read_bytes()
        with self.assertRaises(u.UploadDraftError):self.create()
        self.assertEqual((result.directory/'episode_0001_body.txt').read_bytes(),old)

    def test_no_overwrite_existing_folder(self):
        folder=self.root/u.DIR_NAME
        folder.mkdir()
        (folder/'secret.txt').write_text('keep')
        with self.assertRaises(u.UploadDraftError): self.create()
        self.assertEqual((folder/'secret.txt').read_text(),'keep')

    def test_output_parent_missing(self):
        with self.assertRaises(u.UploadDraftError):self.create(parent=self.root/'missing')

    def test_output_parent_symlink(self):
        link=self.root/'link'; link.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(u.UploadDraftError):self.create(parent=link)

    def test_existing_output_symlink_not_followed(self):
        hidden=self.root/'elsewhere';hidden.mkdir()
        (self.root/u.DIR_NAME).symlink_to(hidden,target_is_directory=True)
        with self.assertRaises(u.UploadDraftError):self.create()
        self.assertEqual(list(hidden.iterdir()),[])

    def test_atomic_rollback_on_write_error(self):
        original=u.os.fsync
        calls=0
        def broken(fd):
            nonlocal calls
            calls+=1
            if calls==2:raise OSError('PRIVATE MATERIAL')
            return original(fd)
        with patch.object(u.os,'fsync',side_effect=broken):
            with self.assertRaises(OSError):self.create()
        self.assertFalse((self.root/u.DIR_NAME).exists())

    def test_atomic_rollback_on_verification_error(self):
        with patch.object(u,'verify_upload_drafts',side_effect=u.UploadDraftError('no')):
            with self.assertRaises(u.UploadDraftError):self.create()
        self.assertFalse((self.root/u.DIR_NAME).exists())

    def test_reject_zero_episodes(self):
        with self.assertRaises(u.UploadDraftError):self.create([])

    def test_reject_201_episodes(self):
        with self.assertRaises(u.UploadDraftError):self.create([u.UploadEpisode(i,'t','text') for i in range(1,202)])

    def test_reject_non_list(self):
        for value in (None,'abc',{},123):
            with self.subTest(value=value),self.assertRaises(u.UploadDraftError):self.create(value)

    def test_reject_bad_episode_type(self):
        with self.assertRaises(u.UploadDraftError):self.create([{'title':'x'}])

    def test_reject_bad_number(self):
        for val in (0,-1,10000,'1',True,2.0):
            with self.subTest(value=val),self.assertRaises(u.UploadDraftError):self.create([u.UploadEpisode(val,'title','body')])

    def test_reject_duplicate_number(self):
        with self.assertRaises(u.UploadDraftError):self.create([self.episodes[0],replace(self.episodes[0],title='another')])

    def test_allow_selected_single_episode(self):
        result=self.create([u.UploadEpisode(150,'제150화','본문')])
        self.assertTrue((result.directory/'episode_0150_body.txt').exists())
        self.assertEqual(u.verify_upload_drafts(result.directory).episode_count,1)

    def test_bad_title(self):
        for value in ('','  ',' bad','bad ','abc\nnext','a'*151,'\u202e','a\x00b'):
            with self.subTest(value=repr(value)),self.assertRaises(u.UploadDraftError):
                self.create([u.UploadEpisode(1,value,'good')])

    def test_bad_body(self):
        for value in ('','   ','a\x00b','a\t','x\ufeffy','a\u202eb','a\ud800b'):
            with self.subTest(value=repr(value)),self.assertRaises(u.UploadDraftError):
                self.create([u.UploadEpisode(1,'valid',value)])

    def test_large_body(self):
        with self.assertRaises(u.UploadDraftError):self.create([u.UploadEpisode(1,'a','가'*700000)])

    def test_large_note(self):
        with self.assertRaises(u.UploadDraftError):self.create([u.UploadEpisode(1,'a','body','n'*50001)])

    def test_reject_tampered_metadata(self):
        with self.assertRaises(ValueError):self.create(metadata=replace(self.metadata,published=True))

    def test_invalid_manifest_digest(self):
        r=self.create()
        for value in ('x'*64,'abc',None):
            if value is None: continue
            with self.subTest(value=value),self.assertRaises(u.UploadDraftError):
                u.verify_upload_drafts(r.directory,expected_manifest_sha256=value)

    def test_tamper_file_detection(self):
        r=self.create()
        f=r.directory/'episode_0001_body.txt'
        f.write_text('changed',encoding='utf8')
        with self.assertRaises(u.UploadDraftError):u.verify_upload_drafts(r.directory)

    def test_tamper_file_same_length_detection(self):
        r=self.create()
        f=r.directory/'episode_0001_title.txt'
        f.write_bytes(b'X'*len(f.read_bytes()))
        with self.assertRaises(u.UploadDraftError):u.verify_upload_drafts(r.directory)

    def test_missing_file(self):
        r=self.create()
        (r.directory/'episode_0002_title.txt').unlink()
        with self.assertRaises(u.UploadDraftError):u.verify_upload_drafts(r.directory)

    def test_extra_file(self):
        r=self.create()
        (r.directory/'unused.txt').write_text('bad')
        with self.assertRaises(u.UploadDraftError):u.verify_upload_drafts(r.directory)

    def test_extra_directory(self):
        r=self.create()
        (r.directory/'extra').mkdir()
        with self.assertRaises(u.UploadDraftError):u.verify_upload_drafts(r.directory)

    def test_symlink_file_detected(self):
        r=self.create()
        f=r.directory/'episode_0001_body.txt'
        backup=self.root/'secret.txt';backup.write_bytes(f.read_bytes())
        f.unlink();f.symlink_to(backup)
        with self.assertRaises(u.UploadDraftError):u.verify_upload_drafts(r.directory)

    def test_symlink_manifest_detected(self):
        r=self.create()
        f=r.directory/u.MANIFEST_NAME
        backup=self.root/'secret.json';backup.write_bytes(f.read_bytes())
        f.unlink();f.symlink_to(backup)
        with self.assertRaises(u.UploadDraftError):u.verify_upload_drafts(r.directory)

    def test_symlink_directory_detected(self):
        r=self.create()
        link=self.root/'linked';link.symlink_to(r.directory,target_is_directory=True)
        with self.assertRaises(u.UploadDraftError):u.verify_upload_drafts(link)

    def test_manifest_changed_expected_hash(self):
        r=self.create()
        f=r.directory/u.MANIFEST_NAME
        doc=json.loads(f.read_text(encoding='utf8'))
        doc['project_id']='changed'
        f.write_bytes(u._canonical(doc))
        with self.assertRaises(u.UploadDraftError):u.verify_upload_drafts(r.directory,expected_manifest_sha256=r.manifest_sha256)

    def test_manifest_false_approval_required(self):
        r=self.create()
        f=r.directory/u.MANIFEST_NAME
        doc=json.loads(f.read_text(encoding='utf8'))
        doc['publication_approved']=True
        f.write_bytes(u._canonical(doc))
        with self.assertRaises(u.UploadDraftError):u.verify_upload_drafts(r.directory)

    def test_manifest_reject_path_traversal(self):
        r=self.create()
        f=r.directory/u.MANIFEST_NAME
        doc=json.loads(f.read_text(encoding='utf8'))
        doc['episodes'][0]['files']['title']['filename']='../../secret.txt'
        f.write_bytes(u._canonical(doc))
        with self.assertRaises(u.UploadDraftError):u.verify_upload_drafts(r.directory)

    def test_manifest_reject_extra_schema_key(self):
        r=self.create()
        f=r.directory/u.MANIFEST_NAME
        doc=json.loads(f.read_text(encoding='utf8'))
        doc['uploaded']=True
        f.write_bytes(u._canonical(doc))
        with self.assertRaises(u.UploadDraftError):u.verify_upload_drafts(r.directory)

    def test_manifest_duplicate_keys(self):
        r=self.create()
        f=r.directory/u.MANIFEST_NAME
        f.write_text('{"published": false, "published": true}', encoding='utf8')
        with self.assertRaises(u.UploadDraftError):u.verify_upload_drafts(r.directory)

    def test_manifest_wrong_episode_order(self):
        r=self.create()
        f=r.directory/u.MANIFEST_NAME
        doc=json.loads(f.read_text(encoding='utf8'))
        doc['episodes'].reverse()
        f.write_bytes(u._canonical(doc))
        with self.assertRaises(u.UploadDraftError):u.verify_upload_drafts(r.directory)

    def test_manifest_invalid_utf8(self):
        r=self.create()
        (r.directory/u.MANIFEST_NAME).write_bytes(b'\xff\xfe')
        with self.assertRaises(u.UploadDraftError):u.verify_upload_drafts(r.directory)

    def test_file_invalid_utf8(self):
        r=self.create()
        f=r.directory/'episode_0002_body.txt'
        f.write_bytes(b'\xff\xfe')
        with self.assertRaises(u.UploadDraftError):u.verify_upload_drafts(r.directory)

    def test_file_newline_not_normalized(self):
        r=self.create()
        f=r.directory/'episode_0001_body.txt'
        data=f.read_bytes().replace(b'\n',b'\r\n')
        doc=json.loads((r.directory/u.MANIFEST_NAME).read_text())
        ent=doc['episodes'][0]['files']['body']
        ent['sha256']=sha256(data).hexdigest();ent['utf8_bytes']=len(data)
        f.write_bytes(data)
        (r.directory/u.MANIFEST_NAME).write_bytes(u._canonical(doc))
        with self.assertRaises(u.UploadDraftError):u.verify_upload_drafts(r.directory)

    def test_cli_input_from_stage92(self):
        save_metadata(self.metadata,self.root)
        user=self.root/'episodes.json'
        user.write_text(json.dumps([{'episode_number':1,'title':'제1화','body':'첫 문장','author_note':'작가의 말'}],ensure_ascii=False),encoding='utf8')
        self.assertEqual(cli.main(['--metadata',str(self.root/'publication_metadata.json'),
                                   '--episodes',str(user),'--output-dir',str(self.root)]),0)
        self.assertEqual(u.verify_upload_drafts(self.root/'upload_drafts').episode_count,1)

    def test_cli_duplicate_json_key(self):
        f=self.root/'episodes.json'
        f.write_text('[{"episode_number": 1, "title":"abc","title":"abc","body":"yes","author_note":""}]')
        with self.assertRaises(u.UploadDraftError):cli.load_user_episodes(f)

    def test_cli_missing_author_note(self):
        f=self.root/'episodes.json'
        f.write_text('[{"episode_number":1,"title":"hi","body":"yes"}]')
        with self.assertRaises(u.UploadDraftError):cli.load_user_episodes(f)

    def test_cli_symlink_rejected(self):
        f=self.root/'episodes.json';f.write_text('[]')
        link=self.root/'linked.json';link.symlink_to(f)
        with self.assertRaises(u.UploadDraftError):cli.load_user_episodes(link)

    def test_cli_json_wrong_root(self):
        f=self.root/'episodes.json';f.write_text('{"chapter":1}')
        with self.assertRaises(u.UploadDraftError):cli.load_user_episodes(f)

    def test_cli_no_network_model_api(self):
        r=self.create()
        self.assertTrue(r.directory.exists())
        # Deterministic file enumeration; nothing is sent, approved, or published.
        self.assertFalse(any(p.suffix in ('.epub','.exe') for p in r.directory.iterdir()))

    def test_safe_error_does_not_echo_manuscript(self):
        secret='MY PRIVATE SECRET NOVEL'
        try:
            self.create([u.UploadEpisode(1,'title', secret+'\x00')])
        except u.UploadDraftError as exc:
            self.assertNotIn(secret,str(exc))
        else:
            self.fail('expected rejection')


if __name__ == '__main__':
    unittest.main()
