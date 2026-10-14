"""Stage 38: deterministic offline overlap detection; privacy and failure gates."""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace, asdict
import io
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from ai_novel_factory.references import (
    analyze_copy_protection, require_copy_safe_draft,
    render_copy_protection, CopyProtectionError, CopyProtectionReport,
    CopyMatchEvidence, REVIEW_MATCH_UNITS, BLOCK_MATCH_UNITS,
    parse_text,
)
from ai_novel_factory.references.copy_protection import (
    MAX_DRAFT_UNITS, MAX_REFERENCE_UNITS, MAX_REFERENCES,
    _first_verified_overlap, _normalize,
)
from ai_novel_factory.references.copy_protection_cli import main as cli_main

CANARY = "PRIVATE_UNPUBLISHED_SOURCE_DO_NOT_ECHO"


def distinct(length: int) -> str:
    # Avoid trivially repetitive test input that could match by coincidence.
    chars = "가나다라마바사아자차카타파하거너더러머버서어저처커터퍼허고노도로모보소오조초코토포호"
    return "".join(chars[(i * i + i * 7) % len(chars)] for i in range(length))


class CopyProtectionUnitTests(unittest.TestCase):
    def test_empty_and_unrelated(self):
        result = analyze_copy_protection("하늘을 나는 새.", ["오늘은 따뜻합니다."])
        self.assertEqual(result.status, "clear")
        self.assertTrue(result.allowed_for_automatic_use)
        self.assertIsNone(result.evidence)

    def test_short_draft_always_clear_if_no_long_match(self):
        self.assertEqual(analyze_copy_protection("작은 꿈.", ["작은 꿈."]).status, "clear")

    def test_exact_48_review(self):
        phrase = distinct(REVIEW_MATCH_UNITS)
        result = analyze_copy_protection("그리고 " + phrase + " 끝", [phrase])
        self.assertEqual(result.status, "review")
        self.assertEqual(result.evidence.minimum_matching_units, 48)
        self.assertFalse(result.allowed_for_automatic_use)

    def test_47_full_short_source_reviewed(self):
        phrase = distinct(REVIEW_MATCH_UNITS - 1)
        report = analyze_copy_protection(phrase, [phrase])
        self.assertEqual(report.status, "review")
        self.assertEqual(report.evidence.minimum_matching_units, 47)

    def test_47_passage_of_longer_source_not_automatically_flagged(self):
        phrase = distinct(REVIEW_MATCH_UNITS - 1)
        self.assertEqual(analyze_copy_protection(phrase, [phrase + "다른원문"]).status, "clear")

    def test_full_short_work_16_units_is_review(self):
        phrase = distinct(16)
        self.assertEqual(analyze_copy_protection(phrase, [phrase]).status, "review")

    def test_too_short_common_fragment_no_auto_flag(self):
        phrase = distinct(15)
        self.assertEqual(analyze_copy_protection(phrase, [phrase]).status, "clear")

    def test_exact_96_block(self):
        phrase = distinct(BLOCK_MATCH_UNITS)
        report = analyze_copy_protection(phrase, [phrase])
        self.assertEqual(report.status, "blocked")
        self.assertEqual(report.evidence.minimum_matching_units, 96)

    def test_95_is_review_not_block(self):
        phrase = distinct(BLOCK_MATCH_UNITS - 1)
        self.assertEqual(analyze_copy_protection(phrase, [phrase]).status, "review")

    def test_priority_block_over_review(self):
        phrase = distinct(110)
        report = analyze_copy_protection(phrase, [phrase[:48], phrase])
        self.assertEqual(report.status, "blocked")
        self.assertEqual(report.evidence.reference_number, 2)

    def test_reference_order(self):
        phrase = distinct(110)
        self.assertEqual(analyze_copy_protection(phrase, [phrase, phrase]).evidence.reference_number, 1)

    def test_normalize_korean_whitespace_and_punctuation(self):
        phrase = distinct(105)
        spaced = "  ·  ".join(phrase)
        report = analyze_copy_protection(spaced, [phrase])
        self.assertEqual(report.status, "blocked")
        self.assertEqual(report.draft_units, len(phrase))

    def test_normalize_case_and_nfkc(self):
        self.assertEqual(_normalize("ＡBC　ＤＥＦ １２３"), "abcdef123")
        self.assertEqual(analyze_copy_protection("A" * 96, ["ａ" * 96]).status, "blocked")

    def test_punctuation_only_draft_rejected(self):
        with self.assertRaises(CopyProtectionError):
            analyze_copy_protection(". ... \n --", ["유효한 원문"])

    def test_empty_reference_rejected(self):
        with self.assertRaises(CopyProtectionError):
            analyze_copy_protection("원고", ["  !!  "])

    def test_empty_references_fail_closed(self):
        with self.assertRaises(CopyProtectionError):
            analyze_copy_protection("원고", [])

    def test_invalid_reference_container(self):
        for x in ("source", {"one": "source"}, None, (v for v in ["source"])):
            with self.subTest(type=type(x)):
                with self.assertRaises(CopyProtectionError):
                    analyze_copy_protection("원고", x)

    def test_over_20_references_rejected(self):
        with self.assertRaises(CopyProtectionError):
            analyze_copy_protection("원고", ["원문"] * (MAX_REFERENCES + 1))

    def test_invalid_draft_type(self):
        for value in (None, b"bytes", 123, False, ["안녕"]):
            with self.subTest(value=value):
                with self.assertRaises(CopyProtectionError):
                    analyze_copy_protection(value, ["참고 문장"])

    def test_invalid_source_type(self):
        for value in (None, 42, b"bytes", False, ["text"]):
            with self.subTest(value=value):
                with self.assertRaises(CopyProtectionError):
                    analyze_copy_protection("원고", [value])

    def test_draft_units_limit(self):
        with self.assertRaises(CopyProtectionError):
            analyze_copy_protection("가" * (MAX_DRAFT_UNITS + 1), ["참고 문장"])

    def test_reference_units_limit(self):
        with self.assertRaises(CopyProtectionError):
            analyze_copy_protection("원고", ["가" * (MAX_REFERENCE_UNITS + 1)])

    def test_raw_draft_limit(self):
        with self.assertRaises(CopyProtectionError):
            analyze_copy_protection(" " * 400001 + "a", ["a"])

    def test_raw_reference_limit(self):
        with self.assertRaises(CopyProtectionError):
            analyze_copy_protection("원고", ["." * 1000001 + "참고"])

    def test_parsed_reference_accepted(self):
        phrase = distinct(105)
        reference = parse_text(phrase)
        self.assertEqual(analyze_copy_protection(phrase, [reference]).status, "blocked")

    def test_mixed_reference_inputs(self):
        phrase = distinct(105)
        self.assertEqual(analyze_copy_protection(phrase, [parse_text("기타 내용"), phrase]).evidence.reference_number, 2)

    def test_multi_paragraph_overlap(self):
        phrase = distinct(105)
        reference = phrase[:60] + "\n\n" + phrase[60:]
        draft = phrase[:50] + "\n" + phrase[50:]
        self.assertEqual(analyze_copy_protection(draft, [reference]).status, "blocked")

    def test_before_after_noise_offset(self):
        phrase = distinct(110)
        report = analyze_copy_protection("오리지널" + phrase + "새로운결말", [phrase])
        self.assertEqual(report.status, "blocked")
        self.assertEqual(report.evidence.draft_normalized_offset, len("오리지널"))

    def test_similar_but_changed_contiguous_sections(self):
        phrase = distinct(110)
        changed = phrase[:45] + "너" + phrase[46:89] + "버" + phrase[90:]
        # Do not present this as a semantic similarity detector: changing
        # characters can break the long contiguous overlap.
        report = analyze_copy_protection(changed, [phrase])
        self.assertNotEqual(report.status, "blocked")

    def test_safe_gate_rejects_review(self):
        phrase = distinct(48)
        with self.assertRaises(CopyProtectionError) as ctx:
            require_copy_safe_draft(phrase, [phrase])
        self.assertNotIn(phrase, str(ctx.exception))

    def test_safe_gate_rejects_block(self):
        phrase = distinct(100)
        with self.assertRaises(CopyProtectionError):
            require_copy_safe_draft(phrase, [phrase])

    def test_safe_gate_returns_clear(self):
        self.assertTrue(require_copy_safe_draft("새로운 문장", ["전혀 상관없는 소설"]).allowed_for_automatic_use)

    def test_report_does_not_retain_original(self):
        phrase = CANARY + distinct(110)
        report = analyze_copy_protection(phrase, [phrase])
        self.assertNotIn(CANARY, repr(report))
        self.assertNotIn(CANARY, str(asdict(report)))
        self.assertNotIn(CANARY, render_copy_protection(report))
        self.assertNotIn(phrase[:50], repr(report))

    def test_fixed_safe_rendering(self):
        report = analyze_copy_protection("가" * 105, ["가" * 105])
        shown = render_copy_protection(report)
        self.assertIn("blocked", shown)
        self.assertIn("96", shown)
        self.assertNotIn("가" * 10, shown)

    def test_clear_rendering(self):
        result = render_copy_protection(analyze_copy_protection("작은 구름", ["큰 바다"]))
        self.assertIn("clear", result)
        self.assertNotIn("일치 최소", result)

    def test_render_invalid(self):
        with self.assertRaises(CopyProtectionError):
            render_copy_protection(CopyProtectionReport("hacked", 1, 30, None))
        with self.assertRaises(CopyProtectionError):
            render_copy_protection(CopyProtectionReport("clear", 1, 10, CopyMatchEvidence(1, 0, 48)))
        with self.assertRaises(CopyProtectionError):
            render_copy_protection(CopyProtectionReport("blocked", 1, 100, CopyMatchEvidence(1, -1, 96)))

    def test_hash_collision_only_a_hint(self):
        # Even a forced hash-index collision cannot trigger false positives.
        with patch("builtins.hash", return_value=42):
            hit = _first_verified_overlap("가" * 96, ("나" * 96,), 48)
        self.assertIsNone(hit)

    def test_offline_no_network(self):
        phrase = distinct(115)
        with patch.object(socket, "create_connection", side_effect=AssertionError("NETWORK")), \
             patch.object(socket.socket, "connect", side_effect=AssertionError("NETWORK")):
            report = analyze_copy_protection(phrase, [phrase])
        self.assertEqual(report.status, "blocked")

    def test_repeatability(self):
        phrase = distinct(100)
        self.assertEqual(analyze_copy_protection(phrase, [phrase]), analyze_copy_protection(phrase, [phrase]))

    def test_empty_and_low_evidence_words(self):
        self.assertEqual(analyze_copy_protection("!" * 100 + "처음", ["처음"] ).status, "clear")

    def test_unrelated_long_text(self):
        self.assertEqual(analyze_copy_protection("a" * 4000, ["b" * 4000]).status, "clear")


