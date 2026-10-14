"""Stage 96: user-supplied, UNVERIFIED offline platform format comparisons."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory.platform_format_audit import (
    PlatformAuditError, UnverifiedPlatformRules, check_platform_format,
    validate_rules, write_local_audit_report,
)
from ai_novel_factory.episode_upload_files import UploadEpisode, export_upload_drafts
from ai_novel_factory.epub3 import Chapter, create_epub
from ai_novel_factory.publication_metadata import MetadataDraft, save_metadata


class PlatformFormatAuditTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.meta = MetadataDraft('story_1', '별과 길', '작가', '독창적인 새로운 이야기',
                                  '판타지', ('모험', '성장'), '0')
        saved = save_metadata(self.meta, self.root)
        self.meta_path, self.meta_hash = saved.path, sha256(saved.path.read_bytes()).hexdigest()
        self.episodes = [UploadEpisode(1, '제1화 시작', '첫 번째 원고입니다.', '감사합니다.'),
                         UploadEpisode(2, '제2화 귀환', '두 번째 원고입니다.', '')]
        output = export_upload_drafts(self.meta, self.episodes, self.root)
        self.directory, self.draft_hash = output.directory, output.manifest_sha256
        self.rules = UnverifiedPlatformRules('hypothetical_01', ('TXT_EPISODES',), 100,
                                               300000, 10000, 10, ('ko',))

    def check(self, rules=None, **kw):
        params = dict(draft_directory=self.directory, expected_draft_sha256=self.draft_hash,
                      metadata_file=self.meta_path, expected_metadata_sha256=self.meta_hash)
        params.update(kw)
        return check_platform_format(rules or self.rules, **params)

    def test_offline_match_is_not_real_upload_possibility(self):
        result = self.check()
        self.assertEqual(result.status, 'LOCAL_DECLARED_MATCH_ONLY')
        self.assertFalse(result.finding_codes)
        self.assertFalse(result.official_rules_verified)
        self.assertFalse(result.official_api_verified)
        self.assertFalse(result.actual_upload_tested)
        self.assertEqual(result.actual_upload_possible, 'UNKNOWN')
        self.assertFalse(result.publication_executed)
        self.assertNotIn('첫 번째 원고', repr(result))
        self.assertNotIn('별과 길', repr(result))
        self.assertEqual(result.episode_count, 2)

    def test_constraints_are_user_claims_only(self):
        self.assertEqual(self.check().rules_origin, 'USER_SUPPLIED_UNVERIFIED')
        self.assertEqual(validate_rules(self.rules), self.rules)

    def test_combined_mismatch_codes(self):
        other = replace(self.rules, accepted_formats=('EPUB3',), languages=('en',),
                        max_title_characters=2, max_body_bytes=1,
                        max_author_note_bytes=1, max_episodes=1,
                        max_keywords=1)
        result = self.check(other)
        self.assertEqual(result.status, 'LOCAL_DECLARED_MISMATCH')
        self.assertEqual(set(result.finding_codes), {
            'DECLARED_FORMAT_NOT_ACCEPTED', 'DECLARED_LANGUAGE_NOT_ACCEPTED',
            'DECLARED_WORK_TITLE_LIMIT_EXCEEDED', 'DECLARED_EPISODE_TITLE_LIMIT_EXCEEDED',
            'DECLARED_BODY_SIZE_LIMIT_EXCEEDED', 'DECLARED_AUTHOR_NOTE_LIMIT_EXCEEDED',
            'DECLARED_EPISODE_LIMIT_EXCEEDED', 'DECLARED_KEYWORDS_LIMIT_EXCEEDED',
        })
        self.assertEqual(result.actual_upload_possible, 'UNKNOWN')

    def test_status_is_bound_to_profile(self):
        a = self.check()
        b = self.check(replace(self.rules, max_body_bytes=200))
        self.assertNotEqual(a.evidence_sha256, b.evidence_sha256)

    def test_epub_valid_local_comparison(self):
        chapters = [Chapter('제1화 시작', '첫 번째 원고입니다.'), Chapter('제2화 귀환', '두 번째 원고입니다.')]
        epub = create_epub(self.meta, chapters, self.root)
        rules = replace(self.rules, accepted_formats=('EPUB3',))
        report = self.check(rules, content_format='EPUB3',
                            epub_path=epub.path, expected_epub_sha256=epub.sha256)
        self.assertEqual(report.status, 'LOCAL_DECLARED_MATCH_ONLY')
        self.assertEqual(report.inspected_format, 'EPUB3')
        self.assertFalse(report.actual_upload_tested)

    def test_epub_without_anchor_rejected(self):
        with self.assertRaises(PlatformAuditError): self.check(content_format='EPUB3')

    def test_epub_mismatch_with_anchor_rejected(self):
        epub = create_epub(self.meta, [Chapter('a', 'b'), Chapter('c', 'd')], self.root)
        with self.assertRaises(PlatformAuditError):
            self.check(content_format='EPUB3', epub_path=epub.path,
                       expected_epub_sha256='0'*64)

    def test_epub_chapter_count_mismatch_rejected(self):
        epub = create_epub(self.meta, [Chapter('a', 'b')], self.root)
        with self.assertRaises(PlatformAuditError):
            self.check(content_format='EPUB3', epub_path=epub.path,
                       expected_epub_sha256=epub.sha256)

    def test_extra_epub_arguments_for_txt_rejected(self):
        with self.assertRaises(PlatformAuditError): self.check(epub_path='unused')

    def test_wrong_format_rejected(self):
        with self.assertRaises(PlatformAuditError): self.check(content_format='PDF')

    def test_manifest_digest_required(self):
        for s in ('', 'x'*64, '0'*63, True, None):
            with self.subTest(s=s), self.assertRaises(PlatformAuditError):
                self.check(expected_draft_sha256=s)

    def test_metadata_digest_required(self):
        for s in ('', 'x'*64, '0'*63, True):
            with self.subTest(s=s), self.assertRaises(PlatformAuditError):
                self.check(expected_metadata_sha256=s)

    def test_metadata_byte_tampering_rejected(self):
        self.meta_path.write_bytes(self.meta_path.read_bytes()+b' ')
        with self.assertRaises(PlatformAuditError): self.check()

    def test_body_byte_tampering_rejected(self):
        (self.directory / 'episode_0001_body.txt').write_text('본문변경', encoding='utf8')
        with self.assertRaises(PlatformAuditError): self.check()

    def test_author_note_byte_tampering_rejected(self):
        (self.directory / 'episode_0001_author_note.txt').write_text('수정', encoding='utf8')
        with self.assertRaises(PlatformAuditError): self.check()

    def test_manifest_byte_tampering_rejected(self):
        (self.directory / 'manifest.json').write_bytes(b'{}\n')
        with self.assertRaises(PlatformAuditError): self.check()

    def test_report_contains_no_prose_and_no_credentials(self):
        result = self.check()
        path = write_local_audit_report(result, self.root)
        data = json.loads(path.read_text('ascii'))
        self.assertEqual(data['actual_upload_possible'], 'UNKNOWN')
        self.assertFalse(data['publication_executed'])
        self.assertEqual(data['rules_origin'], 'USER_SUPPLIED_UNVERIFIED')
        self.assertNotIn(self.meta.title, path.read_text())
        self.assertNotIn(self.episodes[0].body, path.read_text())
        if os.name != 'nt':
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        # Windows ACLs are not represented by POSIX st_mode; audit separately.
        with self.assertRaises(PlatformAuditError): write_local_audit_report(result, self.root)

    def test_report_symlink_denied(self):
        external = self.root / 'target'
        external.write_text('safe')
        symlink = self.root / 'platform_audit_hypothetical_01.json'
        symlink.symlink_to(external)
        with self.assertRaises(PlatformAuditError): write_local_audit_report(self.check(), self.root)
        self.assertEqual(external.read_text(), 'safe')

    def test_report_cannot_launder_fake_platform_verification(self):
        original = self.check()
        for key, value in [('actual_upload_possible', 'YES'), ('official_rules_verified', True),
                           ('official_api_verified', True), ('actual_upload_tested', True),
                           ('publication_executed', True), ('rules_origin', 'OFFICIAL')]:
            with self.subTest(key=key), self.assertRaises(PlatformAuditError):
                write_local_audit_report(replace(original, **{key:value}), self.root)

    def test_report_path_traversal_is_rejected(self):
        with self.assertRaises(PlatformAuditError):
            write_local_audit_report(replace(self.check(), profile_id='../escape'), self.root)

    def test_report_fake_match_with_findings_is_rejected(self):
        with self.assertRaises(PlatformAuditError):
            write_local_audit_report(replace(self.check(), finding_codes=('MISMATCH',)), self.root)

    def test_report_invalid_output_directory_rejected(self):
        with self.assertRaises(PlatformAuditError):
            write_local_audit_report(self.check(), self.root / 'missing')

    def test_source_spoofing_rejected(self):
        for source in ('OFFICIAL', '', None):
            with self.subTest(source=source), self.assertRaises(PlatformAuditError):
                self.check(replace(self.rules, source=source))

    def test_invalid_profile_ids_rejected(self):
        for profile_id in ('../a', '.hidden', 'a/b', '', '한글', 'x'*65):
            with self.subTest(id=profile_id), self.assertRaises(PlatformAuditError):
                self.check(replace(self.rules, profile_id=profile_id))

    def test_invalid_format_rules_rejected(self):
        for fmts in ((), ('PDF',), ('TXT_EPISODES', 'TXT_EPISODES'), ['TXT_EPISODES'], ('',)):
            with self.subTest(formats=fmts), self.assertRaises(PlatformAuditError):
                self.check(replace(self.rules, accepted_formats=fmts))

    def test_invalid_limits_rejected(self):
        for field, number in [('max_title_characters', 0), ('max_body_bytes', 0),
                              ('max_author_note_bytes', -1), ('max_episodes', 0),
                              ('max_episodes', True), ('max_keywords', -1),
                              ('max_body_bytes', 20000001)]:
            with self.subTest(field=field, value=number), self.assertRaises(PlatformAuditError):
                self.check(replace(self.rules, **{field:number}))

    def test_invalid_languages_rejected(self):
        for value in ((), ('ko', 'ko'), ('unknown',), ['ko'], ('',)):
            with self.subTest(value=value), self.assertRaises(PlatformAuditError):
                self.check(replace(self.rules, languages=value))

    def test_flag_type_must_be_boolean(self):
        with self.assertRaises(PlatformAuditError):
            self.check(replace(self.rules, require_category=1))

    def test_ignores_any_claim_of_real_platform_success(self):
        result = self.check()
        self.assertEqual(result.actual_upload_possible, 'UNKNOWN')
        self.assertFalse(result.official_rules_verified)
        self.assertEqual(result.episode_count, 2)


if __name__ == '__main__':
    unittest.main()
