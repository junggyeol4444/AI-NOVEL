import sqlite3
import tempfile
import unittest
from pathlib import Path

from ai_novel_factory.database.novel_bible import NovelBibleStore
from ai_novel_factory.database.migrations import (
    MigrationError, audit_database, migrate_database, SCHEMA_VERSION,
)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'novel.db'
        self.backup = Path(self.tmp.name) / 'backup.db'
        with NovelBibleStore(self.path) as store:
            self.project = store.create_project('원본 작품').project_id
            store.save_rule(self.project, 'genre', '판타지')

    def test_preserve_and_backup(self):
        before = audit_database(self.path)
        self.assertTrue(before.integrity_ok)
        result = migrate_database(self.path, self.backup)
        self.assertEqual(result.version, SCHEMA_VERSION)
        self.assertEqual(audit_database(self.backup).version, 0)
        with NovelBibleStore(self.path) as store:
            self.assertEqual(store.get_rule(self.project, 'genre').value, '판타지')
        with NovelBibleStore(self.backup) as store:
            self.assertEqual(store.get_rule(self.project, 'genre').value, '판타지')

    def test_idempotent_with_new_backup(self):
        migrate_database(self.path, self.backup)
        second = Path(self.tmp.name) / 'second.db'
        self.assertEqual(migrate_database(self.path, second).version, 1)

    def test_refuse_overwrite(self):
        self.backup.write_text('keep')
        with self.assertRaises(MigrationError):
            migrate_database(self.path, self.backup)
        self.assertEqual(self.backup.read_text(), 'keep')

    def test_refuse_future_version(self):
        with sqlite3.connect(self.path) as db:
            db.execute('PRAGMA user_version=999')
        with self.assertRaises(MigrationError):
            migrate_database(self.path, self.backup)
        self.assertFalse(self.backup.exists())

    def test_refuse_corrupt_file(self):
        self.path.write_bytes(b'not a sqlite database')
        with self.assertRaises(MigrationError):
            migrate_database(self.path, self.backup)

    def test_refuse_missing_tables(self):
        other = Path(self.tmp.name) / 'empty.db'
        with sqlite3.connect(other):
            pass
        with self.assertRaises(MigrationError):
            migrate_database(other, self.backup)

    def test_refuse_network_uri(self):
        with self.assertRaises(MigrationError):
            audit_database('file:remote?mode=ro')

    def test_refuse_same_path(self):
        with self.assertRaises(MigrationError):
            migrate_database(self.path, self.path)

    def test_refuse_symlink(self):
        link = Path(self.tmp.name) / 'link.db'
        link.symlink_to(self.path)
        with self.assertRaises(MigrationError):
            audit_database(link)


if __name__ == '__main__':
    unittest.main()
