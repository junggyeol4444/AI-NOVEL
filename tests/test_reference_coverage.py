"""Synthetic-only coverage tests; never open a user's reference catalog."""
from pathlib import Path
from contextlib import closing
import importlib.util
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory.desktop.reference_coverage import read_reference_coverage


class ReferenceCoverageTests(unittest.TestCase):
    def test_missing_file_does_not_create_or_claim_zero(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "missing.sqlite"
            result = read_reference_coverage(path)
            self.assertIsNone(result.registered)
            self.assertEqual(result.reason, "MISSING")
            self.assertIn("NOT_RUN", result.label)
            self.assertFalse(path.exists())

    def test_registered_counts_and_no_write(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "catalog.sqlite"
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("CREATE TABLE reference_files (status TEXT)")
                db.executemany("INSERT INTO reference_files VALUES (?)",
                               [("analyzed",), ("registered",), ("failed",)])
            before = path.read_bytes()
            result = read_reference_coverage(path)
            self.assertEqual((result.registered, result.analyzed), (3, 1))
            self.assertIn("NOT_RUN", result.label)
            self.assertEqual(path.read_bytes(), before)

    def test_valid_empty_catalog_is_zero_but_not_clear(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "catalog.sqlite"
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("CREATE TABLE reference_files (status TEXT)")
            result = read_reference_coverage(path)
            self.assertEqual((result.registered, result.analyzed), (0, 0))
            self.assertIn("NOT_RUN", result.label)

    def test_bad_schema_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "catalog.sqlite"
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("CREATE TABLE other (id INTEGER)")
            result = read_reference_coverage(path)
            self.assertIsNone(result.registered)
            self.assertEqual(result.reason, "UNAVAILABLE")

    def test_relative_and_symlink_paths_rejected(self):
        self.assertEqual(read_reference_coverage(Path("relative.sqlite")).reason, "INVALID_PATH")
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "catalog.sqlite"
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("CREATE TABLE reference_files (status TEXT)")
            link = Path(root) / "link.sqlite"
            try:
                link.symlink_to(path)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unsupported")
            self.assertEqual(read_reference_coverage(link).reason, "INVALID_PATH")


    def test_unrecognized_or_null_status_never_claims_coverage(self):
        for invalid in ("complete", None):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as root:
                path = Path(root) / "legacy.sqlite"
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute("CREATE TABLE reference_files (status TEXT)")
                    db.executemany("INSERT INTO reference_files VALUES (?)",
                                   [("analyzed",), (invalid,)])
                before = path.read_bytes()
                result = read_reference_coverage(path)
                self.assertEqual(result.reason, "INVALID_STATUS")
                self.assertIsNone(result.registered)
                self.assertIsNone(result.analyzed)
                self.assertIn("NOT_RUN", result.label)
                self.assertEqual(path.read_bytes(), before)

    def test_all_documented_statuses_are_counted_without_claiming_similarity(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "catalog.sqlite"
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("CREATE TABLE reference_files (status TEXT)")
                db.executemany("INSERT INTO reference_files VALUES (?)",
                               [(s,) for s in ("registered", "analyzing", "analyzed", "failed")])
            result = read_reference_coverage(path)
            self.assertEqual(result.reason, "AVAILABLE")
            self.assertEqual((result.registered, result.analyzed), (4, 1))
            self.assertIn("NOT_RUN", result.label)


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 not installed")
class ReferenceCoverageGuiTests(unittest.TestCase):
    def test_similarity_page_never_calls_it_full_similarity(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from ai_novel_factory.desktop.additional_workspaces import SimilarityWorkspace
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "synthetic.sqlite"
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("CREATE TABLE reference_files (status TEXT)")
                db.executemany("INSERT INTO reference_files VALUES (?)",
                               [("analyzed",), ("registered",)])
            with patch("ai_novel_factory.desktop.additional_workspaces.default_local_catalog_path", return_value=path):
                widget = SimilarityWorkspace(lambda: None)
                self.assertIn("NOT_RUN", widget.coverage_status.text())
                widget.coverage_button.click()
                self.assertIn("등록 참고작 2개 / 분석 완료 1개", widget.coverage_status.text())
                self.assertIn("NOT_RUN", widget.coverage_status.text())
                widget.close()
        self.assertIsNotNone(app)


if __name__ == "__main__":
    unittest.main()
