"""Offline native bridge model-profile regression. This does not certify prose."""
import unittest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / 'packaging/windows/local_model_bridge.py').read_text(encoding='utf-8')


class NativeProfileBudgetTests(unittest.TestCase):
    def test_smoke_and_korean_profiles_have_distinct_bounded_timeouts(self):
        self.assertIn("prediction_budget = '384' if is_bundled_qa_model else '3072'", SOURCE)
        self.assertIn("prediction_budget = '512'", SOURCE)
        self.assertIn("if model.name.lower().startswith('qwen2.5-')", SOURCE)
        self.assertIn('native_timeout = 110 if is_bundled_qa_model else 400', SOURCE)
        self.assertIn("'--predict', prediction_budget", SOURCE)

    def test_no_cloud_model_provider(self):
        self.assertIn("MODEL_PROTO = 'anf-local-scene-v1'", SOURCE)
        self.assertNotIn("requests.post(", SOURCE)
