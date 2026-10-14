"""Stage 80: selective rewriting never changes unflagged Scenes or approves prose."""
from dataclasses import replace
from hashlib import sha256
import socket
import unittest
from unittest.mock import patch

from ai_novel_factory.episode_assembler import EpisodeDraftPreview, SceneSpan
from ai_novel_factory.local_models import SceneDraftResult
from ai_novel_factory.scene_writer import SceneDraftPreview
from ai_novel_factory.scene_revision import (
    SceneIssue, SceneReplacement, SceneRevisionError, rewrite_selected_scenes,
    replacement_from_scene_preview,
)
from ai_novel_factory.repetition_checker import WatchedPhrase
from ai_novel_factory.reference_similarity_checker import ReferenceMaterial, TextSpan
from ai_novel_factory.database.reference_catalog import ReferenceCatalog

PID = 'a' * 32
PARTS = (
    '새벽 항구의 배가 천천히 움직였다.',
    '그는 다시 말했다. 그는 다시 말했다. 그는 다시 말했다. 그는 다시 말했다.',
    '그날 저녁 그들은 숲에서 비밀의 문을 발견했다.',
)
NEW = '그는 오늘부터 같은 말을 반복하지 않기로 결심했다.'
FLAGS = dict(goal_visible=True, tension_present=True, development=True,
             character_choice=True, consequence=True, closing_hook=True)


def h(s):
    return sha256(s.encode('utf-8')).hexdigest()


def original(parts=PARTS, project=PID):
    text = '\n\n'.join(parts)
    pos = 0
    spans = []
    for n, part in enumerate(parts, 1):
        if n > 1:
            pos += 2
        spans.append(SceneSpan(n, pos, pos + len(part), h(part), h('prompt' + str(n)), ('fact-' + str(n),)))
        pos += len(part)
    return EpisodeDraftPreview(project, 5, text, h(text), tuple(spans), ('canon-1',),
                               'offline-mock-v1', 'DETERMINISTIC_MOCK_NOT_AI')


def issue(src, number=2, code='REPETITION'):
    span = src.scenes[number - 1]
    return SceneIssue(number, code, span.start, span.end, h(src.draft[span.start:span.end]))


def replacement(src, number=2, text=NEW):
    return SceneReplacement(number, src.scenes[number - 1].draft_sha256, text, h(text))


def run(src=None, *, issues=None, replacements=None, **kw):
    src = original() if src is None else src
    issues = (issue(src),) if issues is None else issues
    replacements = (replacement(src),) if replacements is None else replacements
    return rewrite_selected_scenes(src, issues=issues, replacements=replacements, **kw)


