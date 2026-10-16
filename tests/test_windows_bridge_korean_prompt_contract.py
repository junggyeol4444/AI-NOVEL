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
        self.assertIn('영어로 먼저 작성하여 번역하거나 영어 해설을 섞지 마세요', source)
        self.assertIn('같은 문장을 반복해 분량을 채우거나', source)
        self.assertIn('Novel Bible', source)

    def test_output_budget_no_longer_384(self):
        source = SOURCE.read_text(encoding='utf-8')
        self.assertIn("prediction_budget = '384' if is_bundled_qa_model else '1536'", source)
        self.assertIn('native_timeout = 110 if is_bundled_qa_model else 400', source)
        self.assertIn("'--ctx-size', '4096'", source)

    def test_no_network_api_or_auto_publish(self):
        source = SOURCE.read_text(encoding='utf-8')
        self.assertNotIn('requests.post(', source)
        self.assertIn("MODEL_PROTO = 'anf-local-scene-v1'", source)
        self.assertIn('No shell or network paths are permitted', source)


if __name__ == '__main__':
    unittest.main()
