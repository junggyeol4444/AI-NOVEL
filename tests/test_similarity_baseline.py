"""Stage 39 offline paragraph similarity regression & privacy tests."""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
from dataclasses import asdict, replace
import io
import socket
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory.references import (
    SimilarityCheckError, SimilarityBaselineReport, ParagraphSimilarityEvidence,
    analyze_similarity_baseline, require_similarity_safe_draft,
    render_similarity_baseline, parse_text,
)
from ai_novel_factory.references.similarity_baseline import (
    SHINGLE_UNITS, MIN_PARAGRAPH_UNITS, MAX_DRAFT_PARAGRAPHS,
    MAX_REFERENCE_PARAGRAPHS, MAX_INDEX_ENTRIES, MAX_EVIDENCE, _shingles,
)
from ai_novel_factory.references.similarity_cli import main as similarity_main

CANARY = "CONFIDENTIAL_AUTHOR_DRAFT_NEVER_ECHO"
TEXT_A = "어두운 골목 끝에서 길을 잃은 사람이 오래된 지도를 발견하고 집으로 돌아갈 길을 찾아냈다."
TEXT_B = "아침 햇살이 창가를 지나가자 작은 새들이 노래했고 사람들은 공원에서 운동을 시작했다."
TEXT_C = "별빛이 쏟아지는 숲에서 여행자는 돌계단을 지나 먼 도시의 불빛을 향해 계속 걸어갔다."


