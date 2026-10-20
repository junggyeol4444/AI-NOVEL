"""Opt-in local TXT/MD/EPUB full-text scope and real Qt click checks.

Only temporary synthetic test files and SQLite. No real user files, model,
network, reference persistence or simulated literary PASS.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4
import importlib.util
import os
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory.references.opt_in_file_similarity import (
    compare_explicit_reference_files, OptInSimilarityError,
)

HAVE_GUI = importlib.util.find_spec('PySide6') is not None
if HAVE_GUI:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from ai_novel_factory.desktop.additional_workspaces import SimilarityWorkspace
    from ai_novel_factory.database.episodes import EpisodeStore


class OptInReferenceFileSafetyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.pid = uuid4().hex
        self.original = (
            '가상의 기록관에서 조사자는 잃어버린 문서를 발견했다. '
            '사서는 문서의 날짜와 사건의 순서를 다시 비교했다. '
        ) * 9

    def test_actual_read_all_selected_synthetic_text_files_no_persist(self):
        file1 = self.root / 'first.txt'
        file2 = self.root / 'second.md'
        file1.write_text(self.original, encoding='utf-8')
        file2.write_text('# 가상 사건\n\n완전히 다른 조사자가 문을 열었다. ',
                         encoding='utf-8')
        before = {p.name: p.read_bytes() for p in (file1, file2)}
        result = compare_explicit_reference_files(
            self.pid, 1, self.original, (str(file1), str(file2)))
        self.assertEqual(result.checked_files, 2)
        self.assertIn(result.report.status, ('blocked', 'review'))
        self.assertFalse(result.source_data_persisted)
        self.assertFalse(result.corpus_coverage_certified)
        self.assertFalse(result.manuscript_approved)
        self.assertFalse(result.report.registration_checked)
        self.assertFalse(result.report.publication_approved)
        self.assertTrue(result.report.unexamined)
        self.assertEqual(before, {p.name:p.read_bytes() for p in (file1,file2)})
        self.assertEqual(set(p.name for p in self.root.iterdir()),
                         {'first.txt', 'second.md'})

    def test_different_reference_cannot_claim_full_coverage(self):
        file = self.root / 'different.txt'
        file.write_text(
            '상인들은 항구 주변에서 오래된 물건을 교환했다. ' * 9, encoding='utf-8')
        result = compare_explicit_reference_files(
            self.pid, 1, self.original, (str(file),))
        self.assertFalse(result.report.passed_checked_scope)
        self.assertTrue(result.report.unexamined)
        self.assertFalse(result.corpus_coverage_certified)

    def test_corrupted_second_source_fails_without_partial_success(self):
        valid = self.root / 'valid.txt'
        invalid = self.root / 'broken.txt'
        valid.write_text(self.original, encoding='utf-8')
        invalid.write_bytes(b'bad' + bytes([0]) + b'private')
        before = {p.name:p.read_bytes() for p in (valid,invalid)}
        with self.assertRaises(OptInSimilarityError):
            compare_explicit_reference_files(
                self.pid, 1, self.original, (str(valid),str(invalid)))
        self.assertEqual(before, {p.name:p.read_bytes() for p in (valid,invalid)})

    def test_rejects_unselected_scope_and_invalid_paths(self):
        file = self.root / 'a.txt'
        file.write_text(self.original, encoding='utf-8')
        for paths in ((), (str(file),str(file)), ('relative.txt',)):
            with self.subTest(paths=paths),self.assertRaises(OptInSimilarityError):
                compare_explicit_reference_files(self.pid,1,self.original,paths)

    def test_21st_explicit_reference_is_checked_and_evidence_index_is_global(self):
        sources = []
        for number in range(21):
            path = self.root / f'author-selected-{number:02d}.txt'
            content = (
                self.original if number == 20 else
                f'가상의 먼 항구에서 {number}번째 상인은 지도와 별을 확인했다. ' * 7)
            path.write_text(content, encoding='utf-8')
            sources.append(str(path))
        original_bytes = tuple(Path(p).read_bytes() for p in sources)
        result = compare_explicit_reference_files(
            self.pid, 1, self.original, tuple(sources))
        self.assertEqual(result.checked_files, 21)
        self.assertEqual(len(result.report.reference_ids), 21)
        self.assertIn(result.report.status, ('blocked', 'review'))
        self.assertTrue(result.report.unexamined)
        self.assertFalse(result.report.manuscript_approved)
        self.assertFalse(result.corpus_coverage_certified)
        self.assertTrue(any(e.reference_number == 21
                            for e in result.report.evidence))
        self.assertEqual(original_bytes,
                         tuple(Path(p).read_bytes() for p in sources))

    def test_epub_parser_gets_full_transient_korean_text(self):
        from ai_novel_factory.epub3 import create_epub, Chapter
        from ai_novel_factory.publication_metadata import MetadataDraft
        folder = self.root / 'epub-only'
        folder.mkdir()
        result=create_epub(
            MetadataDraft('reference-fixture','임시 EPUB','임시',
                          '가상의 설정','미스터리',('가상',),'0'),
            [Chapter('1화',self.original)],folder)
        compared=compare_explicit_reference_files(
            self.pid,1,self.original,(str(result.path),))
        self.assertEqual(compared.checked_files,1)
        self.assertFalse(compared.corpus_coverage_certified)


@unittest.skipUnless(HAVE_GUI,'PySide6 not installed')
class ExplicitReferenceGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_button_reads_only_opted_in_selected_local_file(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as root:
            base=Path(root)
            db=base/'synthetic.sqlite'
            story='조사자는 숨겨진 기록을 찾았고 사서에게 두 번째 열쇠의 위치를 설명했다. '*9
            with EpisodeStore(db) as store:
                pid=store.create_project('가상의 참조작 비교').project_id
                store.create_episode(pid,1,plot='임시')
                store.update_episode(pid,1,expected_revision=1,draft=story)
                session=SimpleNamespace(store=store,project_id=pid)
                widget=SimilarityWorkspace(lambda:session)
                self.addCleanup(widget.close)
                widget.refresh()
                ref=base/'author-chosen.txt'
                ref.write_text(story,encoding='utf-8')
                with patch('ai_novel_factory.desktop.additional_workspaces.QFileDialog.getOpenFileNames',
                           return_value=([str(ref)],'')):
                    widget.file_compare_button.click()
                report=widget.status.toPlainText()
                self.assertIn('참고파일 1개 비교',report)
                self.assertIn('NOT_RUN',report)
                self.assertNotIn(str(ref),report)
                self.assertNotIn(story,report)
                self.assertEqual(store.get_episode(pid,1).draft,story)
                old=widget.status.toPlainText()
                with patch('ai_novel_factory.desktop.additional_workspaces.QFileDialog.getOpenFileNames',
                           return_value=([],'')):
                    widget.file_compare_button.click()
                self.assertEqual(widget.status.toPlainText(),old)


if __name__ == '__main__':
    unittest.main()
