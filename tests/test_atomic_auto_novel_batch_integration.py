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
    def test_real_stored_250_episode_checkpoints_preserve_first_and_latest(self):
        from types import SimpleNamespace
        from ai_novel_factory.auto_novel_run import _continuity_context
        source = {n: SimpleNamespace(draft=f'{n}화 원본 사건 완료',
                                      final_text='', summary='잘못된 AI 요약')
                  for n in range(1, 250)}
        source[1] = SimpleNamespace(draft='1화 원고 속 첫 번째 열쇠',
                                    final_text='', summary='가짜 요약')
        context = _continuity_context('작가 설정의 핵심', source, 250)
        self.assertIn('1화 원고 속 첫 번째 열쇠', context)
        self.assertIn('225화 미검수 초고 저장 본문 마지막 사건', context)
        self.assertIn('중간 장기 사건 체크포인트', context)
        self.assertNotIn('1화 미확정 AI 요약', context)
        self.assertIn('작가 설정의 핵심', context)
        self.assertEqual(source[1].summary, '가짜 요약')

    def test_recent_reviewed_final_and_legacy_final_only_used_for_crosscheck(self):
        from types import SimpleNamespace
        from ai_novel_factory.auto_novel_run import (_continuity_context,
                                                      _cross_episode_sources)
        existing = {
            1: SimpleNamespace(draft='', final_text='검수본에서 문이 열렸다', summary=''),
            2: SimpleNamespace(draft='미검수 초안에서 문이 닫혔다',
                               final_text='검수본에서 문이 열렸고 발걸음이 이어졌다',
                               summary='낡은 요약'),
        }
        context = _continuity_context('작가 원칙', existing, 3)
        self.assertIn('검수본에서 문이 열렸다', context)
        self.assertIn('검수본에서 문이 열렸고 발걸음이 이어졌다', context)
        self.assertNotIn('미검수 초안에서 문이 닫혔다', context)
        text, missing, older = _cross_episode_sources(existing, 3)
        self.assertEqual(text, (existing[1].final_text, existing[2].final_text))
        self.assertEqual((missing, older), (0, 0))

    def test_auto_source_stamp_detects_rule_character_and_prior_episode_edits(self):
        from ai_novel_factory.auto_novel_run import _auto_author_source_stamp
        from types import SimpleNamespace
        from unittest.mock import patch
        class FakeCharacters:
            def __init__(self, path): self.path = path
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def list_characters(self, pid): return tuple(characters)
        class FakeEpisodes:
            def get_project(self, pid): return SimpleNamespace(title='검증용 작품')
            def list_rules(self, pid): return tuple(rules)
            def list_episodes(self, pid): return tuple(chapters)
        rules = [SimpleNamespace(key='genre', value='판타지', revision=1)]
        characters = [SimpleNamespace(character_id='abc',name='주인공', personality='신중함', goal='목표',speech_style='말투',secret='',revision=1)]
        chapters = [SimpleNamespace(episode=1, revision=1),
                    SimpleNamespace(episode=250, revision=1)]
        with patch('ai_novel_factory.auto_novel_run.CharacterStore', FakeCharacters):
            before = _auto_author_source_stamp(FakeEpisodes(), 'local.sqlite', 'book', 250)
            self.assertEqual(before, _auto_author_source_stamp(FakeEpisodes(), 'local.sqlite', 'book', 250))
            chapters[0].revision = 2
            self.assertNotEqual(before, _auto_author_source_stamp(FakeEpisodes(), 'local.sqlite', 'book', 250))
            chapters[0].revision = 1
            characters[0].personality = '적극적'
            self.assertNotEqual(before, _auto_author_source_stamp(FakeEpisodes(), 'local.sqlite', 'book', 250))
            characters[0].personality = '신중함'
            rules[0].revision = 2
            self.assertNotEqual(before, _auto_author_source_stamp(FakeEpisodes(), 'local.sqlite', 'book', 250))
            self.assertEqual(before[2], ((1, 1),))

    def test_auto_source_stamp_never_mutates_author_records(self):
        from ai_novel_factory.auto_novel_run import _auto_author_source_stamp
        from types import SimpleNamespace
        from unittest.mock import patch
        class FakeCharacters:
            def __init__(self, path): pass
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def list_characters(self, pid): return (character,)
        class FakeEpisodes:
            def get_project(self, pid): return SimpleNamespace(title='검증용 작품')
            def list_rules(self, pid): return (rule,)
            def list_episodes(self, pid): return (episode,)
        character = SimpleNamespace(character_id='abc',name='인물', personality='성격', goal='목표',speech_style='말투',secret='',revision=1)
        rule = SimpleNamespace(key='mood', value='차분함', revision=1)
        episode = SimpleNamespace(episode=1, revision=12)
        with patch('ai_novel_factory.auto_novel_run.CharacterStore', FakeCharacters):
            stamp = _auto_author_source_stamp(FakeEpisodes(), 'local.sqlite', 'book', 2)
        self.assertEqual(stamp[2], ((1, 12),))
        self.assertEqual((character.name, rule.value, episode.revision), ('인물', '차분함', 12))

    def test_auto_batch_rechecks_stop_and_snapshot_before_sqlite_write(self):
        from pathlib import Path
        source = Path(__file__).parents[1] / 'src/ai_novel_factory/auto_novel_run.py'
        code = source.read_text(encoding='utf-8')
        write = code.index('current = safe.create_unapproved_batch_episode(')
        stop = code.rfind('if should_stop is not None and should_stop():', 0, write)
        compare = code.rfind('started_source_state', 0, write)
        self.assertGreater(stop, 0)
        self.assertGreater(compare, stop)
        self.assertLess(compare, write)

    def test_long_episode_plot_preserves_early_clue_and_late_resolution(self):
        from ai_novel_factory.auto_novel_run import (
            _plot_endpoints, _native_scene_generation_goal,
            _scene_generation_context)
        original = '첫 장면의 복선은 푸른 열쇠다. ' + '중간 전개' * 2000 + ' 마지막 결말은 문을 잠근다.'
        before = original
        excerpt = _plot_endpoints(original, 1200)
        self.assertEqual(len(excerpt), 1200)
        self.assertIn('푸른 열쇠', excerpt)
        self.assertIn('문을 잠근다', excerpt)
        self.assertIn('중간 미확정 플롯 생략', excerpt)
        goal = _native_scene_generation_goal(250, 2, 3, original, 1667)
        self.assertTrue(goal.startswith('목표 분량 1667자'))
        self.assertIn('푸른 열쇠', goal)
        self.assertIn('문을 잠근다', goal)
        context = _scene_generation_context('작가 저장 원칙', original, '앞 장면 원고')
        self.assertLessEqual(len(context), 12000)
        self.assertIn('푸른 열쇠', context)
        self.assertIn('문을 잠근다', context)
        self.assertIn('앞 장면 원고', context)
        self.assertEqual(original, before)

    def test_revision_goal_preserves_scene_allocation_on_retry(self):
        from ai_novel_factory.auto_novel_run import _native_scene_revision_goal
        self.assertTrue(_native_scene_revision_goal(1667).startswith('목표 분량 1667자'))
        self.assertTrue(_native_scene_revision_goal(1666).startswith('목표 분량 1666자'))
        with self.assertRaises(ValueError):
            _native_scene_revision_goal(10001)
        self.assertIn('_native_scene_revision_goal(per_scene)',
                      BATCH.read_text(encoding='utf-8'))

    def test_existing_reviewed_final_only_is_not_misclassified_as_empty(self):
        from types import SimpleNamespace
        from ai_novel_factory.auto_novel_run import _existing_episode_needs_review
        reviewed = SimpleNamespace(draft='', final_text='작가가 검수한 원고')
        self.assertFalse(_existing_episode_needs_review(
            reviewed, scenes=(object(),), checks=(object(),)))
        self.assertTrue(_existing_episode_needs_review(
            reviewed, scenes=(), checks=(object(),)))
        self.assertTrue(_existing_episode_needs_review(
            reviewed, scenes=(object(),), checks=()))
        empty = SimpleNamespace(draft='', final_text='')
        self.assertTrue(_existing_episode_needs_review(
            empty, scenes=(object(),), checks=(object(),)))
        self.assertEqual(reviewed.final_text, '작가가 검수한 원고')

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

    def test_real_native_scene_text_is_preserved_across_sqlite_restart(self):
        # Synthetic stored texts test SQL provenance only. No mocked Qwen
        # acceptance, no fake literary PASS, no publication, no real files.
        scenes = (
            (1, '사서는 첫 번째 서랍에서 날짜가 지워진 종이를 발견했다.'),
            (2, '조사자는 두 번째 서랍을 열어 봉인된 장부를 확인했다.'),
        )
        before = self.db.get_project(self.pid).revision
        episode = self.db.create_unapproved_batch_episode(
            self.pid, 1, plot='미승인 플롯', draft='\n\n'.join(s for _, s in scenes),
            summary='미승인 요약', scenes=scenes,
            checks=(('continuity', 'NOT_RUN', '실제 품질 미검증'),))
        self.assertEqual(episode.revision, 4)
        with EpisodeStore(self.path) as other:
            loaded = other.snapshot(self.pid, 1)
            self.assertEqual([s.text for s in loaded.scenes],
                             [s for _, s in scenes])
            self.assertEqual(loaded.episode.draft,
                             '\n\n'.join(s for _, s in scenes))
            self.assertEqual(loaded.episode.final_text, '')
            self.assertEqual(other.get_project(self.pid).revision, before + 1)

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

    def test_saved_character_traits_reach_native_prompt_without_database_changes(self):
        from ai_novel_factory.database.characters import CharacterStore
        from ai_novel_factory.auto_novel_run import (
            _character_bible_context, _continuity_context,
            _scene_generation_context)
        with CharacterStore(self.path) as characters:
            characters.create_character(
                self.pid, name='선우', personality='성급하지만 약속을 지킴',
                goal='사라진 형을 찾기', speech_style='짧고 명확한 존댓말',
                secret='오래된 편지의 비밀')
            before = characters.list_characters(self.pid)
        notes = _character_bible_context(before)
        self.assertIn('성급하지만 약속을 지킴', notes)
        self.assertIn('사라진 형을 찾기', notes)
        self.assertIn('짧고 명확한 존댓말', notes)
        self.assertIn('오래된 편지의 비밀', notes)
        long_rules = '작가 설정 원본 ' * 1300
        first = _scene_generation_context(notes + '\n' + long_rules,
                                          '첫 회차 가상 플롯', '')
        next_context = _continuity_context(notes + '\n' + long_rules, {}, 2)
        later = _scene_generation_context(next_context, '두 번째 플롯', '')
        for actual_prompt in (first, later):
            self.assertLessEqual(len(actual_prompt), 12000)
            self.assertIn('성급하지만 약속을 지킴', actual_prompt)
            self.assertIn('짧고 명확한 존댓말', actual_prompt)
            self.assertIn('오래된 편지의 비밀', actual_prompt)
        with CharacterStore(self.path) as characters:
            self.assertEqual(characters.list_characters(self.pid), before)

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
        # Real saved events, rather than unreviewed AI summaries, must
        # survive the long-Bible context budget.
        self.assertIn('첫 사건의 실제 장면을 저장했다.', ctx)
        self.assertIn('주인공이 새로운 문서를 찾았다.', ctx)
        self.assertIn('그는 사건의 날짜가 뒤바뀌었다', ctx)
        self.assertNotIn('첫 회차 계획', ctx)
        self.assertIn('날짜가 뒤바뀌었다', ctx)
        self.assertIn('사용자가 저장한 Novel Bible', ctx)
        self.assertTrue(ctx.endswith(long_bible))
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



