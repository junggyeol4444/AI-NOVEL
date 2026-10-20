"""Cross-feature database + GUI batch contracts; not real AI acceptance.

Uses only temporary SQLite, no model, external account, user files or publish.
Actual Windows native Qwen and GGUF tests remain separate release gates.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from ai_novel_factory.database.episodes import EpisodeError, EpisodeStore

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'src/ai_novel_factory/database/episodes.py'
BATCH = ROOT / 'src/ai_novel_factory/auto_novel_run.py'
GUI = ROOT / 'src/ai_novel_factory/desktop/auto_batch_panel.py'
WORKFLOW = ROOT / 'src/ai_novel_factory/desktop/authoring_workflow.py'


class AtomicBatchEpisodeRegression(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'only-temporary.sqlite'
        self.db = EpisodeStore(self.path)
        self.addCleanup(self.db.close)
        self.pid = self.db.create_project('임시 원고 안전 검사').project_id

    @staticmethod
    def kwargs(number=1):
        # Data is a synthetic transport fixture and not presented as AI prose.
        return dict(plot='플롯 전송 검사',
                    draft='검사용 임시 텍스트\n저장과 복구를 확인한다.',
                    summary='미승인 요약',
                    scenes=((1, '장면 슬롯 A'), (2, '장면 슬롯 B')),
                    checks=(('length', 'WARN', '분량 미달'),
                            ('korean_format', 'WARN', '형식 검사 미달'),
                            ('continuity', 'NOT_RUN', '전수 검사 미실시')))

    def test_insert_is_atomic_and_survives_independent_sqlite_reopen(self):
        project_before = self.db.get_project(self.pid).revision
        saved = self.db.create_unapproved_batch_episode(
            self.pid, 1, **self.kwargs())
        self.assertEqual(saved.revision, 4)
        self.assertEqual(self.db.get_project(self.pid).revision, project_before + 1)
        with EpisodeStore(self.path) as independent:
            loaded = independent.snapshot(self.pid, 1)
            self.assertEqual(loaded.episode.draft, self.kwargs()['draft'])
            self.assertEqual(loaded.episode.summary, '미승인 요약')
            self.assertEqual(loaded.episode.final_text, '')
            self.assertEqual([s.position for s in loaded.scenes], [1, 2])
            self.assertEqual(len(loaded.checks), 3)
            self.assertTrue(all(c.content_revision == loaded.episode.revision
                                for c in loaded.checks))

    def test_duplicate_existing_episode_cannot_overwrite_user_content(self):
        first = self.db.create_unapproved_batch_episode(
            self.pid, 1, **self.kwargs())
        before = self.db.get_project(self.pid).revision
        with self.assertRaises(EpisodeError):
            self.db.create_unapproved_batch_episode(
                self.pid, 1, **{**self.kwargs(), 'draft': '다른 데이터'})
        self.assertEqual(self.db.get_episode(self.pid, 1).draft, first.draft)
        self.assertEqual(self.db.get_project(self.pid).revision, before)
        self.assertEqual(len(self.db.list_checks(self.pid, 1)), 3)

    def test_failure_during_qc_insert_rolls_back_episode_and_all_scenes(self):
        before = self.db.get_project(self.pid).revision
        self.db._db.execute("""CREATE TRIGGER reject_test_check
            BEFORE INSERT ON bible_episode_checks
            BEGIN SELECT RAISE(ABORT, 'ephemeral rollback probe'); END""")
        self.db._db.commit()
        with self.assertRaises(EpisodeError):
            self.db.create_unapproved_batch_episode(
                self.pid, 2, **self.kwargs())
        self.assertEqual(self.db.list_episodes(self.pid), ())
        self.assertEqual(self.db.get_project(self.pid).revision, before)
        with EpisodeStore(self.path) as independent:
            self.assertEqual(independent.list_episodes(self.pid), ())

    def test_invalid_scenes_and_unapproved_status_are_rejected_before_writes(self):
        for kwargs in ({'scenes': ((1, 'A'), (1, 'B'))},
                       {'checks': (('literary', 'CERTIFIED', '허위 결과'),)},
                       {'draft': ''}):
            with self.subTest(kwargs=kwargs), self.assertRaises(EpisodeError):
                self.db.create_unapproved_batch_episode(
                    self.pid, 3, **{**self.kwargs(), **kwargs})
        self.assertEqual(self.db.list_episodes(self.pid), ())

    def test_250_episode_storage_contract_does_not_certify_ai(self):
        # Real SQLite transactions only; these are NOT model-written novels.
        for number in range(1, 251):
            self.db.create_unapproved_batch_episode(
                self.pid, number, **self.kwargs())
        with EpisodeStore(self.path) as independent:
            self.assertEqual(len(independent.list_episodes(self.pid)), 250)
            self.assertTrue(all(not e.final_text
                                for e in independent.list_episodes(self.pid)))
            self.assertEqual(len(independent.list_checks(self.pid, 250)), 3)


class BatchWiringSourceContract(unittest.TestCase):
    def test_recent_true_saved_chapter_context_survives_long_novel_bible(self):
        from ai_novel_factory.auto_novel_run import _continuity_context
        # Only disposable authoring DB and synthetic contents; no AI was run.
        examples = [
            (1, '첫 회차 계획', '첫 사건의 실제 장면을 저장했다.'),
            (25, '25화 반전 계획', '주인공이 새로운 문서를 찾았다.'),
            (49, '49화 흔적', '복도의 벽이 무너지는 소리가 났다.'),
            (50, '50화 기록', '그는 사건의 날짜가 뒤바뀌었다는 사실을 발견했다.'),
        ]
        for number, summary, draft in examples:
            self.db.create_unapproved_batch_episode(
                self.pid, number, plot=summary, draft=draft,
                summary=summary,
                scenes=((1, '계속 사건'),),
                checks=(('continuity', 'NOT_RUN', '진짜 작가의 검수 대기'),))
        original = {e.episode: e for e in self.db.list_episodes(self.pid)}
        long_bible = '사용자 원본 세계관 ' * 1400
        ctx = _continuity_context(long_bible, original, 51)
        self.assertIn('첫 회차 계획', ctx)
        self.assertIn('25화 반전 계획', ctx)
        self.assertIn('50화 기록', ctx)
        self.assertIn('날짜가 뒤바뀌었다', ctx)
        self.assertIn('사용자가 저장한 Novel Bible', ctx)
        self.assertTrue(ctx.endswith(long_bible[:len(ctx)-ctx.index('사용자가 저장한 Novel Bible 설정 (충돌 시 우선):\\n')-len('사용자가 저장한 Novel Bible 설정 (충돌 시 우선):\\n')]))
        from ai_novel_factory.local_models import SceneDraftRequest
        from importlib.util import spec_from_file_location, module_from_spec
        # The actual bridge packs only 12k characters of its scene canon.
        spec = spec_from_file_location('bridge_for_continuity',
                ROOT / 'packaging/windows/local_model_bridge.py')
        bridge = module_from_spec(spec)
        spec.loader.exec_module(bridge)
        _, prompt = bridge.build_story_prompts(
            ctx, '51화 사건', '새 갈등', '도서관', '', ['사서'])
        self.assertIn('날짜가 뒤바뀌었다', prompt)
        self.assertEqual(self.db.get_episode(self.pid, 50).draft,
                         examples[-1][2])
        self.assertEqual(self.db.get_episode(self.pid, 50).final_text, '')

    def test_run_uses_atomic_insert_and_explicit_real_korean_screening(self):
        batch = BATCH.read_text(encoding='utf-8')
        self.assertIn('safe.create_unapproved_batch_episode(', batch)
        self.assertIn("('korean_format', 'PASS' if screen.format_gate_pass", batch)
        self.assertIn("('reference_similarity', 'continuity',", batch)
        self.assertNotIn('safe.create_episode(project_id, n, plot=outline)', batch)

    def test_gui_uses_explicit_qwen_timeout_and_cannot_switch_project(self):
        gui = GUI.read_text(encoding='utf-8')
        workflow = WORKFLOW.read_text(encoding='utf-8')
        self.assertIn("Path(executable).name.casefold() == 'anf_local_model.exe'", gui)
        self.assertIn("timeout_seconds=(", gui)
        self.assertIn('self.auto_panel.request_stop()', workflow)
        self.assertIn("if self.auto_panel.is_running():", workflow)
        self.assertIn('str(session.project_id) == self.worker.project_id', gui)



    def test_real_batch_passes_explicit_scene_allocation_to_native_wire_request(self):
        from ai_novel_factory.local_models import (
            SceneDraftRequest, _message, effective_scene_target)
        request = SceneDraftRequest(
            'a' * 32, 30, 3, '가상의 서고 이야기',
            '장면 플롯이 이어진다', '기록을 잃는다', '책장 사이',
            ('조사자',), target_chars=625)
        self.assertEqual(_message(request)['request']['target_chars'], 625)
        self.assertEqual(effective_scene_target(
            request.scene_goal, request.target_chars), 625)
        batch = BATCH.read_text(encoding='utf-8')
        self.assertIn('target_chars=allocated_scene_chars', batch)
        self.assertIn('allocated_scene_chars=per_scene', batch)

    def test_short_scene_requires_korean_quality_gate_before_revision(self):
        batch = BATCH.read_text(encoding='utf-8')
        self.assertIn('scene_screen = screen_korean_draft(', batch)
        self.assertIn('if (not scene_screen.format_gate_pass', batch)
        self.assertIn('revised_screen = screen_korean_draft(', batch)
        self.assertIn('revised_repeat = check_repetition(', batch)
        self.assertIn('if better_format or better_partial:', batch)
        # A brief 300-character output must not be accepted as a
        # complete 1600-character scene merely because it exceeds 120.
        from ai_novel_factory.korean_draft_quality import screen_korean_draft
        screened = screen_korean_draft('조사자는 기록을 살폈다. ' * 15,
                                       target_chars=1600)
        self.assertFalse(screened.format_gate_pass)

    def test_batch_worker_does_not_reveal_private_path_on_system_errors(self):
        gui = GUI.read_text(encoding='utf-8')
        self.assertIn('except (AutoNovelRunError, LocalModelError)', gui)
        self.assertIn('except (OSError, ValueError):', gui)
        self.assertNotIn("except (ValueError, OSError) as exc:", gui)

if __name__ == '__main__':
    unittest.main()
