"""Stage 49 release contract: cumulative offline ZIP includes episode storage."""
from pathlib import Path
import importlib.util
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("stage49_verifier", ROOT / "scripts/verify_release_bundle.py")
verifier = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(verifier)


class Stage49ReleaseTests(unittest.TestCase):
    def verify(self, missing=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bundle.zip"
            with ZipFile(path, "w") as archive:
                for name in verifier.REQUIRED - ({missing} if missing else set()):
                    archive.writestr(name, "synthetic source")
            return verifier.verify_archive(path)

    def test_complete_fixture(self):
        self.assertEqual(self.verify(), ())

    def test_episode_store_required(self):
        self.assertIn("missing_required_source", self.verify(
            "src/ai_novel_factory/database/episodes.py"))

    def test_episode_cli_required(self):
        self.assertIn("missing_required_source", self.verify(
            "src/ai_novel_factory/database/episode_cli.py"))

    def test_episode_tests_required(self):
        self.assertIn("missing_required_source", self.verify("tests/test_stage49_episodes.py"))

    def test_release_tests_required(self):
        self.assertIn("missing_required_source", self.verify("tests/test_stage49_release_verifier.py"))

    def test_report_required(self):
        self.assertIn("missing_required_source", self.verify("docs/stage49_test_results.json"))

    def test_log_required(self):
        self.assertIn("missing_required_source", self.verify("docs/stage49_verification_log.txt"))

    def test_documentation_required(self):
        self.assertIn("missing_required_source", self.verify("docs/stage49_episodes.md"))

    def test_previous_style_store_required(self):
        self.assertIn("missing_required_source", self.verify(
            "src/ai_novel_factory/database/style_bible.py"))

    def test_previous_style_report_required(self):
        self.assertIn("missing_required_source", self.verify("docs/stage48_test_results.json"))

    def test_previous_foreshadow_required(self):
        self.assertIn("missing_required_source", self.verify(
            "src/ai_novel_factory/database/foreshadow.py"))

    def test_gitignore_required(self):
        self.assertIn("missing_required_source", self.verify(".gitignore"))

    def test_env_example_required(self):
        self.assertIn("missing_required_source", self.verify(".env.example"))

    def test_original_reference_tests_required(self):
        self.assertIn("missing_required_source", self.verify(
            "tests/test_stage40_reference_integration.py"))


if __name__ == "__main__":
    unittest.main()
