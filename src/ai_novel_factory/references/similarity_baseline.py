"""Stage 39: offline, conservative paragraph-level lexical similarity baseline.

Checks *only* transient source texts. Returns fixed categories and numeric
positions/scores, never excerpts, shingles, hashes, author names or paths.
Not a semantic/plagiarism verdict. Human review is needed for review/blocked.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re
from typing import Sequence

from .copy_protection import (
    MAX_REFERENCES, MAX_RAW_DRAFT_CHARS, MAX_RAW_REFERENCE_CHARS,
    MAX_DRAFT_UNITS, MAX_REFERENCE_UNITS,
    CopyProtectionError, _normalize, analyze_copy_protection,
)
from .plaintext_parser import ParsedReference

SHINGLE_UNITS = 5
MIN_PARAGRAPH_UNITS = 24
JACCARD_REVIEW = 0.70
CONTAINMENT_REVIEW = 0.80
MIN_CONTAINMENT_JACCARD = 0.40
MAX_DRAFT_PARAGRAPHS = 500
MAX_REFERENCE_PARAGRAPHS = 1_000
MAX_INDEX_ENTRIES = 300_000
MAX_EVIDENCE = 12
MAX_SEARCH_POSTINGS = 3_000_000  # fail closed on adversarial repetitive documents
_BLANK = re.compile(r"\n[ \t]*\n+")
_BODY_KINDS = frozenset({"paragraph", "table"})


class SimilarityCheckError(CopyProtectionError):
    """Generic, fixed-message error; do not leak user documents or paths."""


@dataclass(frozen=True)
class ParagraphSimilarityEvidence:
    reference_number: int
    draft_paragraph_number: int
    reference_paragraph_number: int
    jaccard: float
    containment: float


@dataclass(frozen=True)
class SimilarityBaselineReport:
    status: str  # clear/review/blocked/inconclusive
    exact_overlap_status: str
    references_checked: int
    draft_paragraphs_checked: int
    reference_paragraphs_checked: int
    similar_paragraphs: int
    highest_jaccard: float
    highest_containment: float
    evidence: tuple[ParagraphSimilarityEvidence, ...]

    @property
    def allowed_for_automatic_use(self) -> bool:
        return self.status == "clear"


def _raw(value: str | ParsedReference) -> str:
    if isinstance(value, ParsedReference):
        return value.text
    if type(value) is str:
        return value
    raise SimilarityCheckError("유사성 검사 입력 형식이 올바르지 않습니다.")


def _paragraphs(value: str | ParsedReference) -> list[str]:
    if isinstance(value, ParsedReference):
        parts = (block.text for block in value.blocks if block.kind in _BODY_KINDS)
    else:
        parts = (value,)
    result: list[str] = []
    for part in parts:
        normalized = part.replace("\r\n", "\n").replace("\r", "\n")
        result.extend(p.strip() for p in _BLANK.split(normalized) if p.strip())
    return result


def _shingles(text: str) -> frozenset[str]:
    return frozenset(text[i:i + SHINGLE_UNITS]
                     for i in range(len(text) - SHINGLE_UNITS + 1))


def _validate(
    draft: str | ParsedReference,
    references: Sequence[str | ParsedReference],
) -> tuple[str, tuple[str, ...]]:
    if type(references) not in (list, tuple) or not 1 <= len(references) <= MAX_REFERENCES:
        raise SimilarityCheckError("유사성 검사에는 1~100개의 참고 원문이 필요합니다.")
    original_draft = _raw(draft)
    if len(original_draft) > MAX_RAW_DRAFT_CHARS or not 1 <= len(_normalize(original_draft)) <= MAX_DRAFT_UNITS:
        raise SimilarityCheckError("검사 원고가 크기 제한을 초과했거나 비어 있습니다.")
    sources: list[str] = []
    raw_total = 0
    units_total = 0
    for ref in references:
        source = _raw(ref)
        raw_total += len(source)
        units_total += len(_normalize(source))
        if raw_total > MAX_RAW_REFERENCE_CHARS or units_total > MAX_REFERENCE_UNITS:
            raise SimilarityCheckError("참고 원문의 총크기 제한을 초과했습니다.")
        if not _normalize(source):
            raise SimilarityCheckError("비어 있는 참고 원문은 검사할 수 없습니다.")
        sources.append(source)
    return original_draft, tuple(sources)


def analyze_similarity_baseline(
    draft: str | ParsedReference,
    references: list[str | ParsedReference] | tuple[str | ParsedReference, ...],
) -> SimilarityBaselineReport:
    """Compare lexical 5-character shingles of paragraphs; fail closed.

    Normalization strips punctuation/whitespace and applies NFKC+casefold.
    Whole-source direct-overlap stage 38 gate is composed first; a blocked
    direct match always wins. No original passages or ngrams escape in reports.
    Candidate paragraphs shorter than 24 normalized characters are excluded.
    If there is no comparable material, status is 'inconclusive', not 'clear'.
    """
    draft_text, source_texts = _validate(draft, references)
    direct = analyze_copy_protection(draft_text, list(source_texts))
    draft_parts = _paragraphs(draft)
    if len(draft_parts) > MAX_DRAFT_PARAGRAPHS:
        raise SimilarityCheckError("원고 문단 개수 제한을 초과했습니다.")
    reference_parts: list[tuple[int, int, str]] = []
    for ref_no, ref in enumerate(references, 1):
        parts = _paragraphs(ref)
        for para_no, paragraph in enumerate(parts, 1):
            reference_parts.append((ref_no, para_no, paragraph))
            if len(reference_parts) > MAX_REFERENCE_PARAGRAPHS:
                raise SimilarityCheckError("참고 문단 총개수 제한을 초과했습니다.")

    index: dict[str, list[int]] = defaultdict(list)
    sources: list[tuple[int, int, frozenset[str]]] = []
    index_entries = 0
    for ref_no, para_no, paragraph in reference_parts:
        units = _normalize(paragraph)
        if len(units) < MIN_PARAGRAPH_UNITS:
            continue
        shingles = _shingles(units)
        index_entries += len(shingles)
        if index_entries > MAX_INDEX_ENTRIES:
            raise SimilarityCheckError("참고 문단 비교 자료가 허용량을 초과했습니다.")
        position = len(sources)
        sources.append((ref_no, para_no, shingles))
        for shingle in shingles:
            index[shingle].append(position)

    eligible = 0
    matches = 0
    top_jaccard = 0.0
    top_containment = 0.0
    evidence: list[ParagraphSimilarityEvidence] = []
    postings_scanned = 0
    for para_no, paragraph in enumerate(draft_parts, 1):
        units = _normalize(paragraph)
        if len(units) < MIN_PARAGRAPH_UNITS:
            continue
        eligible += 1
        draft_shingles = _shingles(units)
        overlaps: dict[int, int] = defaultdict(int)
        for shingle in draft_shingles:
            positions = index.get(shingle, ())
            postings_scanned += len(positions)
            if postings_scanned > MAX_SEARCH_POSTINGS:
                raise SimilarityCheckError("문단 유사성 검색 작업량 제한을 초과했습니다.")
            for pos in positions:
                overlaps[pos] += 1
        best: tuple[float, float, int] | None = None
        for pos, intersection in overlaps.items():
            ref_no, reference_para_no, ref_shingles = sources[pos]
            jaccard = intersection / (len(draft_shingles) + len(ref_shingles) - intersection)
            containment = intersection / len(draft_shingles)
            top_jaccard = max(top_jaccard, jaccard)
            top_containment = max(top_containment, containment)
            # A high-containment match must not be hidden by another candidate
            # with a slightly higher Jaccard score but no review threshold.
            eligible_match = jaccard >= JACCARD_REVIEW or (
                containment >= CONTAINMENT_REVIEW and jaccard >= MIN_CONTAINMENT_JACCARD
            )
            if eligible_match and (best is None or (jaccard, containment, -ref_no, -reference_para_no) > (
                best[0], best[1], -sources[best[2]][0], -sources[best[2]][1]
            )):
                best = jaccard, containment, pos
        if best is not None:
            jaccard, containment, pos = best
            matches += 1
            if len(evidence) < MAX_EVIDENCE:
                ref_no, ref_para_no, _ = sources[pos]
                evidence.append(ParagraphSimilarityEvidence(
                    reference_number=ref_no,
                    draft_paragraph_number=para_no,
                    reference_paragraph_number=ref_para_no,
                    jaccard=round(jaccard, 4),
                    containment=round(containment, 4),
                ))

    if direct.status == "blocked":
        status = "blocked"
    elif direct.status == "review" or matches:
        status = "review"
    elif not eligible or not sources:
        status = "inconclusive"
    else:
        status = "clear"
    return SimilarityBaselineReport(
        status=status,
        exact_overlap_status=direct.status,
        references_checked=len(references),
        draft_paragraphs_checked=eligible,
        reference_paragraphs_checked=len(sources),
        similar_paragraphs=matches,
        highest_jaccard=round(top_jaccard, 4),
        highest_containment=round(top_containment, 4),
        evidence=tuple(evidence),
    )


def require_similarity_safe_draft(
    draft: str | ParsedReference,
    references: list[str | ParsedReference] | tuple[str | ParsedReference, ...],
) -> SimilarityBaselineReport:
    """Allow automatic use only after both baseline checks report clear."""
    report = analyze_similarity_baseline(draft, references)
    if not report.allowed_for_automatic_use:
        raise SimilarityCheckError("유사성 검사 결과 검토가 필요하거나 검사 자료가 부족합니다.")
    return report


def render_similarity_baseline(report: SimilarityBaselineReport) -> str:
    """Numeric-only CLI rendering. Reject forged/corrupt reports."""
    if type(report) is not SimilarityBaselineReport or report.status not in {
        "clear", "review", "blocked", "inconclusive"
    } or report.exact_overlap_status not in {"clear", "review", "blocked"}:
        raise SimilarityCheckError("유사성 분석 결과가 올바르지 않습니다.")
    numeric = (report.references_checked, report.draft_paragraphs_checked,
               report.reference_paragraphs_checked, report.similar_paragraphs)
    if any(type(n) is not int or n < 0 for n in numeric) or not 1 <= report.references_checked <= MAX_REFERENCES \
        or report.similar_paragraphs > report.draft_paragraphs_checked \
        or len(report.evidence) > MAX_EVIDENCE:
        raise SimilarityCheckError("유사성 분석 수치가 올바르지 않습니다.")
    if any(type(score) is not float or not 0 <= score <= 1
           for score in (report.highest_jaccard, report.highest_containment)):
        raise SimilarityCheckError("유사성 분석 지표가 올바르지 않습니다.")
    for item in report.evidence:
        if type(item) is not ParagraphSimilarityEvidence or not (
            1 <= item.reference_number <= report.references_checked
            and 1 <= item.draft_paragraph_number <= MAX_DRAFT_PARAGRAPHS
            and 1 <= item.reference_paragraph_number <= MAX_REFERENCE_PARAGRAPHS
            and 0 <= item.jaccard <= 1 and 0 <= item.containment <= 1
        ):
            raise SimilarityCheckError("유사성 비교 근거가 올바르지 않습니다.")
    lines = [
        f"유사성 기준선: {report.status} (원문 연속 일치: {report.exact_overlap_status})",
        f"참고 입력 수: {report.references_checked}",
        f"비교 문단 수: 원고 {report.draft_paragraphs_checked}, 참고 {report.reference_paragraphs_checked}",
        f"유사 문단 수: {report.similar_paragraphs}",
        f"최대 Jaccard: {report.highest_jaccard:.4f}, 최대 포함률: {report.highest_containment:.4f}",
        "주의: 문단별 문자열 유사도 기준선이며 저작권·의미적 독창성의 최종 판정은 아닙니다.",
    ]
    lines.extend(
        f"유사 문단 위치: 참고 {e.reference_number}번 문서 {e.reference_paragraph_number}번 문단, "
        f"원고 {e.draft_paragraph_number}번 문단, Jaccard {e.jaccard:.4f}, 포함률 {e.containment:.4f}"
        for e in report.evidence
    )
    return "\n".join(lines)