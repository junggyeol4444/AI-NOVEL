"""Stage 65: ordered episode-draft assembly and fail-closed safety invariants."""
from dataclasses import replace
from hashlib import sha256
import socket
import unittest
from unittest.mock import patch

from ai_novel_factory.episode_assembler import (
    EpisodeAssemblyError, assemble_episode_draft, MAX_EPISODE_DRAFT_CHARS,
)
from ai_novel_factory.episode_context import ContextFact, select_episode_context
from ai_novel_factory.episode_planner import EpisodePlan
from ai_novel_factory.local_models import MockSceneProvider, SceneDraftResult
from ai_novel_factory.scene_planner import ScenePlan
from ai_novel_factory.scene_writer import generate_scene_draft


class Stage65EpisodeAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.project = 'novel-1'
        self.episode = EpisodePlan(7, 1, '비밀 발견', ('단서 발견',), ('hero',), '', (), '다음 장면')
        self.scenes = (
            ScenePlan(7, 1, '도서관', ('hero',), '서류 찾기', '경비 순찰', '긴장'),
            ScenePlan(7, 2, '복도', ('hero',), '도주', '발각', '불안'),
            ScenePlan(7, 3, '집', ('hero',), '해독', '암호', '안도'),
        )
        self.facts = (
            ContextFact(self.project, 'novel_bible', 'core', '마법은 불가능'),
            ContextFact(self.project, 'character', 'hero-fact', '주인공은 탐정', character_ids=('hero',)),
        )
        self.context = select_episode_context(self.project, self.episode, self.facts)
        self.previews = tuple(generate_scene_draft(self.project, self.episode, scene,
                              self.context, MockSceneProvider()) for scene in self.scenes)

    def assemble(self, **overrides):
        return assemble_episode_draft(overrides.get('project', self.project),
                overrides.get('episode', self.episode), overrides.get('scenes', self.scenes),
                overrides.get('previews', self.previews),
                maximum_chars=overrides.get('maximum_chars', MAX_EPISODE_DRAFT_CHARS))

    def test_three_scenes_merged_in_order_and_exact_text(self):
        out = self.assemble()
        self.assertEqual(out.draft, '\n\n'.join(p.result.draft for p in self.previews))
        self.assertEqual(len(out.scenes), 3)
        self.assertEqual(tuple(x.scene_number for x in out.scenes), (1, 2, 3))
        for span, preview in zip(out.scenes, self.previews):
            self.assertEqual(out.draft[span.start:span.end], preview.result.draft)

    def test_origin_and_canon_preserved(self):
        out = self.assemble()
        self.assertEqual(out.canon_fact_ids, ('core',))
        self.assertEqual(out.provider, 'offline-mock-v1')
        self.assertEqual(out.origin, 'DETERMINISTIC_MOCK_NOT_AI')
        self.assertEqual(out.scenes[0].supporting_fact_ids, ('hero-fact',))

    def test_unapproved_non_persistent(self):
        out = self.assemble()
        self.assertEqual(out.status, 'DRAFT_REQUIRES_USER_APPROVAL')
        self.assertFalse(out.persisted)
        self.assertFalse(out.publication_approved)

    def test_full_draft_fingerprint(self):
        out = self.assemble()
        self.assertEqual(out.draft_sha256, sha256(out.draft.encode()).hexdigest())
        self.assertEqual(self.assemble(), out)

    def test_missing_scene_is_rejected(self):
        with self.assertRaises(EpisodeAssemblyError): self.assemble(previews=self.previews[:2])

    def test_duplicate_scene_is_rejected(self):
        with self.assertRaises(EpisodeAssemblyError): self.assemble(previews=(self.previews[0], self.previews[0], self.previews[2]))

    def test_out_of_order_scene_rejected(self):
        with self.assertRaises(EpisodeAssemblyError): self.assemble(previews=self.previews[::-1])

    def test_wrong_episode_rejected(self):
        with self.assertRaises(EpisodeAssemblyError): self.assemble(previews=(replace(self.previews[0], result=replace(self.previews[0].result, episode_number=8)), *self.previews[1:]))

    def test_wrong_project_rejected(self):
        with self.assertRaises(EpisodeAssemblyError): self.assemble(project='other-novel')

    def test_altered_text_detected_by_sha(self):
        altered = replace(self.previews[1], result=replace(self.previews[1].result, draft='변조 원고'))
        with self.assertRaises(EpisodeAssemblyError): self.assemble(previews=(self.previews[0], altered, self.previews[2]))

    def test_bad_prompt_hash_rejected(self):
        altered = replace(self.previews[1], prompt_sha256='notsha')
        with self.assertRaises(EpisodeAssemblyError): self.assemble(previews=(self.previews[0], altered, self.previews[2]))

    def test_mismatching_canon_rejected(self):
        altered = replace(self.previews[1], canon_fact_ids=('someone-elses-canon',))
        with self.assertRaises(EpisodeAssemblyError): self.assemble(previews=(self.previews[0], altered, self.previews[2]))

    def test_missing_canon_rejected(self):
        altered = replace(self.previews[1], canon_fact_ids=())
        with self.assertRaises(EpisodeAssemblyError): self.assemble(previews=(self.previews[0], altered, self.previews[2]))

    def test_mixed_provider_origin_rejected(self):
        altered = replace(self.previews[1], result=replace(self.previews[1].result, provider='local-executable-v1'), origin='LOCAL_EXECUTABLE_OUTPUT_NOT_VERIFIED_AS_AI')
        with self.assertRaises(EpisodeAssemblyError): self.assemble(previews=(self.previews[0], altered, self.previews[2]))

    def test_false_origin_rejected(self):
        altered = replace(self.previews[1], origin='LOCAL_EXECUTABLE_OUTPUT_NOT_VERIFIED_AS_AI')
        with self.assertRaises(EpisodeAssemblyError): self.assemble(previews=(self.previews[0], altered, self.previews[2]))

    def test_already_persisted_rejected(self):
        altered = replace(self.previews[0], persisted=True)
        with self.assertRaises(EpisodeAssemblyError): self.assemble(previews=(altered, *self.previews[1:]))

    def test_published_rejected(self):
        altered = replace(self.previews[0], publication_approved=True)
        with self.assertRaises(EpisodeAssemblyError): self.assemble(previews=(altered, *self.previews[1:]))

    def test_wrong_state_rejected(self):
        altered = replace(self.previews[0], result=replace(self.previews[0].result, status='FINAL'))
        with self.assertRaises(EpisodeAssemblyError): self.assemble(previews=(altered, *self.previews[1:]))

    def test_invalid_scene_plan_rejected(self):
        with self.assertRaises(EpisodeAssemblyError): self.assemble(scenes=(self.scenes[0], replace(self.scenes[1], scene_number=3), self.scenes[2]))

    def test_unfinished_scene_rejected(self):
        with self.assertRaises(EpisodeAssemblyError): self.assemble(scenes=(replace(self.scenes[0], goal=''), *self.scenes[1:]))

    def test_episode_status_rejected(self):
        with self.assertRaises(EpisodeAssemblyError): self.assemble(episode=replace(self.episode, status='PUBLISHED'))

    def test_bounded_total_length(self):
        with self.assertRaises(EpisodeAssemblyError): self.assemble(maximum_chars=15)
        with self.assertRaises(EpisodeAssemblyError): self.assemble(maximum_chars=True)
        with self.assertRaises(EpisodeAssemblyError): self.assemble(maximum_chars=MAX_EPISODE_DRAFT_CHARS + 1)
        self.assertEqual(self.assemble(maximum_chars=len(self.assemble().draft)).draft, self.assemble().draft)

    def test_reject_bool_and_garbage_indices(self):
        altered = replace(self.previews[0], result=replace(self.previews[0].result, scene_number=True))
        with self.assertRaises(EpisodeAssemblyError): self.assemble(previews=(altered, *self.previews[1:]))

    def test_reject_empty_or_nul_draft(self):
        for value in ('', ' \n', '\x00'):
            with self.subTest(value=repr(value)):
                changed = replace(self.previews[0], result=replace(self.previews[0].result, draft=value), draft_sha256=sha256(value.encode()).hexdigest())
                with self.assertRaises(EpisodeAssemblyError): self.assemble(previews=(changed, *self.previews[1:]))

    def test_one_scene_allowed(self):
        out = self.assemble(scenes=self.scenes[:1], previews=self.previews[:1])
        self.assertEqual(out.draft, self.previews[0].result.draft)
        self.assertEqual(out.scenes[0].start, 0)

    def test_no_io_and_no_network(self):
        with patch('builtins.open', side_effect=AssertionError('unexpected file access')):
            with patch.object(socket.socket, 'connect', side_effect=AssertionError('unexpected network')):
                self.assertEqual(len(self.assemble().scenes), 3)

    def test_errors_never_leak_manuscript_text(self):
        bad = replace(self.previews[0], result=replace(self.previews[0].result, draft='UNIQUE_MANUSCRIPT_SECRET'))
        with self.assertRaises(EpisodeAssemblyError) as result:
            self.assemble(previews=(bad, *self.previews[1:]))
        self.assertNotIn('UNIQUE_MANUSCRIPT_SECRET', str(result.exception))


if __name__ == '__main__':
    unittest.main()
