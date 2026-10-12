"""Stage 19: deterministic reference metadata catalog tests."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

from ai_novel_factory.database import CatalogError, ReferenceCatalog


def hashed(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class ReferenceCatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = ReferenceCatalog()

    def tearDown(self):
        self.catalog.close()

    def register(self, filename="C:/private/소설.txt", text="reference", fmt="txt"):
        return self.catalog.register(
            file_name=filename, source_format=fmt,
            byte_count=len(text.encode()), sha256=hashed(text),
        )

    def test_empty(self):
        self.assertEqual(self.catalog.count(), 0)
        self.assertEqual(self.catalog.list(), ())

    def test_register_basename_only(self):
        row = self.register()
        self.assertEqual(row.file_name, "소설.txt")
        self.assertNotIn("private", repr(row))
        self.assertEqual(row.status, "registered")
        self.assertEqual(len(row.reference_id), 32)

    def test_unicode_and_formats(self):
        for fmt in ("txt", "md", "epub", "docx", "pdf"):
            self.register(filename=f"작품.{fmt}", text=fmt, fmt=fmt)
        self.assertEqual(self.catalog.count(), 5)

    def test_markdown_alias(self):
        row = self.register(filename="노트.markdown", text="abc", fmt="markdown")
        self.assertEqual(row.source_format, "md")

    def test_file_identity_deduplication(self):
        a = self.register()
        b = self.register(filename="another.txt")
        self.assertEqual(a.reference_id, b.reference_id)
        self.assertEqual(self.catalog.count(), 1)

    def test_hash_case_deduplication(self):
        a = self.register()
        b = self.catalog.register(file_name="a.txt", source_format="txt",
                                  byte_count=9, sha256=hashed("reference").upper())
        self.assertEqual(a.reference_id, b.reference_id)

    def test_same_hash_inconsistent_format_rejected(self):
        self.register()
        with self.assertRaises(CatalogError):
            self.catalog.register(file_name="name.pdf", source_format="pdf",
                                  byte_count=9, sha256=hashed("reference"))

    def test_same_hash_inconsistent_size_rejected(self):
        self.register()
        with self.assertRaises(CatalogError):
            self.catalog.register(file_name="name.txt", source_format="txt",
                                  byte_count=123, sha256=hashed("reference"))

    def test_invalid_hash_size_type_name(self):
        bad = [dict(file_name="a.txt", source_format="txt", byte_count=1, sha256="bad"),
               dict(file_name="a.txt", source_format="txt", byte_count=0, sha256=hashed("a")),
               dict(file_name="a.txt", source_format="txt", byte_count=True, sha256=hashed("a")),
               dict(file_name="a.txt", source_format="exe", byte_count=1, sha256=hashed("a")),
               dict(file_name="a.pdf", source_format="txt", byte_count=1, sha256=hashed("a")),
               dict(file_name="../", source_format="txt", byte_count=1, sha256=hashed("a"))]
        for item in bad:
            with self.subTest(item=item), self.assertRaises(CatalogError):
                self.catalog.register(**item)
        self.assertEqual(self.catalog.count(), 0)

    def test_filtered_list_and_pagination(self):
        self.register(text="a")
        second = self.register(text="b")
        self.catalog.change_status(second.reference_id, "analyzing")
        self.assertEqual(len(self.catalog.list(limit=1)), 1)
        self.assertEqual(len(self.catalog.list(limit=1, offset=1)), 1)
        self.assertEqual(self.catalog.count(status="analyzing"), 1)
        self.assertEqual(self.catalog.list(status="analyzing")[0].reference_id, second.reference_id)

    def test_valid_status_lifecycle(self):
        row = self.register()
        self.catalog.change_status(row.reference_id, "analyzing")
        self.catalog.change_status(row.reference_id, "failed")
        self.catalog.change_status(row.reference_id, "analyzing")
        updated = self.catalog.change_status(row.reference_id, "analyzed")
        self.assertEqual(updated.status, "analyzed")
        self.assertNotEqual(updated.updated_at, "")

    def test_illegal_status_transition(self):
        row = self.register()
        with self.assertRaises(CatalogError):
            self.catalog.change_status(row.reference_id, "analyzed")
        self.assertEqual(self.catalog.get(row.reference_id).status, "registered")

    def test_unknown_record(self):
        with self.assertRaises(CatalogError):
            self.catalog.get("unknown")
        with self.assertRaises(CatalogError):
            self.catalog.change_status("unknown", "analyzing")

    def test_bad_query_range(self):
        for args in ({"limit": 0}, {"limit": True}, {"limit": 1001},
                     {"offset": -1}, {"offset": False}, {"status": "oops"}):
            with self.subTest(args=args), self.assertRaises(CatalogError):
                self.catalog.list(**args)

    def test_persistent_database(self):
        with tempfile.TemporaryDirectory() as directory:
            location = Path(directory) / "catalog.sqlite3"
            with ReferenceCatalog(location) as db:
                row = db.register(file_name="테스트.txt", source_format="txt",
                                  byte_count=3, sha256=hashed("abc"))
            with ReferenceCatalog(location) as db:
                self.assertEqual(db.count(), 1)
                self.assertEqual(db.get(row.reference_id).file_name, "테스트.txt")
            with sqlite3.connect(location) as conn:
                columns = {c[1] for c in conn.execute("PRAGMA table_info(reference_files)")}
                self.assertEqual(columns, {"reference_id", "file_name", "source_format",
                                           "byte_count", "sha256", "status", "created_at", "updated_at"})

    def test_missing_parent_directory_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(CatalogError):
                ReferenceCatalog(Path(directory) / "missing" / "db.sqlite3")

    def test_sql_injection_is_plain_data(self):
        row = self.register(filename="x'); DROP TABLE reference_files; --.txt")
        self.assertEqual(self.catalog.get(row.reference_id).file_name, "x'); DROP TABLE reference_files; --.txt")
        self.assertEqual(self.catalog.count(), 1)

    def test_no_source_text_columns(self):
        columns = {r[1] for r in self.catalog._db.execute("PRAGMA table_info(reference_files)")}
        self.assertFalse(columns & {"text", "content", "raw_manuscript", "full_path", "api_key"})


if __name__ == "__main__":
    unittest.main()
