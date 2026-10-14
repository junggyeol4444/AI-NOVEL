"""Stage 48 release contract: all previous stages and Style Bible are present."""
from pathlib import Path
import importlib.util
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("stage48_verifier", ROOT / "scripts/verify_release_bundle.py")
verifier = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(verifier)


class Stage48ReleaseTests(unittest.TestCase):
    def verify(self, missing=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bundle.zip"
            with ZipFile(path, "w") as archive:
                for name in verifier.REQUIRED - ({missing} if missing else set()):
                    archive.writestr(name, "synthetic source")
            return verifier.verify_archive(path)

    def test_complete_fixture(self):
        self.assertEqual(self.verify(), ())

    def test_required_style_store(self):
        self.assertIn("missing_required_source", self.verify(
            "src/ai_novel_factory/database/style_bible.py"))

    def test_required_style_cli(self):
        self.assertIn("missing_required_source", self.verify(
            "src/ai_novel_factory/database/style_cli.py"))

    def test_required_style_tests(self):
        self.assertIn("missing_required_source", self.verify("tests/test_stage48_style_bible.py"))

    def test_required_release_tests(self):
        self.assertIn("missing_required_source", self.verify("tests/test_stage48_release_verifier.py"))

    def test_required_report(self):
        self.assertIn("missing_required_source", self.verify("docs/stage48_test_results.json"))

    def test_required_log(self):
        self.assertIn("missing_required_source", self.verify("docs/stage48_verification_log.txt"))

    def test_required_documentation(self):
        self.assertIn("missing_required_source", self.verify("docs/stage48_style_bible.md"))

    def test_previous_foreshadow_required(self):
        self.assertIn("missing_required_source", self.verify(
            "src/ai_novel_factory/database/foreshadow.py"))

    def test_previous_report_required(self):
        self.assertIn("missing_required_source", self.verify("docs/stage47_test_results.json"))

    def test_novel_bible_required(self):
        self.assertIn("missing_required_source", self.verify(
            "src/ai_novel_factory/database/novel_bible.py"))

    def test_gitignore_required(self):
        self.assertIn("missing_required_source", self.verify(".gitignore"))

    def test_env_example_required(self):
        self.assertIn("missing_required_source", self.verify(".env.example"))


if __name__ == "__main__":
    unittest.main()
