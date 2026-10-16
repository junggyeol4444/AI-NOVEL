"""Source-level regression for native asynchronous GUI; NOT a product acceptance."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
GUI = (ROOT / 'src/ai_novel_factory/desktop/authoring_workflow.py').read_text(encoding='utf-8')
WORKER = (ROOT / 'src/ai_novel_factory/desktop/draft_worker.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'src/ai_novel_factory/desktop/app.py').read_text(encoding='utf-8')


class AsyncNativeGuiSourceRegression(unittest.TestCase):
    def test_native_inference_only_in_background_worker(self):
        self.assertIn('class DraftWorker(QThread)', WORKER)
        self.assertIn('draft_scene(self._request, self._provider)', WORKER)
        self.assertNotIn('self.session.generate(', GUI)
        self.assertIn('worker.start()', GUI)

    def test_live_gui_does_not_close_during_inference(self):
        self.assertIn('authoring.is_generating()', MAIN)
        self.assertIn('accept_generation(', GUI)
        self.assertIn('한국어 형식 검사 미달', GUI)
        self.assertIn('한국어 형식 1차 검사 충족', GUI)
        self.assertIn('screen_korean_draft(', GUI)
        self.assertIn("setAccessibleName('한국어 형식 검사 미달')", GUI)


if __name__ == '__main__':
    unittest.main()
