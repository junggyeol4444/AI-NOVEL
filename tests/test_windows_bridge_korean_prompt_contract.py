"""Non-acceptance source regression: the Windows real EXE CI is authoritative.

This only checks that the bundled local bridge no longer asks for English-first prose
or limits all scenes to the historical 384 tokens. It does not certify model output.
"""
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'packaging' / 'windows' / 'local_model_bridge.py'


class KoreanNativeBridgeSourceContract(unittest.TestCase):
    def test_korean_native_not_translation(self):
        source = SOURCE.read_text(encoding='utf-8')
        self.assertIn('def build_story_prompts(', source)
        self.assertIn('prose_retry: bool = False', source)
        self.assertIn('prose_retry=True', source)
        self.assertIn('attempt=initial_retry', source)
        self.assertIn('한국어 서술과 자연스러운 대화로 하나의 장면을 전개합니다', source)
        self.assertIn('인물의 선택, 행동, 대화', source)
        self.assertIn('system_prompt, prompt = build_story_prompts(', source)
        self.assertIn("'--system-prompt', system_prompt", source)
        self.assertIn("'--repeat-penalty', ('1.08' if qwen else '1.16')", source)
        self.assertIn("'--log-disable', '--no-show-timings'", source)
        self.assertNotIn("'--simple-io',", source)
        self.assertIn('draft = validate_clean_manuscript(raw_draft)', source)
        self.assertIn('latin > max(5, (len(compact) + 19) // 20)', source)
        self.assertIn('현재 장면에서 아직 필요한 분량은 공백 제외 약', source)
        self.assertIn('new = validate_clean_manuscript(next_raw)', source)

    def test_output_budget_no_longer_384(self):
        source = SOURCE.read_text(encoding='utf-8')
        self.assertIn("prediction_budget = '384' if is_bundled_qa_model else '3072'", source)
        self.assertIn("1400 if model.name.lower().startswith('qwen2.5-')", source)
        self.assertIn('bundled_timeout_seconds(arm64_host=windows_native_arm64())', source)
        self.assertIn('if is_bundled_qa_model else 400)', source)
        self.assertIn("'--ctx-size', '4096'", source)
        self.assertIn(
            "threads = '1' if qwen_crash_recovery else ('4' if qwen else '1')",
            source)
        self.assertIn('run_native_with_heap_crash_recovery(', source)
        self.assertIn('qwen_crash_recovery=True', source)

    def test_no_network_api_or_auto_publish(self):
        source = SOURCE.read_text(encoding='utf-8')
        self.assertNotIn('requests.post(', source)
        self.assertIn("MODEL_PROTO = 'anf-local-scene-v1'", source)
        self.assertIn('No shell or network paths are permitted', source)
        self.assertNotIn("'<|im_start|>system", source)
        self.assertIn("'style_bible'", source)


if __name__ == '__main__':
    unittest.main()