class SimilarityBaselineUnitTests(unittest.TestCase):
    def test_no_match_clear(self):
        r = analyze_similarity_baseline(TEXT_A, [TEXT_B])
        self.assertEqual((r.status, r.exact_overlap_status), ("clear", "clear"))
        self.assertTrue(r.allowed_for_automatic_use)
        self.assertEqual(r.similar_paragraphs, 0)

    def test_exact_long_blocked(self):
        passage = (TEXT_A + TEXT_C) * 2
        r = analyze_similarity_baseline(passage, [passage])
        self.assertEqual(r.status, "blocked")
        self.assertEqual(r.exact_overlap_status, "blocked")

    def test_exact_48_review(self):
        r = analyze_similarity_baseline("가" * 48, ["가" * 48])
        self.assertEqual(r.status, "review")
        self.assertEqual(r.exact_overlap_status, "review")

    def test_near_copy_typo_review(self):
        mutated = TEXT_A.replace("발견하고", "발견하여")
        r = analyze_similarity_baseline(mutated, [TEXT_A])
        self.assertEqual(r.status, "review")
        self.assertEqual(r.exact_overlap_status, "clear")
        self.assertEqual(r.similar_paragraphs, 1)

    def test_near_copy_insert_word_review(self):
        mutated = TEXT_A.replace("길을 잃은", "깊은 밤에 길을 잃은")
        self.assertEqual(analyze_similarity_baseline(mutated, [TEXT_A]).status, "review")

    def test_punctuation_differences_normalized(self):
        ref = (TEXT_A + TEXT_C) * 2
        altered = ref.replace(" ", "  ").replace(".", "!")
        self.assertEqual(analyze_similarity_baseline(altered, [ref]).status, "blocked")

    def test_case_nfkc(self):
        base = "ABCdefghij0123456789" * 5
        self.assertEqual(analyze_similarity_baseline(base, [base.lower()]).status, "blocked")

    def test_unrelated_paragraphs_not_flagged(self):
        r = analyze_similarity_baseline(TEXT_A + "\n\n" + TEXT_B, [TEXT_C])
        self.assertEqual(r.status, "clear")
        self.assertEqual(r.draft_paragraphs_checked, 2)

    def test_short_draft_is_inconclusive(self):
        r = analyze_similarity_baseline("짧은 문장", [TEXT_A])
        self.assertEqual(r.status, "inconclusive")
        self.assertFalse(r.allowed_for_automatic_use)

    def test_short_reference_is_inconclusive(self):
        r = analyze_similarity_baseline(TEXT_A, ["짧은 참고"])
        self.assertEqual(r.status, "inconclusive")

    def test_short_full_reference_goes_to_review(self):
        short = "가나다라마바사아자차카타파하거너더러머버서어저처"
        r = analyze_similarity_baseline(short, [short])
        self.assertEqual(r.status, "review")

    def test_short_paragraph_skipped(self):
        r = analyze_similarity_baseline("짧음\n\n" + TEXT_A, [TEXT_B])
        self.assertEqual(r.draft_paragraphs_checked, 1)

    def test_paragraph_numbers_preserved(self):
        r = analyze_similarity_baseline("짧음\n\n" + TEXT_A.replace("발견하고", "발견하여"),
                                        ["짧음\n\n" + TEXT_A])
        self.assertEqual(r.evidence[0].draft_paragraph_number, 2)
        self.assertEqual(r.evidence[0].reference_paragraph_number, 2)

    def test_multiple_sources_report_ordinal_only(self):
        r = analyze_similarity_baseline(TEXT_A.replace("발견하고", "발견하여"), [TEXT_B, TEXT_A])
        self.assertEqual(r.evidence[0].reference_number, 2)

    def test_multiple_draft_paragraphs(self):
        a = TEXT_A.replace("발견하고", "발견하여")
        b = TEXT_B.replace("새들이", "새들이 다시")
        r = analyze_similarity_baseline(a + "\n\n" + b, [TEXT_A + "\n\n" + TEXT_B])
        self.assertEqual(r.similar_paragraphs, 2)
        self.assertEqual([e.draft_paragraph_number for e in r.evidence], [1, 2])

    def test_raw_doc_without_blank_line_is_one_paragraph(self):
        r = analyze_similarity_baseline(TEXT_A + "\n" + TEXT_B, [TEXT_C])
        self.assertEqual(r.draft_paragraphs_checked, 1)

    def test_parsed_markdown_excludes_heading_code(self):
        draft = parse_text("# 제목을 빼고 검사를 진행합니다\n\n" + TEXT_A + "\n\n```\n" + TEXT_B + "\n```",
                           format="markdown")
        r = analyze_similarity_baseline(draft, [parse_text(TEXT_C)])
        self.assertEqual(r.draft_paragraphs_checked, 1)

    def test_parse_doc_in_reference(self):
        ref = parse_text("# 제목은 제외\n\n" + TEXT_A, format="markdown")
        r = analyze_similarity_baseline(TEXT_A.replace("발견하고", "발견하여"), [ref])
        self.assertEqual(r.similar_paragraphs, 1)

    def test_normalized_shingles(self):
        self.assertEqual(_shingles("가나다라마바"), frozenset({"가나다라마", "나다라마바"}))
        self.assertEqual(SHINGLE_UNITS, 5)
        self.assertEqual(MIN_PARAGRAPH_UNITS, 24)

    def test_short_shingles_empty(self):
        self.assertEqual(_shingles("abc"), frozenset())

    def test_report_contains_no_original(self):
        secret = CANARY + TEXT_A
        r = analyze_similarity_baseline(secret.replace("발견하고", "발견하여"), [secret])
        self.assertNotIn(CANARY, repr(r))
        self.assertNotIn(CANARY, str(asdict(r)))
        self.assertNotIn(CANARY, render_similarity_baseline(r))

    def test_no_matches_return_no_evidence(self):
        r = analyze_similarity_baseline(TEXT_A, [TEXT_B])
        self.assertEqual(r.evidence, ())

    def test_highest_score_bounds(self):
        r = analyze_similarity_baseline(TEXT_A, [TEXT_A.replace("발견하고", "발견하여")])
        self.assertTrue(0 <= r.highest_jaccard <= 1)
        self.assertTrue(0 <= r.highest_containment <= 1)

    def test_evidence_score_rounded(self):
        r = analyze_similarity_baseline(TEXT_A.replace("발견하고", "발견하여"), [TEXT_A])
        self.assertEqual(r.evidence[0].jaccard, round(r.evidence[0].jaccard, 4))

    def test_require_safe_allows_distinct(self):
        self.assertTrue(require_similarity_safe_draft(TEXT_A, [TEXT_B]).allowed_for_automatic_use)

    def test_require_safe_rejects_review(self):
        with self.assertRaises(SimilarityCheckError):
            require_similarity_safe_draft(TEXT_A.replace("발견하고", "발견하여"), [TEXT_A])

    def test_require_safe_rejects_inconclusive(self):
        with self.assertRaises(SimilarityCheckError):
            require_similarity_safe_draft("짧은", [TEXT_A])

    def test_require_safe_rejects_blocked(self):
        with self.assertRaises(SimilarityCheckError):
            require_similarity_safe_draft(TEXT_A * 4, [TEXT_A * 4])

    def test_empty_draft_rejected(self):
        with self.assertRaises(SimilarityCheckError):
            analyze_similarity_baseline("", [TEXT_A])

    def test_empty_reference_rejected(self):
        with self.assertRaises(SimilarityCheckError):
            analyze_similarity_baseline(TEXT_A, [" "])

    def test_empty_ref_list_rejected(self):
        with self.assertRaises(SimilarityCheckError):
            analyze_similarity_baseline(TEXT_A, [])

    def test_bad_draft_types_rejected(self):
        for bad in (None, 7, False, [TEXT_A], b"text"):
            with self.subTest(value=type(bad).__name__):
                with self.assertRaises(SimilarityCheckError):
                    analyze_similarity_baseline(bad, [TEXT_A])

    def test_bad_ref_types_rejected(self):
        for bad in (None, 7, False, [TEXT_A], b"text"):
            with self.subTest(value=type(bad).__name__):
                with self.assertRaises(SimilarityCheckError):
                    analyze_similarity_baseline(TEXT_A, [bad])

    def test_bad_reference_containers(self):
        for bad in ("one", set([TEXT_A]), {"a": TEXT_A}, (v for v in [TEXT_A])):
            with self.subTest(type=str(type(bad))):
                with self.assertRaises(SimilarityCheckError):
                    analyze_similarity_baseline(TEXT_A, bad)

    def test_more_than_twenty_sources_rejected(self):
        with self.assertRaises(SimilarityCheckError):
            analyze_similarity_baseline(TEXT_A, [TEXT_B] * 21)

    def test_raw_input_size_rejected(self):
        with self.assertRaises(SimilarityCheckError):
            analyze_similarity_baseline("가" * 400001, [TEXT_A])

    def test_total_source_size_rejected(self):
        with self.assertRaises(SimilarityCheckError):
            analyze_similarity_baseline(TEXT_A, ["가" * 500001])

    def test_paragraph_limit_draft(self):
        text = ("짧음\n\n" * MAX_DRAFT_PARAGRAPHS) + TEXT_A
        with self.assertRaises(SimilarityCheckError):
            analyze_similarity_baseline(text, [TEXT_B])

    def test_paragraph_limit_references(self):
        text = ("짧음\n\n" * MAX_REFERENCE_PARAGRAPHS) + TEXT_B
        with self.assertRaises(SimilarityCheckError):
            analyze_similarity_baseline(TEXT_A, [text])

    def test_scores_no_nan(self):
        r = analyze_similarity_baseline(TEXT_A, [TEXT_B])
        with self.assertRaises(SimilarityCheckError):
            render_similarity_baseline(replace(r, highest_jaccard=float("nan")))

    def test_forged_report_rejected(self):
        with self.assertRaises(SimilarityCheckError):
            render_similarity_baseline("not a report")

    def test_forged_negative_count_rejected(self):
        r = analyze_similarity_baseline(TEXT_A, [TEXT_B])
        with self.assertRaises(SimilarityCheckError):
            render_similarity_baseline(replace(r, similar_paragraphs=-1))

    def test_forged_evidence_rejected(self):
        r = analyze_similarity_baseline(TEXT_A, [TEXT_B])
        with self.assertRaises(SimilarityCheckError):
            render_similarity_baseline(replace(r, evidence=("malicious",)))

    def test_no_network_calls(self):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), \
             patch.object(socket, "create_connection", side_effect=AssertionError("network forbidden")):
            r = analyze_similarity_baseline(TEXT_A, [TEXT_B])
        self.assertEqual(r.status, "clear")

    def test_evidence_cap(self):
        altered = TEXT_A.replace("발견하고", "발견하여")
        draft = "\n\n".join([altered] * 20)
        r = analyze_similarity_baseline(draft, [TEXT_A])
        self.assertEqual(r.similar_paragraphs, 20)
        self.assertEqual(len(r.evidence), MAX_EVIDENCE)

    def test_large_repetitive_workload_fails_closed(self):
        # Each query shingle occurs in many paragraphs. Never silently skip
        # common shingles and mistakenly classify an unsafe document clear.
        paragraph = "abcdefghijklmnopqrstuvwxyz" * 2
        source = "\n\n".join([paragraph] * 900)
        draft = "\n\n".join([paragraph] * 180)
        with self.assertRaises(SimilarityCheckError):
            analyze_similarity_baseline(draft, [source])

    def test_no_database_writes(self):
        import sqlite3
        with patch.object(sqlite3, "connect", side_effect=AssertionError("database not needed")):
            self.assertTrue(analyze_similarity_baseline(TEXT_A, [TEXT_B]).allowed_for_automatic_use)

    def test_inputs_unchanged(self):
        draft = TEXT_A
        refs = [TEXT_B]
        analyze_similarity_baseline(draft, refs)
        self.assertEqual(draft, TEXT_A)
        self.assertEqual(refs, [TEXT_B])


