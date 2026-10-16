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


if __name__ == '__main__':
    unittest.main()
