"""Stage-5 metadata checks (stdlib only)."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_dependencies", ROOT / "scripts" / "check_dependencies.py")
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


class DependencyPolicyTests(unittest.TestCase):
    def test_manifest_policy(self):
        self.assertEqual(module.check(), [])

    def test_python_version_file(self):
        self.assertEqual((ROOT / ".python-version").read_text(encoding="utf-8").strip(), "3.12")

    def test_no_fabricated_lockfile(self):
        # No lockfile until dependency resolution has actually run.
        self.assertFalse((ROOT / "uv.lock").exists())

    def test_secret_exclusions(self):
        rules = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for secret in (".env", "*.key", "*.pem", "secrets/"):
            with self.subTest(secret=secret):
                self.assertIn(secret, rules)


if __name__ == "__main__":
    unittest.main()