class SimilarityBaselineCLITests(unittest.TestCase):
    def test_cli_clear_and_no_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            draft = path / "draft_secret.txt"
            source = path / "source_secret.txt"
            draft.write_text(TEXT_A, encoding="utf-8")
            source.write_text(TEXT_B, encoding="utf-8")
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = similarity_main(["--draft", str(draft), "--reference", str(source)])
            self.assertEqual(code, 0)
            self.assertIn("clear", stdout.getvalue())
            self.assertNotIn(str(path), stdout.getvalue()+stderr.getvalue())
            self.assertNotIn("source_secret", stdout.getvalue()+stderr.getvalue())
            self.assertNotIn(TEXT_A, stdout.getvalue()+stderr.getvalue())

    def test_cli_review(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            draft, reference = path / "d.txt", path / "r.txt"
            draft.write_text(TEXT_A.replace("발견하고", "발견하여"), encoding="utf-8")
            reference.write_text(TEXT_A, encoding="utf-8")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = similarity_main(["--draft", str(draft), "--reference", str(reference)])
            self.assertEqual(code, 1)
            self.assertIn("review", stdout.getvalue())

    def test_cli_unsupported_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            draft, source = path / "manuscript.epub", path / "novel.txt"
            draft.write_text(TEXT_A)
            source.write_text(TEXT_B)
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = similarity_main(["--draft", str(draft), "--reference", str(source)])
            self.assertEqual(code, 2)
            self.assertNotIn(str(draft), stderr.getvalue())

    def test_cli_missing_path_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = similarity_main(["--draft", folder + "/missing.txt", "--reference", folder + "/r.txt"])
            self.assertEqual(code, 2)
            self.assertNotIn(folder, stderr.getvalue())

    def test_cli_too_many_references_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = similarity_main(["--draft", folder + "/missing.txt", "--reference"] + ["x.txt"] * 21)
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
