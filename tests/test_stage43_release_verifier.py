"""Stage 43 ZIP completeness checks, including inherited hidden files."""
from pathlib import Path
import importlib.util
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_verifier", ROOT / "scripts/verify_release_bundle.py")
verifier = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(verifier)


class Stage43ReleaseTests(unittest.TestCase):
    def verify(self, omitted=None):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bundle.zip"
            with ZipFile(path, "w") as archive:
                for name in verifier.REQUIRED - ({omitted} if omitted else set()):
                    archive.writestr(name, "synthetic fixture")
            return verifier.verify_archive(path)

    def test_required_knowledge_store(self):
        self.assertIn("missing_required_source", self.verify("src/ai_novel_factory/database/character_knowledge.py"))

    def test_required_knowledge_cli(self):
        self.assertIn("missing_required_source", self.verify("src/ai_novel_factory/database/knowledge_cli.py"))

    def test_required_new_tests(self):
        self.assertIn("missing_required_source", self.verify("tests/test_stage43_character_knowledge.py"))

    def test_required_release_tests(self):
        self.assertIn("missing_required_source", self.verify("tests/test_stage43_release_verifier.py"))

    def test_required_report(self):
        self.assertIn("missing_required_source", self.verify("docs/stage43_test_results.json"))

    def test_required_gitignore(self):
        self.assertIn("missing_required_source", self.verify(".gitignore"))

    def test_complete_fixture(self):
        self.assertEqual(self.verify(), ())
