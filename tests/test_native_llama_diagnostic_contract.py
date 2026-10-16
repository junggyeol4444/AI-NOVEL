"""Windows process transport probing is diagnostic only (not quality PASS)."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / '.github/workflows/anf-real-windows-exe-korean-literary-gate.yml').read_text(encoding='utf-8')
PROBE = (ROOT / 'scripts/ci_native_llama_diagnostic.py').read_text(encoding='utf-8')


class NativeWindowsDiagnosticContract(unittest.TestCase):
    def test_actual_gui_abort_on_model_failure(self):
        self.assertIn("throw 'real_native_model_failed_before_draft'", WORKFLOW)
        self.assertIn("gui_model_failure='native_output_rejected'", WORKFLOW)
        self.assertIn('ANF_QA_CLI', WORKFLOW)

    def test_probe_never_prints_actual_output(self):
        self.assertIn("kind='diagnostic_not_literary_acceptance'", PROBE)
        self.assertNotIn('print(prose)', PROBE)
        self.assertNotIn('print(synthetic)', PROBE)
        self.assertIn('capture_output=True', PROBE)
        self.assertIn("'--no-conversation'", PROBE)
        self.assertIn("'no_conversation_raw_completion'", PROBE)


if __name__ == '__main__':
    unittest.main()
