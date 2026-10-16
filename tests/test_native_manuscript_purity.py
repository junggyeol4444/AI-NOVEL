"""Synthetic transport regression: rejecting llama-cli banners is not literary approval."""
import importlib.util
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

    def test_smoke_model_preserves_previous_single_turn_runner(self):
        cli = Path('runtime/llama-cli.exe')
        command = module.build_native_command(
            cli, Path('models/SmolLM2-135M-Instruct-Q4_K_M.gguf'),
            '작가', '장면', '384')
        self.assertEqual(command[0], str(cli))
        self.assertIn('--single-turn', command)
        self.assertIn('--system-prompt', command)


if __name__ == '__main__':
    unittest.main()