class Stage80RevisionTests(unittest.TestCase):
    def test_only_flagged_scene_replaced_exactly(self):
        p = run()
        self.assertEqual(p.draft, PARTS[0] + '\n\n' + NEW + '\n\n' + PARTS[2])
        self.assertEqual(p.report.changed_scene_numbers, (2,))
        self.assertEqual([s.changed for s in p.scenes], [False, True, False])
        for number in (1, 3):
            s = p.scenes[number - 1]
            self.assertEqual(p.draft[s.start:s.end], PARTS[number - 1])
            self.assertEqual(s.original_sha256, s.current_sha256)
            self.assertEqual(s.prompt_sha256, h('prompt' + str(number)))

    def test_source_not_modified(self):
        src = original()
        old = src.draft
        run(src)
        self.assertEqual(src.draft, old)
        self.assertEqual(src.draft_sha256, h(old))

    def test_new_offsets_and_hashes_correct(self):
        p = run()
        self.assertEqual(p.draft_sha256, h(p.draft))
        self.assertEqual(p.source_sha256, h(original().draft))
        self.assertEqual(p.scenes[-1].end, len(p.draft))
        for s in p.scenes:
            self.assertEqual(s.current_sha256, h(p.draft[s.start:s.end]))

    def test_no_auto_approval_or_storage(self):
        p = run()
        self.assertEqual(p.status, 'DRAFT_REQUIRES_USER_APPROVAL')
        self.assertEqual(p.report.status, 'REVIEW_REQUIRED_NOT_APPROVED')
        self.assertFalse(p.persisted)
        self.assertFalse(p.publication_approved)
        self.assertFalse(p.report.manuscript_approved)
        self.assertFalse(p.report.publication_approved)
        self.assertFalse(p.report.persisted)
        self.assertIn('user_approval_required', p.report.pending_checks)

    def test_repetition_recheck_on_revised_full_episode(self):
        p = run(watched_phrases=(WatchedPhrase('watch', '그는 다시 말했다', 2),))
        self.assertEqual(p.report.repetition.manuscript_sha256, p.draft_sha256)
        self.assertFalse(any(f.watched_key == 'watch' for f in p.report.repetition.findings))

    def test_unresolved_repetition_remains_flagged(self):
        p = run(replacements=(replacement(original(), text='그는 다시 말했다. 그는 다시 말했다. 그는 다시 말했다.'),),
                watched_phrases=(WatchedPhrase('watch', '그는 다시 말했다', 2),))
        self.assertTrue(any(f.watched_key == 'watch' for f in p.report.repetition.findings))
        self.assertIn('repetition_findings_or_unexamined', p.report.pending_checks)

    def test_missing_reference_and_reader_rechecks_explicit(self):
        p = run()
        self.assertIsNone(p.report.reference_similarity)
        self.assertIsNone(p.report.reader_simulation)
        self.assertIn('reference_similarity_not_rechecked', p.report.pending_checks)
        self.assertIn('fresh_reader_annotations_not_provided', p.report.pending_checks)
        self.assertIn('continuity_logic_style_and_canon_recheck', p.report.pending_checks)

    def test_fresh_reader_annotations_rechecked(self):
        p = run(reader_marks=(FLAGS.copy(), FLAGS.copy(), FLAGS.copy()))
        self.assertEqual(p.report.reader_simulation.draft_sha256, p.draft_sha256)
        self.assertEqual(p.report.reader_simulation.status, 'ANNOTATED_PROXY_ONLY')
        self.assertNotIn('fresh_reader_annotations_not_provided', p.report.pending_checks)

    def test_unknown_reader_marks_are_not_passed(self):
        unknown = {**FLAGS, 'development': None}
        p = run(reader_marks=(FLAGS.copy(), unknown, FLAGS.copy()))
        self.assertIn('reader_annotations_incomplete', p.report.pending_checks)

    def test_reference_recheck_with_registered_reference(self):
        text = '멀리 떨어진 협곡에서는 작은 모래 바람이 끊임없이 불고 있었다.'
        catalog = ReferenceCatalog(':memory:')
        try:
            rec = catalog.register(file_name='reference.txt', source_format='txt',
                                   byte_count=len(text.encode()), sha256=h(text))
            catalog.change_status(rec.reference_id, 'analyzing')
            catalog.change_status(rec.reference_id, 'analyzed')
            ref = ReferenceMaterial(rec.reference_id, rec.sha256, text,
                                    (TextSpan(0, len(text)),),
                                    ('inciting', 'setback', 'resolution', 'transition'))
            p = run(references=(ref,), catalog=catalog, required_reference_ids=(rec.reference_id,),
                    draft_beats=('setup', 'reversal', 'escalation', 'climax', 'hook'))
            self.assertIsNotNone(p.report.reference_similarity)
            self.assertEqual(p.report.reference_similarity.draft_sha256, p.draft_sha256)
            self.assertTrue(p.report.reference_similarity.registration_checked)
            self.assertNotIn('reference_similarity_not_rechecked', p.report.pending_checks)
        finally:
            catalog.close()

    def test_unregistered_reference_not_called_clear(self):
        text = '멀리 떨어진 협곡에서는 작은 모래 바람이 끊임없이 불고 있었다.'
        ref = ReferenceMaterial('b' * 32, h(text), text, (TextSpan(0, len(text)),),
                                ('inciting', 'setback', 'resolution', 'transition'))
        p = run(references=(ref,), draft_beats=('setup', 'reversal', 'escalation', 'climax', 'hook'))
        self.assertIn('reference_similarity_not_cleared', p.report.pending_checks)

    def test_original_reference_prose_not_in_report(self):
        p = run()
        self.assertNotIn(PARTS[0], repr(p.report))
        self.assertNotIn(NEW, repr(p.report))
        self.assertNotIn(NEW, repr(p))

    def test_issues_bound_to_original_evidence(self):
        src = original()
        broken = replace(issue(src), evidence_sha256='f' * 64)
        with self.assertRaises(SceneRevisionError):
            run(src, issues=(broken,))

    def test_issue_offsets_outside_scene_rejected(self):
        src = original()
        bad = replace(issue(src), start=0)
        with self.assertRaises(SceneRevisionError):
            run(src, issues=(bad,))

    def test_issue_bad_code_rejected(self):
        with self.assertRaises(SceneRevisionError):
            run(issues=(replace(issue(original()), code='UNKNOWN'),))

    def test_issue_duplicate_rejected(self):
        i = issue(original())
        with self.assertRaises(SceneRevisionError):
            run(issues=(i, i))

    def test_issue_missing_replacement_rejected(self):
        src = original()
        with self.assertRaises(SceneRevisionError):
            run(src, issues=(issue(src), issue(src, 3)))

    def test_replacement_without_issue_rejected(self):
        src = original()
        with self.assertRaises(SceneRevisionError):
            run(src, replacements=(replacement(src), replacement(src, 3, '새로운 사건.')))

    def test_duplicate_replacement_rejected(self):
        r = replacement(original())
        with self.assertRaises(SceneRevisionError):
            run(replacements=(r, r))

    def test_replacement_wrong_original_hash_rejected(self):
        with self.assertRaises(SceneRevisionError):
            run(replacements=(replace(replacement(original()), original_sha256='0'*64),))

    def test_replacement_wrong_new_hash_rejected(self):
        with self.assertRaises(SceneRevisionError):
            run(replacements=(replace(replacement(original()), revised_sha256='0'*64),))

    def test_replacement_must_change_text(self):
        src = original()
        with self.assertRaises(SceneRevisionError):
            run(src, replacements=(replacement(src, text=PARTS[1]),))

    def test_two_selected_scenes_change_only_them(self):
        src = original()
        p = run(src, issues=(issue(src, 1, 'MANUAL'), issue(src, 3, 'LOGIC')),
                replacements=(replacement(src, 3, '마지막 장면이 바뀌었다.'),
                              replacement(src, 1, '처음 장면이 바뀌었다.')))
        self.assertEqual(p.report.changed_scene_numbers, (1, 3))
        self.assertEqual(p.draft[p.scenes[1].start:p.scenes[1].end], PARTS[1])

    def test_source_modified_hash_rejected(self):
        with self.assertRaises(SceneRevisionError):
            run(replace(original(), draft=original().draft + '변조'))

    def test_source_modified_scene_hash_rejected(self):
        src = original()
        with self.assertRaises(SceneRevisionError):
            run(replace(src, scenes=(src.scenes[0], replace(src.scenes[1], draft_sha256='0'*64), src.scenes[2])))

    def test_source_wrong_scene_boundaries_rejected(self):
        src = original()
        with self.assertRaises(SceneRevisionError):
            run(replace(src, scenes=(src.scenes[0], replace(src.scenes[1], start=0), src.scenes[2])))

    def test_source_not_unapproved_rejected(self):
        src = original()
        for value in (replace(src, status='APPROVED'), replace(src, persisted=True),
                      replace(src, publication_approved=True)):
            with self.subTest(value=value.status), self.assertRaises(SceneRevisionError):
                run(value)

    def test_invalid_unicode_rejected(self):
        with self.assertRaises(SceneRevisionError):
            run(replacements=(SceneReplacement(2, original().scenes[1].draft_sha256, 'bad\ud800', '0'*64),))

    def test_invalid_control_character_rejected(self):
        with self.assertRaises(SceneRevisionError):
            run(replacements=(replacement(original(), text='secret\x00text'),))

    def test_empty_replacement_rejected(self):
        with self.assertRaises(SceneRevisionError):
            run(replacements=(replacement(original(), text=' \n'),))

    def test_mismatched_reference_inputs_rejected(self):
        with self.assertRaises(SceneRevisionError):
            run(required_reference_ids=('b'*32,))

    def test_invalid_reader_mark_rejected(self):
        with self.assertRaises(SceneRevisionError):
            run(reader_marks=(FLAGS.copy(), {**FLAGS, 'development': 1}, FLAGS.copy()))

    def test_missing_reader_mark_rejected(self):
        with self.assertRaises(SceneRevisionError):
            run(reader_marks=(FLAGS.copy(), FLAGS.copy()))

    def test_replacement_prompt_provenance_not_forged(self):
        p = run()
        self.assertEqual(p.scenes[1].origin, 'REVIEWER_SUPPLIED')
        self.assertIsNone(p.scenes[1].prompt_sha256)
        self.assertEqual(p.scenes[0].origin, 'UNCHANGED_SOURCE')

    def test_stage64_preview_adapter(self):
        src = original()
        result = SceneDraftResult(PID, 5, 2, NEW, 'offline-mock-v1')
        preview = SceneDraftPreview(result, h('new prompt'), h(NEW), ('canon-1',),
                                    ('fact-2',), 'DETERMINISTIC_MOCK_NOT_AI')
        r = replacement_from_scene_preview(src, preview)
        p = run(src, replacements=(r,))
        self.assertEqual(p.scenes[1].origin, 'STAGE64_PREVIEW')
        self.assertEqual(p.scenes[1].prompt_sha256, h('new prompt'))

    def test_stage64_preview_rejects_wrong_canon(self):
        src = original()
        result = SceneDraftResult(PID, 5, 2, NEW, 'offline-mock-v1')
        preview = SceneDraftPreview(result, h('new prompt'), h(NEW), ('wrong',),
                                    ('fact-2',), 'DETERMINISTIC_MOCK_NOT_AI')
        with self.assertRaises(SceneRevisionError):
            replacement_from_scene_preview(src, preview)

    def test_stage64_preview_rejects_changed_text(self):
        src = original()
        result = SceneDraftResult(PID, 5, 2, NEW + '변조', 'offline-mock-v1')
        preview = SceneDraftPreview(result, h('new prompt'), h(NEW), ('canon-1',),
                                    ('fact-2',), 'DETERMINISTIC_MOCK_NOT_AI')
        with self.assertRaises(SceneRevisionError):
            replacement_from_scene_preview(src, preview)

    def test_stage64_preview_rejects_cross_project(self):
        src = original()
        result = SceneDraftResult('b'*32, 5, 2, NEW, 'offline-mock-v1')
        preview = SceneDraftPreview(result, h('new prompt'), h(NEW), ('canon-1',),
                                    ('fact-2',), 'DETERMINISTIC_MOCK_NOT_AI')
        with self.assertRaises(SceneRevisionError):
            replacement_from_scene_preview(src, preview)

    def test_stage64_preview_rejects_wrong_provider(self):
        src = original()
        result = SceneDraftResult(PID, 5, 2, NEW, 'local-executable-v1')
        preview = SceneDraftPreview(result, h('new prompt'), h(NEW), ('canon-1',),
                                    ('fact-2',), 'LOCAL_EXECUTABLE_OUTPUT_NOT_VERIFIED_AS_AI')
        with self.assertRaises(SceneRevisionError):
            replacement_from_scene_preview(src, preview)

    def test_reject_empty_issue_or_replacement(self):
        for issues, repl in (((), (replacement(original()),)), ((issue(original()),), ())):
            with self.assertRaises(SceneRevisionError):
                run(issues=issues, replacements=repl)

    def test_reject_bool_scene_number(self):
        with self.assertRaises(SceneRevisionError):
            run(issues=(replace(issue(original()), scene_number=True),))

    def test_redacted_error(self):
        secret = 'VERY_PRIVATE_MANUSCRIPT_SECRET'
        with self.assertRaises(SceneRevisionError) as cm:
            run(replacements=(replacement(original(), text=secret+'\x00'),))
        self.assertNotIn(secret, str(cm.exception))

    def test_source_wrong_provider_type_rejected(self):
        with self.assertRaises(SceneRevisionError):
            run(replace(original(), provider=['offline-mock-v1']))

    def test_stage64_preview_wrong_result_type_rejected(self):
        with self.assertRaises(SceneRevisionError):
            replacement_from_scene_preview(original(), SceneDraftPreview(
                None, h('prompt'), h(NEW), ('canon-1',), ('fact-2',),
                'DETERMINISTIC_MOCK_NOT_AI'))

    def test_stage64_preview_rejects_approved_or_persisted(self):
        src = original()
        result = SceneDraftResult(PID, 5, 2, NEW, 'offline-mock-v1')
        preview = SceneDraftPreview(result, h('new prompt'), h(NEW), ('canon-1',),
                                    ('fact-2',), 'DETERMINISTIC_MOCK_NOT_AI')
        for altered in (replace(preview, publication_approved=True),
                        replace(preview, persisted=True),
                        replace(preview, result=replace(result, persisted=True))):
            with self.assertRaises(SceneRevisionError):
                replacement_from_scene_preview(src, altered)

    def test_real_stage65_assembly_to_stage80_revision(self):
        from ai_novel_factory.episode_assembler import assemble_episode_draft
        from ai_novel_factory.episode_context import ContextFact, select_episode_context
        from ai_novel_factory.episode_planner import EpisodePlan
        from ai_novel_factory.scene_planner import ScenePlan
        from ai_novel_factory.scene_writer import generate_scene_draft
        from ai_novel_factory.local_models import MockSceneProvider
        ep = EpisodePlan(5, 1, '비밀의 문', ('문 찾기',), ('hero',), '', (), '마지막 갈등')
        plans = (
            ScenePlan(5, 1, '숲', ('hero',), '단서 찾기', '폭풍', '긴장'),
            ScenePlan(5, 2, '마을', ('hero',), '비밀 밝히기', '추적', '불안'),
        )
        facts = (ContextFact(PID, 'novel_bible', 'core', '세계관의 핵심 법칙'),
                 ContextFact(PID, 'character', 'hero-fact', '주인공은 탐험가', character_ids=('hero',)))
        ctx = select_episode_context(PID, ep, facts)
        drafts = tuple(generate_scene_draft(PID, ep, plan, ctx, MockSceneProvider()) for plan in plans)
        assembled = assemble_episode_draft(PID, ep, plans, drafts)
        new_scene = '그는 오래된 문 앞에서 새로운 단서를 발견했다.'
        revised = rewrite_selected_scenes(
            assembled, issues=(issue(assembled, 2, 'MANUAL'),),
            replacements=(replacement(assembled, 2, new_scene),),
        )
        self.assertEqual(revised.draft[revised.scenes[0].start:revised.scenes[0].end],
                         drafts[0].result.draft)
        self.assertEqual(revised.draft[revised.scenes[1].start:revised.scenes[1].end], new_scene)
        self.assertEqual(revised.canon_fact_ids, assembled.canon_fact_ids)
        self.assertFalse(revised.publication_approved)

    def test_no_disk_or_network_side_effects(self):
        with patch('builtins.open', side_effect=AssertionError('unexpected disk access')):
            with patch.object(socket.socket, 'connect', side_effect=AssertionError('unexpected network')):
                self.assertFalse(run().persisted)


if __name__ == '__main__':
    unittest.main()
