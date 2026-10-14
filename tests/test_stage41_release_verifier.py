"""Stage 41 release verifier now requires Novel Bible source, tests and report."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("stage41_verifier", ROOT / "scripts/verify_release_bundle.py")
verifier = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(verifier)


class Stage41ReleaseTests(unittest.TestCase):
    def _check(self, omit=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "release.zip"
            with ZipFile(path, "w") as bundle:
                for name in verifier.REQUIRED - ({omit} if omit else set()):
                    bundle.writestr(name, "test fixture")
            return verifier.verify_archive(path)

    def test_new_novel_bible_source_required(self):
        self.assertIn("missing_required_source", self._check("src/ai_novel_factory/database/novel_bible.py"))

    def test_new_novel_bible_tests_required(self):
        self.assertIn("missing_required_source", self._check("tests/test_stage41_novel_bible.py"))

    def test_new_report_required(self):
        self.assertIn("missing_required_source", self._check("docs/stage41_test_results.json"))

    def test_all_required_present(self):
        self.assertEqual(self._check(), ())
