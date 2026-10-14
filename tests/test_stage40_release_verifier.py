"""Stage 40: ensure exported cumulative ZIPs are actually runnable and private."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import stat
import tempfile
import unittest
from zipfile import ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verify_release_bundle", ROOT / "scripts/verify_release_bundle.py")
verifier = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(verifier)


class ReleaseVerifierTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "local.zip"

    def _archive(self, *, missing=(), extra=(), custom=None):
        with ZipFile(self.path, "w") as bundle:
            for name in sorted(verifier.REQUIRED - set(missing)):
                bundle.writestr(name, b"synthetic source")
            for name in extra:
                bundle.writestr(name, b"synthetic secret")
            if custom is not None:
                bundle.writestr(custom, b"synthetic")
        return verifier.verify_archive(self.path)

    def test_complete_synthetic_bundle_passes(self):
        self.assertEqual(self._archive(), ())

    def test_hidden_gitignore_is_required_for_dependency_tests(self):
        self.assertIn("missing_required_source", self._archive(missing={".gitignore"}))

    def test_missing_integration_tests_rejected(self):
        self.assertIn("missing_required_source", self._archive(missing={
            "tests/test_stage40_reference_integration.py"}))

    def test_path_traversal_rejected(self):
        self.assertIn("unsafe_archive_path", self._archive(extra={"../outside.txt"}))

    def test_windows_path_separator_rejected(self):
        self.assertIn("unsafe_archive_path", self._archive(extra={"src\\..\\escape.py"}))

    def test_private_env_rejected(self):
        self.assertIn("private_or_build_artifact", self._archive(extra={".env"}))

    def test_private_database_rejected(self):
        self.assertIn("private_or_build_artifact", self._archive(extra={"docs/secret.sqlite3"}))

    def test_github_directory_rejected(self):
        self.assertIn("private_or_build_artifact", self._archive(extra={".github/workflows/ci.yml"}))

    def test_build_artifact_rejected(self):
        self.assertIn("private_or_build_artifact", self._archive(extra={"src/__pycache__/foo.pyc"}))

    def test_duplicate_archive_member_rejected(self):
        import warnings
        with ZipFile(self.path, "w") as bundle:
            for name in sorted(verifier.REQUIRED):
                bundle.writestr(name, b"synthetic")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                bundle.writestr("README.md", b"duplicate")
        self.assertIn("duplicate_entry", verifier.verify_archive(self.path))

    def test_symlink_member_rejected(self):
        with ZipFile(self.path, "w") as bundle:
            for name in sorted(verifier.REQUIRED):
                bundle.writestr(name, b"synthetic")
            item = ZipInfo("docs/shortcut")
            item.create_system = 3
            item.external_attr = (stat.S_IFLNK | 0o777) << 16
            bundle.writestr(item, "../outside")
        self.assertIn("symlink_entry", verifier.verify_archive(self.path))

    def test_corrupt_zip_rejected(self):
        self.path.write_bytes(b"not a zip")
        self.assertEqual(verifier.verify_archive(self.path), ("unreadable_archive",))

    def test_reject_unknown_top_level_file(self):
        self.assertIn("unexpected_archive_entry", self._archive(extra={"private_notes.txt"}))

    def test_no_filename_in_error_categories(self):
        problems = self._archive(extra={"docs/PRIVATE_SECRET_DO_NOT_PRINT.sqlite3"})
        self.assertNotIn("PRIVATE_SECRET_DO_NOT_PRINT", repr(problems))


if __name__ == "__main__":
    unittest.main()
