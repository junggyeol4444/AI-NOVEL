"""Stage 10: tests for the smoke runner itself (stdlib only)."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("stage10_smoke", ROOT / "scripts" / "smoke_test.py")
smoke = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = smoke
SPEC.loader.exec_module(smoke)


class SmokeRunnerTests(unittest.TestCase):
    def test_offline_contracts_pass(self):
        results = smoke.offline_checks()
        self.assertEqual(len(results), 7)
        self.assertFalse(any(item.status == "FAIL" for item in results))
        self.assertEqual({item.check for item in results}, {
            "safe_defaults", "health_contract", "desktop_navigation", "loopback_guard",
            "api_cli", "desktop_cli", "python_version",
        })

    def test_cli_json_report(self):
        run = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "smoke_test.py"), "--json"],
            cwd=ROOT, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        payload = json.loads(run.stdout)
        self.assertEqual(payload["stage"], 10)
        self.assertTrue(payload["passed"])
        self.assertTrue(all(r["status"] != "FAIL" for r in payload["results"]))

    def test_explicit_http_flag_only(self):
        with patch.object(smoke, "http_check") as check:
            check.return_value = smoke.Result("http_roundtrip", "PASS", "test")
            with patch.object(smoke, "offline_checks", return_value=[]):
                with patch("builtins.print"):
                    self.assertEqual(smoke.main([]), 0)
                    check.assert_not_called()
                    self.assertEqual(smoke.main(["--with-http"]), 0)
                    check.assert_called_once()

    def test_failure_sets_exit_code(self):
        with patch.object(smoke, "offline_checks", return_value=[smoke.Result("x", "FAIL", "test")]):
            with patch("builtins.print"):
                self.assertEqual(smoke.main([]), 1)

    def test_gui_missing_skips_without_launch(self):
        with patch.object(smoke, "_has_modules", return_value=False):
            with patch.object(smoke.subprocess, "run") as runner:
                result = smoke.gui_check()
                self.assertEqual(result.status, "SKIP")
                runner.assert_not_called()

    def test_http_missing_skips_without_launch(self):
        with patch.object(smoke, "_has_modules", return_value=False):
            with patch.object(smoke.subprocess, "Popen") as runner:
                result = smoke.http_check()
                self.assertEqual(result.status, "SKIP")
                runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
