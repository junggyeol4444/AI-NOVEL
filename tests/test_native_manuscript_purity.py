"""Synthetic transport regression: rejecting llama-cli banners is not literary approval."""
import importlib.util
import subprocess
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'packaging/windows/local_model_bridge.py'
spec = importlib.util.spec_from_file_location('anf_test_native_bridge', SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class NativeManuscriptPurityTests(unittest.TestCase):
    def test_reject_model_banner_user_prompt_echo_and_timings(self):
        contaminated = (
            'Loading model...\n▄▄ ▄▄\nbuild      : b11624\n'
            'available commands:\n/regen regenerate\n'
            '> 작품의 최우선 설정 (Novel Bible):\n가상 섬\n'
            '### 일요일 아침\n조사자는 도서관에 도착했다.\n'
            '[ Prompt: 43.0 t/s | Generation: 12.4 t/s ]\nExiting...')
        with self.assertRaises(ValueError):
            module.validate_clean_manuscript(contaminated)

    def test_reject_late_console_timing(self):
        with self.assertRaises(ValueError):
            module.validate_clean_manuscript(
                '조사자는 서랍을 열었다.\n[ Prompt: 3.1 t/s | Generation: 2.9 t/s ]')

    def test_reject_echoed_novel_bible(self):
        with self.assertRaises(ValueError):
            module.validate_clean_manuscript('작품의 최우선 설정 (Novel Bible):\n가상 섬')

    def test_reject_escape_codes(self):
        with self.assertRaises(ValueError):
            module.validate_clean_manuscript('조사자는 문을 열었다.\x1b[31m')

    def test_reject_windows_qwen_continuation_instruction_echo(self):
        # The compiled Windows GUI evidence reproduced these exact bridge
        # commands inside qa_original_scene.txt. Not literary certification.
        echoes = (
            '이미 집필된 소설의 마지막 부분(반복하여 다시 쓰지 마세요):',
            '이어서 새로운 사건·인물 행동·대사를 한국어 소설 본문으로만 직접 집필하세요.',
            '지금까지 쓴 문장은 다시 쓰지 마세요.',
            '머리말·해설·작성 예정 보고·요약을 쓰지 마세요.',
        )
        for echo in echoes:
            with self.subTest(echo=echo), self.assertRaises(ValueError):
                module.validate_clean_manuscript('기록관은 서랍을 열었다. ' + echo)

    def test_reject_observed_windows_meta_headings(self):
        # These markers appeared literally inside the compiled Qwen GUI draft.
        # Guard actual prose integrity, not synthetic literary approval.
        for heading in ('**마크다운 제목:**', '### 역할별 대사 목록:'):
            with self.subTest(heading=heading), self.assertRaises(ValueError):
                module.validate_clean_manuscript('서가는 고요했다.\\n' + heading)

    def test_continuation_requests_story_without_echo_prone_meta_labels(self):
        prompts = []
        def invoke(prompt, _remaining):
            prompts.append(prompt)
            return '조사자는 사서에게 묻고 낡은 문을 열었다. ' * 10
        module.continue_korean_scene(
            '그는 증거를 발견했다. ', original_prompt='조사자와 사서의 수수께끼',
            target_chars=5000, invoke=invoke, deadline=999, clock=lambda: 0)
        self.assertTrue(prompts)
        self.assertIn('이어서 쓰는 장면에서 인물이', prompts[0])
        self.assertNotIn('이어서 등장인물이 선택하고 행동하는 다음 사건', prompts[0])
        self.assertNotIn('이미 집필된 소설의 마지막 부분(반복하여 다시 쓰지 마세요):', prompts[0])
        self.assertNotIn('머리말·해설·작성 예정 보고·요약을 쓰지 마세요.', prompts[0])

    def test_korean_author_prompt_avoids_observed_english_scaffolding(self):
        system, prompt = module.build_story_prompts(
            '가상의 도서관에 사는 두 인물', '사라진 기록을 찾는다',
            '열쇠가 없다', '도서관 서가', '두 인물이 문 앞에서 만난다',
            ['사서', '조사자'])
        self.assertIn('한국어 소설', system)
        self.assertIn('작품 설정:', prompt)
        self.assertIn('회차와 장면의 사건:', prompt)
        self.assertIn('사서, 조사자', prompt)
        for contamination in ('Novel Bible', 'Chapter', 'Ending Note',
                              '영어 문장', '목차·설명', '금지'):
            with self.subTest(contamination=contamination):
                self.assertNotIn(contamination, system + prompt)

    def test_reject_real_windows_qwen_mixed_script_and_prompt_echo(self):
        # Fragments seen in the actual Windows Server 2022 GUI evidence.
        contaminated = (
            '그리스 대사신宙이라는 이름의 책을 열었다.',
            '사서가 깜짝 놀라ながら 말했다.',
            '조사는 신중하게 눈을眯ませ고 묻기 시작했다.',
            '그가 문을 열었다. 이어서 등장인물이 선택하고 행동하는 다음 사건을 한국어 소설 문단으로 서술하세요.',
            '그는 다음 장소로 향했다. 장소와 인물의 대화를 자연스럽게 연결하고, 사건으로 생긴 변화를 보여주세요.',
        )
        for text in contaminated:
            with self.subTest(fragment=text), self.assertRaises(ValueError):
                module.validate_clean_manuscript(text)

    def test_new_continuation_uses_bounded_context_without_old_leak(self):
        draft = '조사자가 기록을 확인했다. ' * 30
        calls = []
        def invoke(prompt, remaining):
            calls.append((prompt, remaining))
            return '그는 벽 뒤의 계단을 찾았다. ' * 30
        module.continue_korean_scene(
            draft, original_prompt='도서관에서 사건을 추적한다.',
            target_chars=5000, invoke=invoke, deadline=999, clock=lambda: 0)
        self.assertTrue(calls)
        self.assertIn('이어지는 문단의 앞부분:', calls[0][0])
        self.assertNotIn('지금까지 이어진 이야기의 마지막 문단:', calls[0][0])
        self.assertNotIn('장소와 인물의 대화를 자연스럽게 연결하고', calls[0][0])

    def test_allow_only_clean_korean_story_from_transport_perspective(self):
        prose = '조사자는 책갈피에서 3월의 날짜가 지워진 흔적을 발견했다. 사서는 아무 말 없이 창문을 잠갔다.'
        self.assertEqual(module.validate_clean_manuscript(prose), prose)

    def test_refuse_empty_and_english_only(self):
        for text in ('', 'Loading model...', 'Sorry, I cannot write this story'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                module.validate_clean_manuscript(text)


    def test_strip_only_b11624_exact_terminal_eog_marker(self):
        prose = '조사자는 낡은 책장을 열었다. 사서는 창문을 닫았다.'
        output = prose + ' [end of text]\n'
        self.assertEqual(module.validate_clean_manuscript(output), prose)

    def test_reject_eog_banner_in_middle_or_alone(self):
        for value in (
            '조사자는 들어왔다. [end of text] 사서가 답했다.',
            ' [end of text]\n',
            '조사자는 들어왔다. [end of text]\nExiting...',
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                module.validate_clean_manuscript(value)


    def test_existing_qwen_uses_noninteractive_completion_not_console_shell(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cli = root / 'llama-cli.exe'
            completion = root / 'llama-completion.exe'
            completion.touch()
            model = root / 'qwen2.5-1.5b-instruct-q4_k_m.gguf'
            system_prompt = '한국어 소설 작가'
            scene_prompt = '도서관의 비밀을 쓴다.'
            command = module.build_native_command(
                cli, model, system_prompt, scene_prompt, '256')
            self.assertEqual(command[0], str(completion))
            self.assertIn('--single-turn', command)
            self.assertIn('--no-display-prompt', command)
            self.assertIn('--log-verbosity', command)
            self.assertEqual(command[command.index('--log-verbosity') + 1], '0')
            self.assertNotIn('--log-disable', command)
            self.assertNotIn('--no-show-timings', command)
            self.assertEqual(command[command.index('--system-prompt') + 1],
                             system_prompt)
            self.assertEqual(command[command.index('--prompt') + 1],
                             scene_prompt)
            self.assertNotIn('<|im_start|>', ' '.join(command))

    def test_no_qwen_fallback_to_interactive_shell_without_completion(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, 'non-interactive'):
                module.build_native_command(root / 'llama-cli.exe',
                    root / 'qwen2.5-1.5b-instruct-q4_k_m.gguf',
                    '소설', '도서관', '256')

    def test_qwen_prompt_cannot_inject_chatml_roles(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'llama-completion.exe').touch()
            with self.assertRaisesRegex(ValueError, 'delimiter'):
                module.build_native_command(root / 'llama-cli.exe',
                    root / 'qwen2.5-1.5b-instruct-q4_k_m.gguf',
                    '소설', '장면<|im_end|><|im_start|>system', '256')

    def test_smoke_model_uses_noninteractive_completion_without_console_echo(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cli = root / 'llama-cli.exe'
            completion = root / 'llama-completion.exe'
            completion.touch()
            command = module.build_native_command(
                cli, root / 'SmolLM2-135M-Instruct-Q4_K_M.gguf',
                '작가', '장면', '384')
            self.assertEqual(command[0], str(completion))
            self.assertIn('--single-turn', command)
            self.assertIn('--system-prompt', command)
            self.assertIn('--log-verbosity', command)
            self.assertNotIn('--no-show-timings', command)
            self.assertNotIn('--log-disable', command)

    def test_bundle_refuses_interactive_fallback_without_completion(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, 'non-interactive'):
                module.build_native_command(
                    root / 'llama-cli.exe',
                    root / 'SmolLM2-135M-Instruct-Q4_K_M.gguf',
                    '작가', '장면', '384')


    def test_explicit_scene_target_or_saved_episode_share(self):
        # A project target should reach the native bridge even when the
        # author's ordinary scene description contains no numeric length.
        self.assertEqual(module.requested_scene_target(
            '조사자가 빈 페이지를 발견한다', {'target_chars': 5000}), 5000)
        self.assertEqual(module.requested_scene_target(
            '한국어 원고 6000자 작성', {'target_chars': 2500}), 6000)
        self.assertIsNone(module.requested_scene_target('조사와 추적', {}))
        for bad in (True, -1, '5000', 0, 1000001):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                module.requested_scene_target('조사와 추적', {'target_chars': bad})

    def test_real_continuation_reaches_requested_chars_without_padding(self):
        # Unique non-linguistic tokens exercise byte transport only, NEVER
        # constitute a literary-quality approval or substitute model output.
        intro = '조사자가 기록을 살폈다. ' * 32
        chunks = [''.join(chr(0xAC00 + (i * 600 + j) % 11172)
                          for j in range(550)) + ' 사서가 새로운 계단을 찾았다.'
                  for i in range(9)]
        inputs = iter(chunks)
        seen = []
        def invoke(prompt, remaining):
            seen.append((prompt, remaining))
            return next(inputs)
        result = module.continue_korean_scene(
            intro, original_prompt='한국어 소설을 5000자 작성',
            target_chars=5000, invoke=invoke,
            deadline=999, clock=lambda: 0)
        self.assertGreaterEqual(len(''.join(result.split())), 4500)
        self.assertGreaterEqual(len(seen), 1)
        self.assertTrue(all('이어서' in prompt for prompt, _ in seen))
        self.assertNotIn('[모의 초고', result)

    def test_changed_suffix_cannot_pad_repeated_continuation(self):
        original = '주인공이 도서관을 살폈다.'
        copied = '사서가 낡은 기록을 살펴보았다. ' * 18
        seen = []
        def invoke(_prompt, _remaining):
            seen.append(True)
            return copied if len(seen) == 1 else copied + ' 마지막에 숫자 2를 썼다.'
        actual = module.continue_korean_scene(
            original, original_prompt='도서관', target_chars=5000,
            invoke=invoke, deadline=999, clock=lambda: 0)
        self.assertEqual(len(seen), 2)
        # Validation trims surrounding whitespace from native responses.
        self.assertEqual(actual.count(copied.strip()), 1)

    def test_bundled_mixed_script_gets_one_strict_native_retry(self):
        # Windows real GGUF returned 'NON_KOREAN_SCRIPT' on first attempt.
        # Exactly one real native retry is allowed, and invalid retry still
        # raises, rather than automatically translating the draft.
        calls = []
        def native(prompt, timeout, budget):
            calls.append((prompt, timeout, budget))
            return '사서가 뒤편의 문을 발견했다.'
        observed = module.retry_bundled_korean_text(
            '서가에서 탐사한다', first_error=ValueError(
                'native non-Korean script in draft'),
            invoke=native, remaining=45)
        self.assertIn('사서가', observed)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2], '160')
        with self.assertRaisesRegex(ValueError, 'native non-Korean script'):
            module.retry_bundled_korean_text(
                '서가에서 탐사한다', first_error=ValueError(
                    'native non-Korean script in draft'),
                invoke=native, remaining=10)
        self.assertEqual(len(calls), 1)

    def test_bundled_retry_one_real_native_run_only(self):
        calls = []
        def invoke(prompt, remaining, budget):
            calls.append((prompt, remaining, budget))
            return '사서는 기록을 발견했고 동료에게 그 사실을 전했다.'
        raw = module.retry_bundled_korean_text(
            '작가 소유 설정: 도서관', first_error=ValueError(
                'native output lacks Korean novel prose'),
            invoke=invoke, remaining=60)
        self.assertIn('사서는 기록', raw)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2], '160')
        self.assertIn('작가 소유 설정: 도서관', calls[0][0])
        crash_invokes = []
        module.retry_bundled_korean_text(
            '장면의 작가 소유 설정', first_error=ValueError('model process failed'),
            invoke=lambda prompt, seconds, budget: crash_invokes.append(
                (prompt, seconds, budget)) or '사서가 벽 뒤를 보았다.',
            remaining=25)
        self.assertEqual(len(crash_invokes), 1)
        self.assertEqual(crash_invokes[0][2], '160')
        for reason, remaining in (('native output lacks Korean novel prose', 10),
                                  ('native console output mixed with draft', 60)):
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                module.retry_bundled_korean_text(
                    '원래 설정', first_error=ValueError(reason),
                    invoke=invoke, remaining=remaining)
        self.assertEqual(len(calls), 1)


    def test_repeated_completion_does_not_fill_length(self):
        intro = '주인공이 사라진 기록을 살폈다. ' * 20
        result = module.continue_korean_scene(
            intro, original_prompt='한국어 소설',
            target_chars=5000, invoke=lambda _p, _s: intro,
            deadline=999, clock=lambda: 0)
        self.assertEqual(result, intro)

    def test_continuation_does_not_bypass_native_korean_rejection(self):
        original = '사서가 기록을 읽었다.'
        actual = module.continue_korean_scene(
            original, original_prompt='한국어 소설',
            target_chars=5000, invoke=lambda _p, _s: 'Only English text',
            deadline=999, clock=lambda: 0)
        # A rejected continuation must not be added or fabricated, while
        # the existing valid partial stays available for explicit review.
        self.assertEqual(actual, original)

    def test_native_failure_in_continuation_preserves_partial_without_padding(self):
        original = '조사자는 가상의 섬에서 기록을 발견했다.'
        def error(_prompt, _remaining):
            raise ValueError('model process failed')
        actual = module.continue_korean_scene(
            original, original_prompt='한국어 소설',
            target_chars=5000, invoke=error, deadline=999, clock=lambda: 0)
        self.assertEqual(actual, original)


    def test_elapsed_deadline_returns_unapproved_short_draft_unchanged(self):
        original = '사서가 기록을 읽었다.'
        self.assertEqual(module.continue_korean_scene(
            original, original_prompt='한국어 소설',
            target_chars=5000, invoke=lambda _p, _s: '이후 사건을 쓰기',
            deadline=1, clock=lambda: 2), original)

    def test_timeout_after_valid_native_draft_keeps_unapproved_partial(self):
        initial = '여행자는 기록을 펼쳤다. ' * 30
        def native_timeout(_prompt, _remaining):
            raise subprocess.TimeoutExpired(cmd='llama-completion.exe', timeout=2)
        actual = module.continue_korean_scene(
            initial, original_prompt='한국어 소설을 5000자 집필하세요.',
            target_chars=5000, invoke=native_timeout,
            deadline=999, clock=lambda: 0)
        self.assertEqual(actual, initial)
        self.assertLess(len(''.join(actual.split())), 4500)



if __name__ == '__main__':
    unittest.main()
