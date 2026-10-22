"""Data protection regressions for manually created local projects.

No PySide6, no real user documents and no internet. This checks exclusive
creation, pre-existing files and cleanup after failed initialization.
"""
import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from ai_novel_factory.desktop.authoring_session import AuthoringError, AuthoringSession


class AuthoringCreationSafetyTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'synthetic-novel.sqlite'
        self.session = AuthoringSession()
        self.addCleanup(self.session.close)

    def create(self, **kwargs):
        return self.session.create_project(
            str(self.path), kwargs.get('title', '합성 작품'),
            kwargs.get('author', '실험 작가'),
            kwargs.get('premise', '가상의 마을에 존재하는 원본 설정'))

    def test_saved_episode_character_goal_reaches_native_scene_payload(self):
        # This exercises the real authoring session and an isolated temporary
        # SQLite DB; it never invokes an external model or accesses user files.
        import sys
        from ai_novel_factory.local_models import _message
        self.session.create_project(
            str(self.path), '가상 원고', '테스트 작가', '가상의 고문서 사건',
            extra_rules={'characters_per_episode': '5000'})
        self.session.create_episode(1, '사라진 기록을 찾는다')
        self.session.add_scene('서가에서 첫 번째 흔적을 발견한다')
        def prepared():
            request, _, _ = self.session.prepare_generation(
                sys.executable, ('--gguf', 'synthetic.gguf'), True,
                '기록관이 낡은 종이를 읽는다', '사서가 문을 막는다',
                '도서관 서가', ('기록관', '사서'))
            return request
        one = prepared()
        self.assertEqual(one.target_chars, 5000)
        self.assertEqual(_message(one)['request']['target_chars'], 5000)
        self.assertIn('회차당 목표 글자 수: 5000', one.novel_bible)
        self.assertNotIn('characters_per_episode:', one.novel_bible)
        self.session.add_scene('뒷문으로 나가는 다른 장면')
        two = prepared()
        self.assertEqual(two.target_chars, 2500)
        self.assertEqual(_message(two)['request']['target_chars'], 2500)
        # A per-scene partial does NOT satisfy the entire episode target.
        self.assertLess(two.target_chars, int(
            self.session.rule('characters_per_episode')))

    def _accept_synthetic_draft(self, text):
        # Exercise the real non-persisting result acceptance path. Never
        # bypass provenance by setting pending_draft directly in an export test.
        import sys
        from ai_novel_factory.local_models import SceneDraftResult
        request, provider, identity = self.session.prepare_generation(
            sys.executable, (), True, '가상 집필 목표', '가상 갈등', '가상 장소', ('가상 인물',))
        result = SceneDraftResult(request.project_id, request.episode_number,
                                  request.scene_number, text, provider.provider_id)
        self.session.accept_generation(request, result, identity)
        self.session.save_draft(text)

    def test_manual_generation_uses_saved_character_facts_and_rejects_stale_character_edits(self):
        import sys
        from ai_novel_factory.database.characters import CharacterStore
        from ai_novel_factory.local_models import SceneDraftResult
        self.create()
        self.session.create_episode(1, '인물의 비밀이 드러난다')
        self.session.add_scene('첫 사건이 시작된다')
        with CharacterStore(self.path) as characters:
            person = characters.create_character(
                self.session.project_id, name='가온',
                personality='낯선 이를 쉽게 믿지 않는다',
                goal='실종된 가족을 찾는다',
                speech_style='짧은 존댓말', secret='열쇠를 숨겼다')
        request, provider, identity = self.session.prepare_generation(
            sys.executable, (), True, '문을 연다', '추격자가 막는다',
            '가상의 지하실', ('가온',))
        self.assertIn('낯선 이를 쉽게 믿지 않는다', request.novel_bible)
        self.assertIn('실종된 가족을 찾는다', request.novel_bible)
        self.assertIn('짧은 존댓말', request.novel_bible)
        self.assertIn('열쇠를 숨겼다', request.novel_bible)
        with CharacterStore(self.path) as characters:
            characters.update_character(
                self.session.project_id, person.character_id,
                expected_revision=person.revision,
                personality='이제 사람을 믿는다')
        draft = SceneDraftResult(
            request.project_id, request.episode_number,
            request.scene_number, 'AI가 작성했다고 가정한 합성 문장', provider.provider_id)
        with self.assertRaisesRegex(AuthoringError, '인물 설정이 변경'):
            self.session.accept_generation(request, draft, identity)
        self.assertIsNone(self.session.pending_draft)

    def test_manual_three_scene_budget_has_no_ceil_rounding_overrun(self):
        import sys
        self.session.create_project(
            str(self.path), '합성 분량 작품', '가상 작가', '가상의 사건',
            extra_rules={'characters_per_episode': '5000'})
        self.session.create_episode(1, '세 장면으로 이어지는 가상의 플롯')
        for text in ('첫 장면', '둘째 장면', '셋째 장면'):
            self.session.add_scene(text)
        targets = []
        for scene in self.session.store.list_scenes(self.session.project_id, 1):
            self.session.scene_id = scene.scene_id
            request, _, _ = self.session.prepare_generation(
                sys.executable, (), True, '이어서 집필한다', '갈등', '가상 공간',
                ('가상 인물',))
            targets.append(request.target_chars)
        self.assertEqual(targets, [1667, 1667, 1666])
        self.assertEqual(sum(targets), 5000)

    def test_manual_scene_quota_after_deleting_first_scene(self):
        import sys
        self.session.create_project(
            str(self.path), '장면 삭제 검증', '작가', '가상 세계관',
            extra_rules={'characters_per_episode': '5001'})
        self.session.create_episode(1, '세 장면을 계획한다')
        for value in ('첫 장면', '둘째 장면', '셋째 장면'):
            self.session.add_scene(value)
        scenes = self.session.store.list_scenes(self.session.project_id, 1)
        self.session.store.delete_scene(
            self.session.project_id, 1, scenes[0].scene_id,
            expected_revision=self.session.episode().revision)
        remaining = self.session.store.list_scenes(self.session.project_id, 1)
        self.assertEqual([item.position for item in remaining], [2, 3])
        targets = []
        for item in remaining:
            self.session.scene_id = item.scene_id
            request, _, _ = self.session.prepare_generation(
                sys.executable, (), True, '다음 장면', '갈등', '가상 공간', ('인물',))
            targets.append(request.target_chars)
        self.assertEqual(targets, [2501, 2500])
        self.assertEqual(sum(targets), 5001)

    def test_manual_previous_chapter_memory_and_stale_prior_revision(self):
        import sys
        from ai_novel_factory.local_models import SceneDraftResult
        self.create()
        self.session.create_episode(1, '전편의 원본 플롯')
        self.session.add_scene('이전 사건')
        old = self.session.episode()
        self.session.store.update_episode(
            self.session.project_id, 1, expected_revision=old.revision,
            draft='가온이 비밀 서류를 마지막에 발견했다.',
            summary='첫 회차에서 서류를 찾았다.')
        self.session.create_episode(2, '서류의 진실을 추적한다')
        self.session.add_scene('서류를 읽는다')
        request, provider, identity = self.session.prepare_generation(
            sys.executable, (), True, '다음 사건을 전개', '갈등', '서재', ('가온',))
        self.assertIn('첫 회차에서 서류를 찾았다', request.style_bible)
        self.assertIn('가온이 비밀 서류를 마지막에 발견했다', request.style_bible)
        self.assertIn('서류의 진실을 추적한다', request.style_bible)
        old = self.session.store.get_episode(self.session.project_id, 1)
        self.session.store.update_episode(
            self.session.project_id, 1, expected_revision=old.revision,
            summary='첫 회차 내용을 수정했다.')
        result = SceneDraftResult(
            request.project_id, request.episode_number, request.scene_number,
            '가상 결과', provider.provider_id)
        with self.assertRaisesRegex(AuthoringError, '이전 회차가 변경'):
            self.session.accept_generation(request, result, identity)
        self.assertIsNone(self.session.pending_draft)

    def test_manual_rejects_result_from_different_scene(self):
        import sys
        from ai_novel_factory.local_models import SceneDraftResult
        self.create()
        self.session.create_episode(1, '첫 회차')
        self.session.add_scene('현재 장면')
        request, provider, identity = self.session.prepare_generation(
            sys.executable, (), True, '목표', '갈등', '장소', ('인물',))
        wrong = SceneDraftResult(
            request.project_id, request.episode_number, request.scene_number + 1,
            '잘못 연결된 합성 초고', provider.provider_id)
        with self.assertRaisesRegex(AuthoringError, '장면이 일치하지 않습니다'):
            self.session.accept_generation(request, wrong, identity)
        self.assertIsNone(self.session.pending_draft)

    def test_manual_rejects_zero_or_unsupported_scene_budget_early(self):
        import sys
        self.session.create_project(
            str(self.path), '장면 목표 검증', '작가', '원본 설정',
            extra_rules={'characters_per_episode': '2'})
        self.session.create_episode(1, '플롯')
        for value in ('첫 장면', '둘째 장면', '셋째 장면'):
            self.session.add_scene(value)
        with self.assertRaisesRegex(AuthoringError, '장면 수가'):
            self.session.prepare_generation(
                sys.executable, (), True, '목표', '갈등', '장소', ('인물',))

    def test_manual_long_active_scene_keeps_saved_previous_chapter_events(self):
        import sys
        self.create()
        self.session.create_episode(1, '앞선 회차의 실제 사건')
        self.session.add_scene('이전 회차 장면')
        old = self.session.episode()
        self.session.store.update_episode(
            self.session.project_id, 1, expected_revision=old.revision,
            draft='주인공이 붉은 봉투를 발견했다.', summary='붉은 봉투 발견')
        self.session.create_episode(2, '현재 플롯 시작 ' + '긴 줄거리 ' * 900)
        self.session.add_scene('현재 장면 앞부분 ' + '긴 장면 ' * 900 + '장면 끝에서 문이 열린다')
        request, _, _ = self.session.prepare_generation(
            sys.executable, (), True, '사건을 이어 쓴다', '추적자', '도서관', ('주인공',))
        self.assertLessEqual(len(request.style_bible), 5000)
        self.assertIn('현재 플롯 시작', request.style_bible)
        self.assertIn('장면 끝에서 문이 열린다', request.style_bible)
        self.assertIn('붉은 봉투 발견', request.style_bible)
        self.assertIn('주인공이 붉은 봉투를 발견했다', request.style_bible)

    def test_reviewed_export_invalid_price_leaves_no_blocking_directory(self):
        self.create()
        self.session.create_episode(1, '검수 회차')
        self.session.add_scene('검수 장면')
        self._accept_synthetic_draft('가상 합성 초고')
        self.session.save_final_text('가상 검수 완료 원고', human_reviewed=True,
                                     incomplete_qc_acknowledged=True)
        folder = Path(self.temp.name) / 'export-validation'
        folder.mkdir()
        with self.assertRaises(ValueError):
            self.session.export_final(folder, '잘못된 가격')
        self.assertFalse((folder / 'reviewed_final').exists())
        # A valid retry must still work without manual cleanup.
        txt, epub = self.session.export_final(folder, '0')
        self.assertTrue(txt.is_file())
        self.assertTrue(epub.is_file())

    def test_reviewed_sqlite_reopen_epub_roundtrip_without_overwriting(self):
        from ai_novel_factory.epub3 import verify_epub
        self.create()
        self.session.create_episode(1, '첫 회차')
        self.session.add_scene('첫 장면')
        self._accept_synthetic_draft('첫 회차 가상 초고')
        self.session.save_final_text('첫 회차 검수 원고', human_reviewed=True,
                                     incomplete_qc_acknowledged=True)
        self.session.create_episode(2, '둘째 회차')
        self.session.add_scene('둘째 장면')
        self._accept_synthetic_draft('둘째 회차 가상 초고')
        self.session.save_final_text('둘째 회차 검수 원고', human_reviewed=True,
                                     incomplete_qc_acknowledged=True)
        pid = self.session.project_id
        self.session.close()
        reopened = AuthoringSession()
        self.addCleanup(reopened.close)
        reopened.open_project(str(self.path))
        self.assertEqual(reopened.project_id, pid)
        saved = reopened.store.list_episodes(pid)
        self.assertEqual([ep.final_text for ep in saved],
                         ['첫 회차 검수 원고', '둘째 회차 검수 원고'])
        folder = Path(self.temp.name) / 'epub-roundtrip'
        folder.mkdir()
        txt, epub = reopened.export_final(folder, '0')
        self.assertEqual(verify_epub(epub, expected_chapters=2).chapters, 2)
        text = txt.read_text(encoding='utf-8')
        self.assertIn('첫 회차 검수 원고', text)
        self.assertIn('둘째 회차 검수 원고', text)
        with self.assertRaises(AuthoringError):
            reopened.export_final(folder, '0')
        self.assertEqual(txt.read_text(encoding='utf-8'), text)

    def test_manual_generation_rejects_wrong_provider_status_persisted_or_empty_draft(self):
        import sys
        from dataclasses import replace
        from ai_novel_factory.local_models import SceneDraftResult
        self.create()
        self.session.create_episode(1, '실제 검수 전 회차')
        self.session.add_scene('임시 장면')
        request, provider, identity = self.session.prepare_generation(
            sys.executable, (), True, '목표', '갈등', '장소', ('인물',))
        valid = SceneDraftResult(request.project_id, request.episode_number,
                                 request.scene_number, '검수 전 임시 초고', provider.provider_id)
        invalid = (
            replace(valid, provider='offline-mock-v1'),
            replace(valid, status='ALREADY_APPROVED'),
            replace(valid, persisted=True),
            replace(valid, draft='   '),
        )
        for candidate in invalid:
            with self.subTest(candidate=candidate):
                with self.assertRaises(AuthoringError):
                    self.session.accept_generation(request, candidate, identity)
                self.assertIsNone(self.session.pending_draft)
        self.assertEqual(self.session.accept_generation(request, valid, identity),
                         '검수 전 임시 초고')
        self.assertEqual(self.session.pending_draft, '검수 전 임시 초고')

    def test_manual_same_scene_late_async_result_cannot_override_newer_draft(self):
        import sys
        from ai_novel_factory.local_models import SceneDraftResult
        self.create()
        self.session.create_episode(1, '하나의 장면을 두 번 요청한다')
        self.session.add_scene('동일한 장면')
        first, provider, first_identity = self.session.prepare_generation(
            sys.executable, (), True, '첫 번째 목표', '갈등', '방', ('인물',))
        second, _, second_identity = self.session.prepare_generation(
            sys.executable, (), True, '두 번째 목표', '갈등', '방', ('인물',))
        self.assertNotEqual(first_identity[-1], second_identity[-1])
        newest = SceneDraftResult(second.project_id, second.episode_number,
                                  second.scene_number, '두 번째 최신 초고', provider.provider_id)
        self.session.accept_generation(second, newest, second_identity)
        stale = SceneDraftResult(first.project_id, first.episode_number,
                                 first.scene_number, '첫 번째 오래된 초고', provider.provider_id)
        with self.assertRaisesRegex(AuthoringError, '더 새로운 집필 요청'):
            self.session.accept_generation(first, stale, first_identity)
        self.assertEqual(self.session.pending_draft, '두 번째 최신 초고')

    def test_manual_250_episode_checkpoint_uses_actual_text_without_summary(self):
        from types import SimpleNamespace
        from ai_novel_factory.desktop.authoring_session import _manual_prior_context
        earlier = tuple(SimpleNamespace(episode=n, summary='',
                                        draft=f'{n}화 미검수 사건 원문', final_text='')
                        for n in range(1, 251))
        notes = _manual_prior_context(earlier)
        self.assertIn('225화 미검수 초고 마지막 사건 원문', notes)
        self.assertIn('250화 미검수 초고 저장 본문 마지막 사건', notes)
        self.assertNotIn('225화 과거 미확정 요약', notes)

    def test_manual_long_bible_preserves_head_tail_and_saved_characters(self):
        from ai_novel_factory.desktop.authoring_session import _manual_canon_context
        canon = '작가 첫 규칙 ' + '세계관 원본 ' * 1900 + ' 작가 마지막 규칙'
        chars = '사용자 저장 인물 비밀: 서랍 속 열쇠'
        prompt = _manual_canon_context(chars, canon)
        self.assertLessEqual(len(prompt), 12000)
        self.assertIn(chars, prompt)
        self.assertIn('작가 첫 규칙', prompt)
        self.assertIn('작가 마지막 규칙', prompt)
        self.assertIn('일부 작가 설정이 생략됨', prompt)


    def test_manual_close_and_reopen_rejects_same_scene_inflight_result(self):
        import sys
        from ai_novel_factory.local_models import SceneDraftResult
        self.create()
        self.session.create_episode(1, '한 회차')
        self.session.add_scene('같은 장면')
        request, provider, identity = self.session.prepare_generation(
            sys.executable, (), True, '목표', '갈등', '방', ('인물',))
        self.session.close()
        self.session.open_project(str(self.path))
        old_result = SceneDraftResult(
            request.project_id, request.episode_number, request.scene_number,
            '재열기 이전의 늦은 초고', provider.provider_id)
        with self.assertRaisesRegex(AuthoringError, '더 새로운 집필 요청'):
            self.session.accept_generation(request, old_result, identity)
        self.assertIsNone(self.session.pending_draft)

    def test_manual_episode_switch_roundtrip_invalidates_async_result(self):
        import sys
        from ai_novel_factory.local_models import SceneDraftResult
        self.create()
        self.session.create_episode(1, '첫 회차')
        self.session.add_scene('첫 장면')
        request, provider, identity = self.session.prepare_generation(
            sys.executable, (), True, '목표', '갈등', '방', ('인물',))
        self.session.create_episode(2, '둘째 회차')
        self.session.add_scene('둘째 장면')
        self.session.select_episode(1)
        old_result = SceneDraftResult(
            request.project_id, request.episode_number, request.scene_number,
            '이전 요청의 늦은 초고', provider.provider_id)
        with self.assertRaisesRegex(AuthoringError, '더 새로운 집필 요청'):
            self.session.accept_generation(request, old_result, identity)

    def test_manual_canon_reports_character_omission_and_preserves_author_tail(self):
        from ai_novel_factory.desktop.authoring_session import _manual_canon_context
        character_notes = '저장 인물 비밀 ' * 900
        author_notes = ('작가 최초 규칙 ' + '중간 원본 ' * 1700
                        + '작가 마지막 규칙\n회차당 목표 글자 수: 5000')
        context = _manual_canon_context(character_notes, author_notes)
        self.assertLessEqual(len(context), 12000)
        self.assertIn('일부 저장 인물 설정이 생략됨', context)
        self.assertIn('일부 작가 설정이 생략됨', context)
        self.assertIn('작가 최초 규칙', context)
        self.assertIn('작가 마지막 규칙', context)
        self.assertIn('회차당 목표 글자 수: 5000', context)

    def test_manual_recent_draft_is_never_labeled_reviewed(self):
        from types import SimpleNamespace
        from ai_novel_factory.desktop.authoring_session import _manual_prior_context
        earlier = tuple(SimpleNamespace(episode=n, summary='',
                                        draft=f'{n}화 미검수 원고 사건', final_text='')
                        for n in range(1, 5))
        notes = _manual_prior_context(earlier)
        self.assertIn('4화 미검수 초고 저장 본문 마지막 사건', notes)
        self.assertNotIn('4화 검수본 저장 본문 마지막 사건', notes)

    def test_manual_selected_ninth_character_reaches_local_prompt(self):
        import sys
        from ai_novel_factory.database.characters import CharacterStore
        self.create()
        self.session.create_episode(1, '아홉 번째 인물이 핵심이다')
        self.session.add_scene('아홉 번째 인물의 행동')
        with CharacterStore(self.path) as characters:
            for number in range(1, 10):
                characters.create_character(
                    self.session.project_id, name=f'인물{number}',
                    personality=f'{number}번 성격', goal=f'{number}번 목표',
                    speech_style=f'{number}번 말투',
                    secret=f'{number}번 비밀')
        request, _, _ = self.session.prepare_generation(
            sys.executable, (), True, '사건', '갈등', '방', ('인물9',))
        self.assertIn('9번 성격', request.novel_bible)
        self.assertIn('9번 비밀', request.novel_bible)

    def test_manual_250_chapters_keep_first_and_recent_checkpoint(self):
        from types import SimpleNamespace
        from ai_novel_factory.desktop.authoring_session import _manual_prior_context
        earlier = tuple(SimpleNamespace(
            episode=n, summary='', draft=f'{n}화의 미검수 실제 사건', final_text='')
            for n in range(1, 251))
        notes = _manual_prior_context(earlier)
        self.assertIn('1화 미검수 초고 마지막 사건 원문', notes)
        self.assertIn('225화 미검수 초고 마지막 사건 원문', notes)
        self.assertIn('250화 미검수 초고 저장 본문 마지막 사건', notes)
        self.assertIn('중간 체크포인트 생략', notes)

    def test_manual_long_plot_keeps_opening_and_final_event(self):
        from ai_novel_factory.desktop.authoring_session import _manual_scene_context
        plot = '첫 번째 복선: 열쇠' + '중간 사건 ' * 900 + '마지막 사건: 배신'
        context = _manual_scene_context(plot, '장면의 마지막: 추적 시작',
                                        '이전 회차 저장 사건: 서류 발견')
        self.assertLessEqual(len(context), 5000)
        self.assertIn('첫 번째 복선: 열쇠', context)
        self.assertIn('마지막 사건: 배신', context)
        self.assertIn('장면의 마지막: 추적 시작', context)
        self.assertIn('이전 회차 저장 사건: 서류 발견', context)

    def test_manual_scene_budget_preserves_first_and_latest_saved_events(self):
        from ai_novel_factory.desktop.authoring_session import _manual_scene_context
        prior = ('1화 검수본 첫 사건: 오래된 서약' + '중간 기록 ' * 280
                 + '250화 검수본 최신 사건: 비밀의 문이 열린다')
        plot = '처음 복선: 봉인' + '현재 플롯 ' * 450 + '결말: 봉인 해제'
        scene = '현재 장면 ' * 500 + '마지막 대사: 돌아오겠다'
        actual = _manual_scene_context(plot, scene, prior)
        self.assertLessEqual(len(actual), 5000)
        for marker in ('처음 복선: 봉인', '결말: 봉인 해제',
                       '마지막 대사: 돌아오겠다', '1화 검수본 첫 사건',
                       '250화 검수본 최신 사건'):
            self.assertIn(marker, actual)
        self.assertIn('이전 회차 중간 생략', actual)

    def test_manual_accepted_draft_rejects_external_character_change_before_save(self):
        import sys
        from ai_novel_factory.database.characters import CharacterStore
        from ai_novel_factory.local_models import SceneDraftResult
        self.create()
        self.session.create_episode(1, '원본 플롯')
        self.session.add_scene('원본 장면')
        with CharacterStore(self.path) as chars:
            character = chars.create_character(
                self.session.project_id, name='나래', personality='신중함',
                goal='실종된 친구 찾기', speech_style='존댓말', secret='편지')
        request, provider, identity = self.session.prepare_generation(
            sys.executable, (), True, '목표', '갈등', '장소', ('나래',))
        result = SceneDraftResult(request.project_id, request.episode_number,
                                  request.scene_number, '승인 전 생성 초고', provider.provider_id)
        self.session.accept_generation(request, result, identity)
        with CharacterStore(self.path) as chars:
            chars.update_character(self.session.project_id, character.character_id,
                                   expected_revision=character.revision,
                                   personality='더 신중해짐')
        with self.assertRaisesRegex(AuthoringError, '인물 설정이 변경'):
            self.session.save_draft('사용자가 다듬은 생성 초고')
        self.assertEqual(self.session.episode().draft, '')
        self.assertIsNone(self.session.pending_draft)

    def test_manual_accepted_draft_rejects_prior_chapter_change_before_save(self):
        import sys
        from ai_novel_factory.local_models import SceneDraftResult
        self.create()
        self.session.create_episode(1, '이전 사건')
        self.session.add_scene('이전 장면')
        self.session.create_episode(2, '현재 사건')
        self.session.add_scene('현재 장면')
        request, provider, identity = self.session.prepare_generation(
            sys.executable, (), True, '목표', '갈등', '장소', ('인물',))
        result = SceneDraftResult(request.project_id, request.episode_number,
                                  request.scene_number, '초고', provider.provider_id)
        self.session.accept_generation(request, result, identity)
        previous = self.session.store.get_episode(self.session.project_id, 1)
        self.session.store.update_episode(self.session.project_id, 1,
                                          expected_revision=previous.revision,
                                          plot='이전 사건의 실제 변경')
        with self.assertRaisesRegex(AuthoringError, '이전 회차가 변경'):
            self.session.save_draft('초고를 편집한 내용')
        self.assertEqual(self.session.episode().draft, '')

    def test_manual_accepted_draft_can_save_author_edited_text_without_overwriting(self):
        import sys
        from ai_novel_factory.local_models import SceneDraftResult
        self.create()
        self.session.create_episode(1, '현재 회차')
        self.session.add_scene('현재 장면')
        request, provider, identity = self.session.prepare_generation(
            sys.executable, (), True, '목표', '갈등', '장소', ('인물',))
        result = SceneDraftResult(request.project_id, request.episode_number,
                                  request.scene_number, '생성 원문', provider.provider_id)
        self.session.accept_generation(request, result, identity)
        self.session.save_draft('사용자가 직접 수정한 원고')
        self.assertEqual(self.session.episode().draft, '사용자가 직접 수정한 원고')
        self.assertIsNone(self.session.pending_draft)


    def test_manual_eight_long_selected_characters_keep_all_facts(self):
        from ai_novel_factory.desktop.authoring_session import _manual_canon_context
        details = []
        for i in range(8):
            details.append(f'인물 선택{i} | 성격: 성격{i}' + '가' * 160
                           + f' | 목표: 목표{i}' + '나' * 160
                           + f' | 말투: 말투{i}' + '다' * 150
                           + f' | 비밀 설정: 비밀{i}' + '라' * 130)
        original = '저장 인물 설정:\n' + '\n'.join(details)
        author = '작가 시작 복선' + '마' * 15000 + '작가 마지막 결말'
        actual = _manual_canon_context(original, author)
        self.assertLessEqual(len(actual), 12000)
        for i in range(8):
            for fragment in (f'선택{i}', f'성격{i}', f'목표{i}', f'말투{i}', f'비밀{i}'):
                self.assertIn(fragment, actual)
        self.assertIn('작가 시작 복선', actual)
        self.assertIn('작가 마지막 결말', actual)
        self.assertIn('일부 저장 인물 설정이 생략됨', actual)
        self.assertTrue(original.endswith('라' * 130))

    def test_manual_pending_without_verified_provenance_never_saves(self):
        self.create()
        self.session.create_episode(1, '합성 사건')
        self.session.add_scene('합성 장면')
        self.session.pending_draft = '검증 출처가 없는 문자열'
        self.session._pending_generation_provenance = None
        with self.assertRaises(AuthoringError):
            self.session.save_draft('출처 없는 문자열')
        self.assertEqual(self.session.episode().draft, '')
        self.assertIsNone(self.session.pending_draft)

    def test_manual_nonstring_pending_save_is_rejected_without_sqlite_write(self):
        self.create()
        self.session.create_episode(1, '합성 사건')
        self.session.add_scene('합성 장면')
        self.session.pending_draft = '임시 모델 초고'
        with self.assertRaises(AuthoringError):
            self.session.save_draft(None)
        self.assertEqual(self.session.episode().draft, '')

    def test_manual_checkpoint_prefers_saved_text_to_stale_summary(self):
        from types import SimpleNamespace
        from ai_novel_factory.desktop.authoring_session import _manual_prior_context
        earlier = tuple(SimpleNamespace(
            episode=n, summary='미확정 오답 사건',
            draft=f'{n}화 실제 미검수 사건', final_text='')
            for n in range(1, 251))
        notes = _manual_prior_context(earlier)
        self.assertIn('1화 미검수 초고 마지막 사건 원문', notes)
        self.assertIn('225화 미검수 초고 마지막 사건 원문', notes)
        self.assertIn('1화 실제 미검수 사건', notes)
        self.assertNotIn('1화 과거 미확정 요약', notes)

    def test_reviewed_epub_cover_is_verified_without_touching_source(self):
        from ai_novel_factory.epub3 import verify_epub
        self.create()
        self.session.create_episode(1, '검수 완료 회차')
        self.session.add_scene('표지가 있는 장면')
        self._accept_synthetic_draft('표지가 있는 작품의 합성 초고')
        self.session.save_final_text('표지와 함께 보존할 검수 원고',
                                     human_reviewed=True,
                                     incomplete_qc_acknowledged=True)
        cover = Path(__file__).resolve().parents[1] / 'docs/stage91_demo/cover.jpg'
        before = cover.read_bytes()
        folder = Path(self.temp.name) / 'covered-export'
        folder.mkdir()
        txt, epub = self.session.export_final(folder, '0', cover_path=cover)
        report = verify_epub(epub, expected_chapters=1, expect_cover=True)
        self.assertTrue(report.contains_cover)
        self.assertIn('표지와 함께 보존할 검수 원고', txt.read_text(encoding='utf-8'))
        self.assertEqual(cover.read_bytes(), before)
    def test_draft_epub_cover_must_not_disappear_without_notice(self):
        from ai_novel_factory.epub3 import EpubError, create_epub as real_create_epub
        self.create()
        self.session.create_episode(1, '표지가 있는 미검수 초고')
        self.session.add_scene('첫 장면')
        self._accept_synthetic_draft('검수되지 않은 가상 원고')
        cover = Path(__file__).resolve().parents[1] / 'docs/stage91_demo/cover.jpg'
        before = cover.read_bytes()
        output = Path(self.temp.name) / 'draft-epub'
        output.mkdir()

        # Simulate an EPUB writer silently dropping the selected cover.
        # The real validator must catch this and delete only new output,
        # never the author's saved database or original cover.
        def broken_cover_writer(metadata, chapters, target, *, cover_path=None):
            return real_create_epub(metadata, chapters, target, cover_path=None)

        with patch('ai_novel_factory.desktop.authoring_session.create_epub',
                   side_effect=broken_cover_writer):
            with self.assertRaises(EpubError):
                self.session.export(output, '0', cover_path=cover)
        self.assertFalse((output / 'book.epub').exists())
        self.assertFalse((output / 'draft.txt').exists())
        self.assertEqual(cover.read_bytes(), before)

    def test_saved_episode_and_manual_scene_override_remain_distinct(self):
        from ai_novel_factory.local_models import effective_scene_target
        self.session.create_project(
            str(self.path), '가상 소설', '작가', '가상 도서관',
            extra_rules={'characters_per_episode': '5000'})
        self.session.create_episode(1, '낡은 편지를 발견한다')
        self.session.add_scene('문이 닫힌다')
        self.session.add_scene('숨겨진 기록을 찾는다')
        import sys
        request, _, _ = self.session.prepare_generation(
            sys.executable, ('--gguf', 'public-test.gguf'), True,
            '이 장면은 6000자로 집필', '증거가 사라진다',
            '서가', ('사서',))
        self.assertEqual(request.target_chars, 2500)
        self.assertEqual(
            effective_scene_target(request.scene_goal, request.target_chars), 6000)
        self.assertEqual(self.session.rule('characters_per_episode'), '5000')


    def test_new_file_is_private_and_can_be_reopened(self):
        pid = self.create()
        self.assertTrue(self.path.is_file())
        self.assertEqual(self.session.project_id, pid)
        self.assertEqual(self.session.rule('author'), '실험 작가')
        self.session.close()
        self.session.open_project(str(self.path))
        self.assertEqual(self.session.project_id, pid)
        self.assertEqual(self.session.rule('premise'), '가상의 마을에 존재하는 원본 설정')

    def test_optional_author_is_marked_undecided(self):
        self.create(author='')
        self.assertEqual(self.session.rule('author'), '미정')

    def test_canon_is_required_before_file_creation(self):
        with self.assertRaises(AuthoringError):
            self.create(premise='')
        self.assertFalse(self.path.exists())

    def test_existing_file_is_never_modified(self):
        original = b'USER DATA, NEVER TOUCH OR OVERWRITE'
        self.path.write_bytes(original)
        with self.assertRaises(AuthoringError):
            self.create()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertIsNone(self.session.store)

    def test_race_created_file_is_never_deleted(self):
        sentinel = b'OTHER PROCESS FILE, DO NOT DELETE'
        real_open = os.open

        def racing_open(path, flags, mode=0o777):
            if str(path) == str(self.path):
                self.path.write_bytes(sentinel)
                raise FileExistsError(str(path))
            return real_open(path, flags, mode)

        with patch('ai_novel_factory.desktop.authoring_session.os.open',
                   side_effect=racing_open):
            with self.assertRaises(AuthoringError):
                self.create()
        self.assertEqual(self.path.read_bytes(), sentinel)

    def test_failed_create_deletes_only_newly_reserved_file(self):
        with self.assertRaises(ValueError):
            self.create(title='  ')
        self.assertFalse(self.path.exists())

    def test_failed_existing_project_open_preserves_current_work(self):
        old_pid = self.create()
        old_path = self.session.path
        self.session.create_episode(1, '기존 작업의 회차')
        other = Path(self.temp.name) / 'synthetic-other.sqlite'
        from ai_novel_factory.database.episodes import EpisodeStore
        with EpisodeStore(other) as storage:
            storage.create_project('외부 가상 작품')
        with patch('ai_novel_factory.desktop.authoring_session.EpisodeStore.list_episodes',
                   side_effect=ValueError('synthetic malformed chapter list')):
            with self.assertRaises(ValueError):
                self.session.open_project(str(other))
        self.assertEqual(self.session.project_id, old_pid)
        self.assertEqual(self.session.path, old_path)
        self.assertEqual(self.session.episode_number, 1)
        self.assertEqual(self.session.episode().plot, '기존 작업의 회차')

    def test_invalid_import_metadata_or_checks_preserves_live_session(self):
        # A malformed but structurally valid external novel cannot replace
        # the current project merely because its episode list was readable.
        pid = self.create()
        self.session.create_episode(1, '계속 보존할 기존 회차')
        self.session.pending_draft = '화면에 아직 저장하지 않은 가상 원고'
        original_store = self.session.store
        old_path = self.session.path
        from ai_novel_factory.database.episodes import EpisodeStore
        other = Path(self.temp.name) / 'synthetic-corrupted-external.sqlite'
        with EpisodeStore(other) as database:
            imported_id = database.create_project('합성 외부 작품').project_id
            database.create_episode(imported_id, 1, plot='합성 외부 회차')
        for broken_read in ('get_project', 'list_rules', 'list_checks'):
            with self.subTest(read=broken_read):
                with patch.object(EpisodeStore, broken_read,
                                  side_effect=ValueError('synthetic corrupt import')):
                    with self.assertRaises(ValueError):
                        self.session.open_project(str(other))
                self.assertIs(self.session.store, original_store)
                self.assertEqual(self.session.project_id, pid)
                self.assertEqual(self.session.path, old_path)
                self.assertEqual(self.session.episode_number, 1)
                self.assertEqual(self.session.pending_draft,
                                 '화면에 아직 저장하지 않은 가상 원고')
                self.assertEqual(self.session.episode().plot, '계속 보존할 기존 회차')

    def test_failed_scene_load_keeps_active_episode(self):
        self.create()
        self.session.create_episode(1, '')
        self.session.create_episode(2, '')
        self.assertEqual(self.session.episode_number, 2)
        from unittest.mock import patch
        with patch.object(self.session.store, 'list_scenes',
                          side_effect=ValueError('synthetic invalid scene')):
            with self.assertRaises(ValueError):
                self.session.select_episode(1)
        self.assertEqual(self.session.episode_number, 2)

    def test_repeated_project_creation_preserves_existing_novel(self):
        pid = self.create()
        self.session.close()
        with self.assertRaises(AuthoringError):
            self.create(title='새 작품 이름')
        self.session.open_project(str(self.path))
        self.assertEqual(self.session.project_id, pid)
