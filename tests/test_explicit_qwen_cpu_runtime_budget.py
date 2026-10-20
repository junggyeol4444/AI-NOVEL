"""Opt-in Windows Qwen CPU runtime budget regression; NOT literary acceptance."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ai_novel_factory.local_models import LocalExecutableProvider, LocalModelError


class ExplicitCpuRuntimeBudgetTests(unittest.TestCase):
    def test_only_explicit_bundled_gguf_path_can_use_long_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bridge = root / 'ANF_Local_Model.exe'
            custom = root / 'OtherModel.exe'
            for executable in (bridge, custom):
                executable.write_bytes(b'MZ')
                executable.chmod(0o755)
            arguments = ('--gguf', str(root / 'chosen.gguf'))
            provider = LocalExecutableProvider(
                str(bridge), arguments=arguments, timeout_seconds=1500,
                explicitly_allowed=True)
            self.assertEqual(provider._timeout, 1500)
            for exe, args, timeout in (
                    (bridge, arguments, 1551),
                    (bridge, (), 481),
                    (custom, arguments, 481)):
                with self.subTest(executable=exe.name, args=args), self.assertRaises(LocalModelError):
                    LocalExecutableProvider(str(exe), arguments=args,
                                            timeout_seconds=timeout,
                                            explicitly_allowed=True)

    def test_windows_and_bridge_budgets_are_aligned(self):
        session = (ROOT / 'src/ai_novel_factory/desktop/authoring_session.py').read_text(encoding='utf-8')
        bridge = (ROOT / 'packaging/windows/local_model_bridge.py').read_text(encoding='utf-8')
        workflow = (ROOT / '.github/workflows/anf-real-windows-exe-korean-literary-gate.yml').read_text(encoding='utf-8')
        self.assertIn('limit = 1500 if user_gguf and packaged_bridge', session)
        self.assertIn("native_timeout = (1400 if model.name.lower()", bridge)
        self.assertIn('for($i=0;$i -lt 3900;$i++){', workflow)
        self.assertIn('timeout-minutes: 35', workflow)


if __name__ == '__main__':
    unittest.main()
