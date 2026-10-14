"""Stage 47 release must retain prior work and include foreshadow source/tests/docs."""
from pathlib import Path
import importlib.util
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("stage47_verifier", ROOT / "scripts/verify_release_bundle.py")
verifier = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(verifier)


class Stage47ReleaseTests(unittest.TestCase):
    def verify(self, missing=None):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bundle.zip"
            with ZipFile(path, "w") as archive:
                for name in verifier.REQUIRED - ({missing} if missing else set()):
                    archive.writestr(name, "synthetic source")
            return verifier.verify_archive(path)

    def test_complete_fixture(self):
        self.assertEqual(self.verify(), ())

    def test_foreshadow_store_required(self):
        self.assertIn("missing_required_source", self.verify(
            "src/ai_novel_factory/database/foreshadow.py"))

    def test_foreshadow_cli_required(self):
        self.assertIn("missing_required_source", self.verify(
            "src/ai_novel_factory/database/foreshadow_cli.py"))

    def test_foreshadow_tests_required(self):
        self.assertIn("missing_required_source", self.verify(
            "tests/test_stage47_foreshadow.py"))

    def test_release_tests_required(self):
        self.assertIn("missing_required_source", self.verify(
            "tests/test_stage47_release_verifier.py"))

    def test_report_required(self):
        self.assertIn("missing_required_source", self.verify("docs/stage47_test_results.json"))

    def test_verification_log_required(self):
        self.assertIn("missing_required_source", self.verify("docs/stage47_verification_log.txt"))

    def test_documentation_required(self):
        self.assertIn("missing_required_source", self.verify("docs/stage47_foreshadow.md"))

    def test_previous_stage_required(self):
        self.assertIn("missing_required_source", self.verify("docs/stage46_test_results.json"))

    def test_previous_timeline_required(self):
        self.assertIn("missing_required_source", self.verify(
            "src/ai_novel_factory/database/event_timeline.py"))

    def test_gitignore_required(self):
        self.assertIn("missing_required_source", self.verify(".gitignore"))

    def test_python_version_required(self):
        self.assertIn("missing_required_source", self.verify(".python-version"))


if __name__ == "__main__":
    unittest.main()