class BatchWiringSourceContract(unittest.TestCase):
    def test_saved_ai_outline_preview_is_not_duplicated_as_author_canon(self):
        batch = BATCH.read_text(encoding='utf-8')
        self.assertIn("{'author', 'ai_story_outline_preview'}", batch)
        self.assertIn('character_bible = _character_bible_context(characters)', batch)


    def test_cross_episode_reuse_is_recorded_as_scope_only_no_auto_approval(self):
        batch = BATCH.read_text(encoding='utf-8')
        self.assertIn('cross = screen_cross_episode_reuse(', batch)
        self.assertIn('_cross_episode_sources(existing, n)', batch)
        self.assertIn('first_checked = max(1, episode - 250)', batch)
        self.assertIn('older_prior_unexamined={older_unexamined}', batch)
        self.assertIn('missing_prior_episodes={missing_prior}', batch)
        self.assertNotIn('range(max(1, n - 3), n)', batch)
        self.assertIn("'cross_episode_sentence_reuse',", batch)
        self.assertIn('scope_only=true;literary_approved=false', batch)
        self.assertIn('requires_review = True', batch)

    def test_1000_episode_window_never_claims_older_750_chapters_checked(self):
        from types import SimpleNamespace
        from ai_novel_factory.auto_novel_run import (
            _cross_episode_sources, AutoNovelRunError)
        from ai_novel_factory.episode_crosscheck import screen_cross_episode_reuse
        # These are synthetic records for scope/limits ONLY, not model prose.
        existing = {
            n: SimpleNamespace(draft=f'가상의 기록 보존을 위한 {n}화 독립 사건이다.')
            for n in range(1, 1000)
        }
        previous, missing, older = _cross_episode_sources(existing, 1000)
        self.assertEqual(len(previous), 250)
        self.assertEqual(missing, 0)
        self.assertEqual(older, 749)
        self.assertEqual(previous[0], existing[750].draft)
        self.assertEqual(previous[-1], existing[999].draft)
        screen = screen_cross_episode_reuse(
            '조사자는 새로 들어온 문서의 내용을 살폈다.', previous)
        self.assertEqual(screen.prior_episodes_examined, 250)
        self.assertFalse(screen.literary_approved)
        del existing[800]
        previous, missing, older = _cross_episode_sources(existing, 1000)
        self.assertEqual(len(previous), 249)
        self.assertEqual(missing, 1)
        self.assertEqual(older, 749)
        for bad in (0, 1001, True):
            with self.subTest(bad=bad), self.assertRaises(AutoNovelRunError):
                _cross_episode_sources(existing, bad)

    def test_scene_context_preserves_actual_previous_scene_and_author_rules(self):
        from ai_novel_factory.auto_novel_run import _scene_generation_context
        from importlib.util import spec_from_file_location, module_from_spec
        author_bible = '사용자 설정의 절대 규칙. ' * 1000
        previous = '앞 장면에서 사서가 붉은 열쇠를 서랍에 넣었다.'
        context = ('최근 회차의 미확정 집필 기록 (아래 사용자의 Novel Bible 설정이 우선):\n'
                   + '50화 저장된 사건. ' * 180
                   + '\n사용자가 저장한 Novel Bible 설정 (충돌 시 우선):\n'
                   + author_bible)
        actual = _scene_generation_context(
            context, '51화에서 서랍을 열어 열쇠를 찾는다.', previous)
        self.assertLessEqual(len(actual), 12000)
        self.assertIn(previous, actual)
        self.assertIn('51화에서 서랍을 열어', actual)
        # Long histories must retain the final saved chapter, not only old arcs.
        long_history = ('오래된 미확정 회차. ' * 900
                        + '50화의 실제 마지막 결과: 봉인이 풀렸다.\n')
        newest_context = _scene_generation_context(
            long_history + '\n사용자가 저장한 Novel Bible 설정 (충돌 시 우선):\n'
            + author_bible, '51화 플롯', previous)
        self.assertIn('50화의 실제 마지막 결과: 봉인이 풀렸다.', newest_context)
        self.assertIn('사용자 설정의 절대 규칙', newest_context)
        self.assertIn('사용자 설정의 절대 규칙', actual)
        spec = spec_from_file_location(
            'native_scene_window', ROOT / 'packaging/windows/local_model_bridge.py')
        bridge = module_from_spec(spec)
        spec.loader.exec_module(bridge)
        _, native_prompt = bridge.build_story_prompts(
            actual, '51화 집필', '서랍이 잠겼다', '기록관', '', ['사서'])
        self.assertIn(previous, native_prompt)
        self.assertIn('사용자 설정의 절대 규칙', native_prompt)
        self.assertIn('51화에서 서랍을 열어', native_prompt)

    def test_revision_context_exposes_rejected_scene_before_native_truncation(self):
        from ai_novel_factory.auto_novel_run import (
            _scene_generation_context, _scene_revision_context)
        canon = ('사용자가 저장한 Novel Bible 설정 (충돌 시 우선):\n'
                 + '중요한 설정을 반드시 유지한다. ' * 600)
        original = _scene_generation_context(
            canon, '이번 회차에서 봉인된 장부를 연다.',
            '사서는 문을 닫고 봉인된 장부를 꺼냈다.')
        revision = _scene_revision_context(
            original, '수정할 장면의 실제 첫 초고. 원인이 빠졌다.' * 75)
        self.assertLessEqual(len(revision), 12000)
        self.assertIn('수정할 장면의 실제 첫 초고', revision)
        self.assertIn('사서는 문을 닫고', revision)
        self.assertIn('이번 회차에서 봉인된 장부', revision)
        self.assertIn('중요한 설정을 반드시 유지', revision)

    def test_real_episode_budget_is_allocated_without_dropping_characters(self):
        from ai_novel_factory.auto_novel_run import (
            _scene_char_targets, AutoNovelRunError)
        for total, count, expected in (
            (5000, 3, (1667, 1667, 1666)),
            (5000, 20, (250,) * 20),
            (5000, 1, (5000,)),
            (50000, 5, (10000,) * 5),
            (101, 2, (51, 50)),
            (250, 5, (50,) * 5),
        ):
            with self.subTest(total=total, count=count):
                actual = _scene_char_targets(total, count)
                self.assertEqual(actual, expected)
                self.assertEqual(sum(actual), total)
                self.assertTrue(all(x >= 50 for x in actual))
        for total, count in ((50, 3), (999, 20), (100, 0),
                             (5000, 21), (5000, True),
                             (50000, 1), (20001, 2)):
            with self.subTest(invalid=(total, count)):
                with self.assertRaises(AutoNovelRunError):
                    _scene_char_targets(total, count)

    def test_real_scene_target_wins_over_numbers_in_model_generated_outline(self):
        from ai_novel_factory.auto_novel_run import _native_scene_generation_goal
        from ai_novel_factory.local_models import effective_scene_target
        outline = '5000자 목표를 토론한 뒤 10000자 연대기를 찾아라.'
        goal = _native_scene_generation_goal(7, 2, 3, outline, 1667)
        self.assertTrue(goal.startswith('목표 분량 1667자'))
        self.assertIn(outline, goal)
        self.assertEqual(effective_scene_target(goal, 1667), 1667)
        for short_target in (50, 500, 999):
            with self.subTest(allocated_scene_chars=short_target):
                short_goal = _native_scene_generation_goal(
                    7, 2, 3, outline, short_target)
                self.assertEqual(effective_scene_target(
                    short_goal, short_target), short_target)
        for bad in (0, 10001, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                _native_scene_generation_goal(7, 2, 3, outline, bad)

    def test_real_model_length_qc_counts_nonspace_only(self):
        batch = BATCH.read_text(encoding='utf-8')
        self.assertIn('enough = screen.nonspace_chars >= target_chars', batch)
        self.assertNotIn('enough = len(full_draft.strip()) >= target_chars', batch)
        self.assertIn('per_scene = scene_targets[scene_index]', batch)
        self.assertIn('actual_nonspace={screen.nonspace_chars}', batch)
        self.assertIn('_scene_generation_context(', batch)
        self.assertIn('not has_foreign_script_corruption(revised)', batch)
        self.assertIn('_scene_revision_context(scene_context, scene)', batch)
        # Stored temporary SQLite episode checks preserve the actual status
        # without author-editing, literary approval or model emulation.
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'only-fixture.sqlite'
            with EpisodeStore(path) as db:
                pid = db.create_project('임시 회귀 전용 소설').project_id
                episode = db.create_unapproved_batch_episode(
                    pid, 1, plot='임시', draft='한글 글자 띄어쓰기',
                    summary='미확정', scenes=((1, '한글 글자 띄어쓰기'),),
                    checks=(('length', 'WARN',
                             'actual_nonspace=8;target_chars=5000'),))
                self.assertEqual(episode.final_text, '')
            # Reopen through an INDEPENDENT SQLite connection, as a user
            # would after closing the native Windows program.
            with EpisodeStore(path) as independent:
                record = independent.list_checks(pid, 1)[0]
                self.assertEqual(record.outcome, 'WARN')
                self.assertIn('target_chars=5000', record.note)
                self.assertEqual(independent.get_episode(pid, 1).final_text, '')

    def test_run_uses_atomic_insert_and_explicit_real_korean_screening(self):
        batch = BATCH.read_text(encoding='utf-8')
        self.assertIn('safe.create_unapproved_batch_episode(', batch)
        self.assertIn('for slot, scene_text in zip(slots, drafts)', batch)
        self.assertNotIn("f'{outline[:600]}\\n장면 목표: {n}화", batch)
        self.assertIn("('korean_format', 'PASS' if screen.format_gate_pass", batch)
        self.assertIn("('reference_similarity', 'continuity',", batch)
        self.assertNotIn('safe.create_episode(project_id, n, plot=outline)', batch)

    def test_gui_uses_explicit_qwen_timeout_and_cannot_switch_project(self):
        gui = GUI.read_text(encoding='utf-8')
        workflow = WORKFLOW.read_text(encoding='utf-8')
        self.assertIn("Path(executable).name.casefold() == 'anf_local_model.exe'", gui)
        self.assertIn("timeout_seconds=(", gui)
        self.assertIn('self.auto_panel.request_stop()', workflow)
        self.assertIn('self.target_chars.value() < 50 * self.scenes.value()', gui)
        self.assertIn('self.target_chars.value() > 10_000 * self.scenes.value()', gui)
        self.assertIn("if self.auto_panel.is_running():", workflow)
        self.assertIn('str(session.project_id) == self.worker.project_id', gui)
        self.assertIn('self._approved_project', gui)
        self.assertIn('self.consent.toggled.connect(self._bind_approval)', gui)



    def test_project_switch_rejects_live_inference_and_revokes_model_consent(self):
        workflow = WORKFLOW.read_text(encoding='utf-8')
        self.assertIn("self.fields['db'].textChanged.connect(", workflow)
        self.assertIn('self._revoke_project_approvals()', workflow)
        self.assertIn('self.auto_panel.consent.setChecked(False)', workflow)
        self.assertIn('if self.is_generating():', workflow)
        self.assertIn("for key in ('plot', 'draft', 'final_text'):", workflow)

    def test_studio_project_creation_uses_same_inference_and_consent_guards(self):
        source = (ROOT / 'src/ai_novel_factory/desktop/project_studio.py').read_text(
            encoding='utf-8')
        body = source.split('    def _create_project(self):', 1)[1].split(
            '    def _start_first_episode(self):', 1)[0]
        self.assertIn('self.workflow.auto_panel.is_running()', body)
        self.assertIn('self.workflow.is_generating()', body)
        self.assertLess(body.index('self.workflow._revoke_project_approvals()'),
                        body.index('self.workflow.session.create_project('))

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