class CopyProtectionCliTests(unittest.TestCase):
    def setUp(self):
        ctx = tempfile.TemporaryDirectory()
        self.addCleanup(ctx.cleanup)
        self.root = Path(ctx.name)
        self.draft = self.root / "new.txt"
        self.reference = self.root / ("hidden_" + CANARY + ".txt")

    def run_cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli_main(list(args))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_cli_clear(self):
        self.draft.write_text("완전히 새로운 내용", encoding="utf8")
        self.reference.write_text("다른 이야기", encoding="utf8")
        code, out, err = self.run_cli("--draft", str(self.draft), "--reference", str(self.reference))
        self.assertEqual(code, 0)
        self.assertIn("clear", out)
        self.assertEqual(err, "")

    def test_cli_block(self):
        paragraph = distinct(112)
        self.draft.write_text(paragraph, encoding="utf8")
        self.reference.write_text(paragraph, encoding="utf8")
        code, out, err = self.run_cli("--draft", str(self.draft), "--reference", str(self.reference))
        self.assertEqual(code, 1)
        self.assertIn("blocked", out)
        self.assertEqual(err, "")
        self.assertNotIn(CANARY, out)

    def test_cli_review(self):
        paragraph = distinct(54)
        self.draft.write_text(paragraph, encoding="utf8")
        self.reference.write_text(paragraph, encoding="utf8")
        code, out, err = self.run_cli("--draft", str(self.draft), "--reference", str(self.reference))
        self.assertEqual(code, 1)
        self.assertIn("review", out)
        self.assertEqual(err, "")

    def test_cli_missing_reference_fails_closed(self):
        self.draft.write_text("원고", encoding="utf8")
        code, out, err = self.run_cli("--draft", str(self.draft), "--reference", str(self.reference))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertNotIn(CANARY, err)

    def test_cli_symlink_rejected(self):
        self.draft.write_text("원고", encoding="utf8")
        self.reference.symlink_to(self.draft)
        code, _, err = self.run_cli("--draft", str(self.draft), "--reference", str(self.reference))
        self.assertEqual(code, 2)
        self.assertNotIn(CANARY, err)

    def test_cli_no_extra_storage_or_original_content_leak(self):
        phrase = CANARY + distinct(110)
        self.draft.write_text(phrase, encoding="utf8")
        self.reference.write_text(phrase, encoding="utf8")
        before = {p.name for p in self.root.iterdir()}
        code, out, _ = self.run_cli("--draft", str(self.draft), "--reference", str(self.reference))
        self.assertEqual(code, 1)
        self.assertEqual(before, {p.name for p in self.root.iterdir()})
        self.assertNotIn(CANARY, out)

    def test_cli_markdown(self):
        phrase = distinct(110)
        draft_md = self.root / "draft.md"
        ref_md = self.root / "ref.md"
        draft_md.write_text("# 1화\n\n" + phrase, encoding="utf8")
        ref_md.write_text("# 2화\n\n" + phrase, encoding="utf8")
        code, out, _ = self.run_cli("--draft", str(draft_md), "--reference", str(ref_md))
        self.assertEqual(code, 1)
        self.assertIn("blocked", out)

    def test_cli_unsupported_file(self):
        draft_pdf = self.root / "draft.zip"
        draft_pdf.write_bytes(b"CONTENT")
        self.reference.write_text("원문", encoding="utf8")
        code, _, _ = self.run_cli("--draft", str(draft_pdf), "--reference", str(self.reference))
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
