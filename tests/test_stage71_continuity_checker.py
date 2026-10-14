"""Stage 71 offline, evidence-based continuity tests (no NLP or network)."""
import dataclasses
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ai_novel_factory.continuity_checker import (
    CanonFact, ContinuityCanon, ContinuityError, ManuscriptClaim,
    check_continuity, load_continuity_canon,
)
from ai_novel_factory.database.novel_bible import NovelBibleStore
from ai_novel_factory.database.characters import CharacterStore
from ai_novel_factory.database.world_canon import WorldCanonStore


class TestContinuityChecker(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / 'canon.sqlite'
        self.bible = NovelBibleStore(path)
        self.addCleanup(self.bible.close)
        self.characters = CharacterStore(path)
        self.addCleanup(self.characters.close)
        self.world = WorldCanonStore(path)
        self.addCleanup(self.world.close)
        self.project = self.bible.create_project('새 소설')
        self.other = self.bible.create_project('다른 소설')
        self.age = self.bible.save_rule(self.project.project_id, 'protagonist_age', '34')
        self.job = self.bible.save_rule(self.project.project_id, 'protagonist_job', '기업가')
        self.hero = self.characters.create_character(self.project.project_id, name='김가람',
                                                      personality='신중함', goal='도시를 구한다',
                                                      speech_style='짧게 말함', secret='비밀인 기억')
        self.region = self.world.create_entry(self.project.project_id, category='region',
                                               name='서광시', description='도시 외곽')
        self.canon = self.load()

    def load(self):
        return load_continuity_canon(self.project.project_id, bible=self.bible,
                                     characters=self.characters, world=self.world)

    def claim(self, source, key, field, manuscript, value):
        start = manuscript.index(value)
        return ManuscriptClaim(source, key, field, start, start + len(value), value)

    def check(self, manuscript, *claims, **kwargs):
        return check_continuity(self.canon, 5, manuscript, tuple(claims), **kwargs)

    def test_loads_all_expected_canon_without_secret(self):
        self.assertEqual(len(self.canon.facts), 2 + 4 + 2)
        self.assertTrue(all('비밀인 기억' not in f.value for f in self.canon.facts))
        self.assertEqual({f.source for f in self.canon.facts}, {'novel_bible', 'character', 'world'})

    def test_conflicting_age_reports_exact_offsets_and_hashes_only(self):
        text = '주인공 나이는 29세라고 기록했다.'
        claim = self.claim('novel_bible', 'protagonist_age', 'value', text, '29')
        report = self.check(text, claim)
        self.assertEqual(len(report.findings), 1)
        f = report.findings[0]
        self.assertEqual(f.code, 'CANON_CONFLICT')
        self.assertEqual(text[f.start:f.end], '29')
        self.assertEqual(len(f.canon_sha256), 64)
        self.assertFalse(report.persisted)
        self.assertFalse(report.publication_approved)
        self.assertNotIn('29', str(f))
        self.assertNotIn('34', str(f))

    def test_matched_declared_claim_does_not_report_false_conflict(self):
        text = '주인공 나이는 34세다.'
        claim = self.claim('novel_bible', 'protagonist_age', 'value', text, '34')
        result = self.check(text, claim)
        self.assertEqual(result.examined_claims, 1)
        self.assertTrue(result.passed_declared_claims)
        self.assertEqual(result.status, 'REQUIRES_HUMAN_REVIEW_NOT_FULL_QC')

    def test_job_and_character_name_and_world_region_conflicts(self):
        text = '직업은 군인, 이름은 강가람, 지역은 동해시.'
        claims = (
            self.claim('novel_bible', 'protagonist_job', 'value', text, '군인'),
            self.claim('character', self.hero.character_id, 'name', text, '강가람'),
            self.claim('world', self.region.entry_id, 'name', text, '동해시'),
        )
        result = self.check(text, *claims)
        self.assertEqual([f.source for f in result.findings], ['novel_bible', 'character', 'world'])
        self.assertEqual(result.examined_claims, 3)

    def test_character_personality_goal_speech_and_world_description(self):
        text = '성격은 거침없음, 목표는 부자가 됨, 말투는 길게 말함, 지형은 산악 지대.'
        fields = (('character', self.hero.character_id, 'personality', '거침없음'),
                  ('character', self.hero.character_id, 'goal', '부자가 됨'),
                  ('character', self.hero.character_id, 'speech_style', '길게 말함'),
                  ('world', self.region.entry_id, 'description', '산악 지대'))
        self.assertEqual(len(self.check(text, *(self.claim(*entry[:3], text, entry[3]) for entry in fields)).findings), 4)

    def test_no_claims_does_not_mean_full_quality_check(self):
        report = self.check('설정에 위배되는 대사가 있다.')
        self.assertTrue(report.passed_declared_claims)
        self.assertEqual(report.examined_claims, 0)
        self.assertEqual(report.status, 'REQUIRES_HUMAN_REVIEW_NOT_FULL_QC')

    def test_nfc_normalization_for_korean(self):
        # Exact evidence matches the manuscript, but Unicode canon comparison uses NFC.
        self.bible.save_rule(self.project.project_id, 'decomposed', '가')
        self.canon = self.load()
        decomposed = '\u1100\u1161'
        self.assertFalse(self.check(decomposed, self.claim('novel_bible', 'decomposed', 'value', decomposed, decomposed)).findings)

    def test_stale_revision_rejected(self):
        with self.assertRaisesRegex(ContinuityError, 'stale'):
            self.check('34', expected_project_revision=self.canon.project_revision - 1)
        self.bible.save_rule(self.project.project_id, 'new_field', '추가')
        fresh = self.load()
        self.assertNotEqual(fresh.project_revision, self.canon.project_revision)

    def test_snapshot_load_detects_revision_disagreement(self):
        self.bible.save_rule(self.project.project_id, 'x', '변경')
        with patch.object(self.world, 'get_project', return_value=dataclasses.replace(
                self.world.get_project(self.project.project_id), revision=-1)):
            with self.assertRaisesRegex(ContinuityError, 'inconsistent'):
                self.load()

    def test_another_projects_record_not_loaded(self):
        self.bible.save_rule(self.other.project_id, 'foreign', '절대 섞이면 안 된다')
        self.characters.create_character(self.other.project_id, name='외부인', personality='침착',
                                          goal='여행', speech_style='정중')
        self.world.create_entry(self.other.project_id, category='region', name='타지역', description='타지역 안내')
        self.canon = self.load()
        self.assertEqual(len(self.canon.facts), 8)
        self.assertFalse(any(f.entity_id == 'foreign' for f in self.canon.facts))

    def test_foreign_project_identity_rejected(self):
        other_canon = load_continuity_canon(self.other.project_id, bible=self.bible,
                                             characters=self.characters, world=self.world)
        with self.assertRaises(ContinuityError):
            check_continuity(other_canon, 1, '원고', (ManuscriptClaim(
                'novel_bible', 'protagonist_age', 'value', 0, 2, '원고'),))

    def test_reference_source_is_not_supported(self):
        for source in ('reference', 'reference_novel', 'style_statistics'):
            with self.subTest(source=source), self.assertRaises(ContinuityError):
                self.check('34', ManuscriptClaim(source, 'protagonist_age', 'value', 0, 2, '34'))

    def test_private_character_secret_is_not_checkable(self):
        with self.assertRaises(ContinuityError):
            self.check('비밀인 기억', ManuscriptClaim('character', self.hero.character_id,
                                                  'secret', 0, 6, '비밀인 기억'))

    def test_unstored_entity_rejected(self):
        with self.assertRaisesRegex(ContinuityError, 'missing canon'):
            self.check('34', ManuscriptClaim('novel_bible', 'missing', 'value', 0, 2, '34'))

    def test_mismatched_span_rejected(self):
        with self.assertRaisesRegex(ContinuityError, 'span'):
            self.check('age: 31', ManuscriptClaim('novel_bible', 'protagonist_age', 'value', 5, 7, '30'))

    def test_invalid_boundaries_rejected(self):
        for start, end in ((-1, 2), (0, 0), (0, 9), (True, 2), (0, False)):
            with self.subTest(start=start, end=end), self.assertRaises(ContinuityError):
                self.check('34', ManuscriptClaim('novel_bible', 'protagonist_age', 'value', start, end, '34'))

    def test_duplicate_claim_rejected(self):
        c = ManuscriptClaim('novel_bible', 'protagonist_age', 'value', 0, 2, '34')
        with self.assertRaises(ContinuityError): self.check('34', c, c)

    def test_duplicate_canon_facts_rejected(self):
        canon = dataclasses.replace(self.canon, facts=self.canon.facts * 2)
        with self.assertRaises(ContinuityError): check_continuity(canon, 1, '원고', ())

    def test_invalid_fact_revision_rejected(self):
        facts = (dataclasses.replace(self.canon.facts[0], revision=True),)
        with self.assertRaises(ContinuityError):
            check_continuity(dataclasses.replace(self.canon, facts=facts), 1, '원고', ())

    def test_invalid_fact_type_rejected(self):
        with self.assertRaises(ContinuityError):
            check_continuity(dataclasses.replace(self.canon, facts=('wrong',)), 1, '원고', ())

    def test_invalid_episode_and_text_rejected(self):
        for ep in (0, -1, True, 1.5, 1_000_001):
            with self.assertRaises(ContinuityError): check_continuity(self.canon, ep, '원고', ())
        for text in ('', None, '\ud800', 'x' * 1_000_001):
            with self.assertRaises(ContinuityError): check_continuity(self.canon, 1, text, ())

    def test_bounded_claims_and_facts(self):
        with self.assertRaises(ContinuityError):
            self.check('원고', *(ManuscriptClaim('novel_bible', 'protagonist_age', 'value', 0, 1, '원') for _ in range(501)))
        with self.assertRaises(ContinuityError):
            check_continuity(dataclasses.replace(self.canon, facts=self.canon.facts * 400), 1, '원고', ())

    def test_rejects_non_tuple_claims_and_invalid_types(self):
        for claims in ([], 'wrong', 1, (None,)):
            with self.subTest(claims=str(claims)), self.assertRaises(ContinuityError):
                check_continuity(self.canon, 1, '원고', claims)

    def test_claim_does_not_disclose_conflicting_values(self):
        text = '직업: 군인'
        report = self.check(text, self.claim('novel_bible', 'protagonist_job', 'value', text, '군인'))
        self.assertNotIn('군인', repr(report))
        self.assertNotIn('기업가', repr(report))

    def test_deterministic_read_only_check(self):
        before = self.bible.get_project(self.project.project_id).revision
        text = '나이 99'
        claim = self.claim('novel_bible', 'protagonist_age', 'value', text, '99')
        self.assertEqual(self.check(text, claim), self.check(text, claim))
        self.assertEqual(self.bible.get_project(self.project.project_id).revision, before)

    def test_bad_snapshot_project_id_rejected(self):
        with self.assertRaises(ContinuityError):
            check_continuity(dataclasses.replace(self.canon, project_id='bad'), 1, '원고', ())

    def test_load_wrong_project_fails_closed(self):
        with self.assertRaises(ContinuityError):
            load_continuity_canon('f' * 32, bible=self.bible, characters=self.characters, world=self.world)

    def test_load_canon_after_character_edit(self):
        updated = self.characters.update_character(self.project.project_id, self.hero.character_id,
                                                     expected_revision=self.hero.revision, name='김다온')
        self.canon = self.load()
        self.assertEqual(next(f.value for f in self.canon.facts if f.source == 'character' and f.field == 'name'), updated.name)


if __name__ == '__main__':
    unittest.main()

class TestEpisodePreviewAdapter(unittest.TestCase):
    def setUp(self):
        from ai_novel_factory.episode_assembler import EpisodeDraftPreview
        from hashlib import sha256
        self.project = 'a' * 32
        self.canon = ContinuityCanon(self.project, 1, (
            CanonFact('novel_bible', 'age', 'value', '34', 1),))
        draft = '주인공 나이 26'
        self.preview = EpisodeDraftPreview(self.project, 2, draft, sha256(draft.encode()).hexdigest(),
                                           (), (), 'offline-mock-v1', 'DETERMINISTIC_MOCK_NOT_AI')

    def test_preview_manual_claim_is_checked(self):
        from ai_novel_factory.continuity_checker import check_episode_draft
        result = check_episode_draft(self.canon, self.preview,
                                     (ManuscriptClaim('novel_bible', 'age', 'value', 7, 9, '26'),))
        self.assertEqual(len(result.findings), 1)
        self.assertEqual(result.episode_number, 2)

    def test_altered_draft_rejected(self):
        from ai_novel_factory.continuity_checker import check_episode_draft
        with self.assertRaises(ContinuityError):
            check_episode_draft(self.canon, dataclasses.replace(self.preview, draft='변조'), ())

    def test_another_project_rejected(self):
        from ai_novel_factory.continuity_checker import check_episode_draft
        with self.assertRaises(ContinuityError):
            check_episode_draft(dataclasses.replace(self.canon, project_id='b' * 32), self.preview, ())

    def test_approved_or_persisted_previews_rejected(self):
        from ai_novel_factory.continuity_checker import check_episode_draft
        for key, value in (('status', 'PUBLISHED'), ('persisted', True), ('publication_approved', True)):
            with self.subTest(key=key), self.assertRaises(ContinuityError):
                check_episode_draft(self.canon, dataclasses.replace(self.preview, **{key: value}), ())

    def test_stale_revision_rejected(self):
        from ai_novel_factory.continuity_checker import check_episode_draft
        with self.assertRaises(ContinuityError):
            check_episode_draft(self.canon, self.preview, (), expected_project_revision=2)
