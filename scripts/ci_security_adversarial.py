"""Actual malicious-value regression checks for Bandit B608/B314 warnings.

These checks provide bounded evidence, not a proof of general security.
All databases and documents are synthetic. No user account or platform API.
"""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from ai_novel_factory.database.characters import CharacterStore
from ai_novel_factory.database.episodes import EpisodeStore
from ai_novel_factory.database.world_canon import WorldCanonStore
from ai_novel_factory.memory_application import MemoryCanonStore, MemoryApplicationError
from ai_novel_factory.operations_monitor import OperationsReader, OperationsError
from ai_novel_factory.epub3 import EpubError, _parse_xml, MAX_CHAPTER_BYTES

SQL_VALUE = "valid'); DROP TABLE bible_projects; --"

class InjectionDefenses(unittest.TestCase):
    def test_character_update_sql_payload_is_literal(self):
        store=CharacterStore(":memory:")
        self.addCleanup(store.close)
        pid=store.create_project("synthetic").project_id
        ch=store.create_character(pid,name="someone",personality="calm",
                                   goal="build",speech_style="short",secret="untouched")
        result=store.update_character(pid,ch.character_id,expected_revision=ch.revision,name=SQL_VALUE)
        self.assertEqual(result.name,SQL_VALUE)
        self.assertEqual(result.secret,"untouched")
        self.assertIsNotNone(store.get_project(pid))

    def test_episode_update_sql_payload_is_literal(self):
        store=EpisodeStore(":memory:")
        self.addCleanup(store.close)
        pid=store.create_project("synthetic").project_id
        ep=store.create_episode(pid,1,plot="unchanged plot")
        after=store.update_episode(pid,1,expected_revision=ep.revision,draft=SQL_VALUE)
        self.assertEqual(after.draft,SQL_VALUE)
        self.assertEqual(after.plot,"unchanged plot")
        self.assertIsNotNone(store.get_project(pid))

    def test_episode_scene_update_sql_payload_is_literal(self):
        store=EpisodeStore(":memory:")
        self.addCleanup(store.close)
        pid=store.create_project("synthetic").project_id
        ep=store.create_episode(pid,1)
        scene=store.add_scene(pid,1,1,"original scene",expected_revision=ep.revision)
        rev=store.get_episode(pid,1).revision
        after=store.update_scene(pid,1,scene.scene_id,expected_revision=rev,text=SQL_VALUE)
        self.assertEqual(after.text,SQL_VALUE)
        self.assertIsNotNone(store.get_project(pid))

    def test_world_canon_update_sql_payload_is_literal(self):
        store=WorldCanonStore(":memory:")
        self.addCleanup(store.close)
        pid=store.create_project("synthetic").project_id
        entry=store.create_entry(pid,category="region",name="Town",description="untouched")
        changed=store.update_entry(pid,entry.entry_id,expected_revision=entry.revision,
                                   name=SQL_VALUE)
        self.assertEqual(changed.name,SQL_VALUE)
        self.assertEqual(changed.description,"untouched")
        self.assertIsNotNone(store.get_project(pid))

    def test_memory_dynamic_column_selection_rejects_identifier_injection(self):
        store=MemoryCanonStore(":memory:")
        self.addCleanup(store.close)
        project=store.create_project("synthetic").project_id
        with self.assertRaises(MemoryApplicationError):
            store.list_facts(project,"character OR 1=1 --","0"*32)

    def test_operations_reader_rejects_untrusted_filter(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"tasks.sqlite"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE local_tasks (task_id TEXT)")
            reader=OperationsReader(path)
            with self.assertRaises(OperationsError):
                reader.summary(project_id="abc' OR 1=1 --")

    def test_xml_dtd_and_entity_expansion_rejected(self):
        payloads=[
           b'<!DOCTYPE r [<!ENTITY bomb "EXPANDED">]><r>&bomb;</r>',
           b'<!DOCTYPE r SYSTEM "file:///etc/passwd"><r/>',
           b'<!doctype r><r/>',
           b'<!ENTITY x SYSTEM "file:///tmp/secret"><r/>',
        ]
        for p in payloads:
            with self.subTest(index=payloads.index(p)), self.assertRaises(EpubError):
                _parse_xml(p)

    def test_xml_oversized_input_rejected(self):
        with self.assertRaises(EpubError):
            _parse_xml(b"<x>" + b"A"*(MAX_CHAPTER_BYTES+30001) + b"</x>")

if __name__=="__main__":
    unittest.main(verbosity=2)
