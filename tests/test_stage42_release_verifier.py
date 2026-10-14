"""Stage 42 cumulative archive must include source, tests, report and hidden files."""
from pathlib import Path
import importlib.util
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("stage42_verifier", ROOT / "scripts/verify_release_bundle.py")
verifier = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(verifier)


class Stage42ReleaseTests(unittest.TestCase):
    def check(self, missing=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "release.zip"
            with ZipFile(path, "w") as bundle:
                for name in verifier.REQUIRED - ({missing} if missing else set()):
                    bundle.writestr(name, "synthetic fixture")
            return verifier.verify_archive(path)

    def test_character_store_required(self):
        self.assertIn("missing_required_source", self.check("src/ai_novel_factory/database/characters.py"))

    def test_character_cli_required(self):
        self.assertIn("missing_required_source", self.check("src/ai_novel_factory/database/character_cli.py"))

    def test_character_tests_required(self):
        self.assertIn("missing_required_source", self.check("tests/test_stage42_characters.py"))

    def test_report_required(self):
        self.assertIn("missing_required_source", self.check("docs/stage42_test_results.json"))

    def test_hidden_gitignore_required(self):
        self.assertIn("missing_required_source", self.check(".gitignore"))

    def test_complete_fixture_passes(self):
        self.assertEqual(self.check(), ())
