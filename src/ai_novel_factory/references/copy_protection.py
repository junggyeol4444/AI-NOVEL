"""Stage 38: offline, fail-closed verbatim-overlap guard for draft manuscripts.

This is an exact-overlap safety gate, NOT a plagiarism verdict or the stage-39
similarity model. It examines transient normalized characters only: original
source text, excerpts, names, source locations and match fingerprints are NOT
returned, persisted or sent to external services.

References must be available *as text during checking*. Aggregate reference
profiles and SHA-256 file identities cannot replace the original source here.
"""
from __future__ import annotations

from dataclasses import dataclass
import unicodedata

from .plaintext_parser import ParsedReference, ReferenceParseError

REVIEW_MATCH_UNITS = 48
BLOCK_MATCH_UNITS = 96
SHORT_SOURCE_REVIEW_UNITS = 16  # full copy of a 16..47-unit short work is reviewable
MAX_REFERENCES = 100
MAX_REFERENCE_UNITS = 500_000
MAX_DRAFT_UNITS = 200_000
MAX_RAW_REFERENCE_CHARS = 1_000_000
MAX_RAW_DRAFT_CHARS = 400_000


class CopyProtectionError(ReferenceParseError):
    """Only fixed, non-excerpt-bearing error messages."""


@dataclass(frozen=True)
class CopyMatchEvidence:
    """Evidence contains an index and numeric positions, never original text."""

    reference_number: int  # 1-based input order, NOT a title or source path
    draft_normalized_offset: int  # 0-based, not an offset into original file
    minimum_matching_units: int


@dataclass(frozen=True)
class CopyProtectionReport:
    status: str  # clear, review, blocked
    references_checked: int
    draft_units: int
    evidence: CopyMatchEvidence | None

    @property
    def allowed_for_automatic_use(self) -> bool:
        return self.status == "clear"


def _normalize(text: str) -> str:
    """Conservative NFKC/casefold alphanumeric normalization.

    Intentionally ignores punctuation and spaces so superficial formatting
    cannot defeat contiguous overlap detection. Meaning-preserving paraphrase,
    translation, and rearrangement are OUT OF SCOPE.
    """
    return "".join(char for char in unicodedata.normalize("NFKC", text).casefold()
                   if char.isalnum())


def _validated_inputs(
    draft: str, references: list[str | ParsedReference] | tuple[str | ParsedReference, ...],
) -> tuple[str, tuple[str, ...]]:
    if type(draft) is not str or len(draft) > MAX_RAW_DRAFT_CHARS:
        raise CopyProtectionError("원고 문자열 또는 크기가 올바르지 않습니다.")
    if type(references) not in (tuple, list) or not 1 <= len(references) <= MAX_REFERENCES:
        raise CopyProtectionError("검사할 참고 원문은 1~100개가 필요합니다.")
    normalized_draft = _normalize(draft)
    if not 1 <= len(normalized_draft) <= MAX_DRAFT_UNITS:
        raise CopyProtectionError("원고의 유효 문자 수가 허용 범위를 벗어났습니다.")
    normalized_refs: list[str] = []
    raw_total = 0
    units_total = 0
    for source in references:
        if isinstance(source, ParsedReference):
            source = source.text  # transient only, never printed/stored
        if type(source) is not str:
            raise CopyProtectionError("참고 원문 입력 형식이 올바르지 않습니다.")
        raw_total += len(source)
        if raw_total > MAX_RAW_REFERENCE_CHARS:
            raise CopyProtectionError("참고 원문 총크기가 검사 제한을 초과했습니다.")
        normalized = _normalize(source)
        if not normalized:
            raise CopyProtectionError("비어 있는 참고 원문은 검사할 수 없습니다.")
        units_total += len(normalized)
        if units_total > MAX_REFERENCE_UNITS:
            raise CopyProtectionError("참고 원문의 유효 문자 총량이 검사 제한을 초과했습니다.")
        normalized_refs.append(normalized)
    return normalized_draft, tuple(normalized_refs)


def _first_verified_overlap(
    draft: str, references: tuple[str, ...], units: int,
) -> CopyMatchEvidence | None:
    """Fast in-process hashed window filter with exact-string verification.

    The Python hash is an ephemeral screening aid. A hash collision does not
    produce a match unless the actual substring exists in a reference.
    Neither hash nor reference content escapes this function.
    """
    if len(draft) < units:
        return None
    fingerprints = {
        hash(reference[start:start + units])
        for reference in references if len(reference) >= units
        for start in range(len(reference) - units + 1)
    }
    if not fingerprints:
        return None
    for position in range(len(draft) - units + 1):
        snippet = draft[position:position + units]
        if hash(snippet) not in fingerprints:
            continue
        for index, reference in enumerate(references, start=1):
            if snippet in reference:  # exact collision verification
                return CopyMatchEvidence(index, position, units)
    return None


def analyze_copy_protection(
    draft: str, references: list[str | ParsedReference] | tuple[str | ParsedReference, ...],
) -> CopyProtectionReport:
    """Read-only guard: blocked >=96 units; review 48..95; clear otherwise.

    Input order is stable. Missing references, bad types and over-limit inputs
    fail closed via CopyProtectionError, NEVER return a false 'clear'.
    """
    draft_normalized, reference_normalized = _validated_inputs(draft, references)
    for length, status in ((BLOCK_MATCH_UNITS, "blocked"),
                           (REVIEW_MATCH_UNITS, "review")):
        evidence = _first_verified_overlap(draft_normalized, reference_normalized, length)
        if evidence is not None:
            return CopyProtectionReport(status, len(reference_normalized),
                                        len(draft_normalized), evidence)
    # Short source works have no >=48-unit window. A complete copy of one is
    # still worth human review instead of being falsely labeled clear.
    for index, source in enumerate(reference_normalized, start=1):
        if SHORT_SOURCE_REVIEW_UNITS <= len(source) < REVIEW_MATCH_UNITS:
            offset = draft_normalized.find(source)
            if offset >= 0:
                return CopyProtectionReport("review", len(reference_normalized),
                                            len(draft_normalized),
                                            CopyMatchEvidence(index, offset, len(source)))
    return CopyProtectionReport("clear", len(reference_normalized),
                                len(draft_normalized), None)


def require_copy_safe_draft(
    draft: str, references: list[str | ParsedReference] | tuple[str | ParsedReference, ...],
) -> CopyProtectionReport:
    """Fail-closed gate intended to be called before any future Writer output is used.

    A 'review' result requires manual review; 'blocked' is not usable.
    Neither result grants permission to reproduce copyrighted source material.
    """
    result = analyze_copy_protection(draft, references)
    if result.status != "clear":
        raise CopyProtectionError("참고 원문과 긴 일치 구간이 있어 자동 사용을 차단했습니다.")
    return result


def render_copy_protection(report: CopyProtectionReport) -> str:
    """Short numeric-only report suitable for stdout; no excerpts or filenames."""
    if type(report) is not CopyProtectionReport or report.status not in {
        "clear", "review", "blocked"
    } or type(report.references_checked) is not int or not 1 <= report.references_checked <= MAX_REFERENCES \
       or type(report.draft_units) is not int or not 1 <= report.draft_units <= MAX_DRAFT_UNITS \
       or (report.status == "clear") != (report.evidence is None):
        raise CopyProtectionError("비복제 보호 결과가 올바르지 않습니다.")
    if report.evidence is not None:
        event = report.evidence
        if (type(event) is not CopyMatchEvidence or type(event.reference_number) is not int
                or not 1 <= event.reference_number <= report.references_checked
                or type(event.draft_normalized_offset) is not int
                or not 0 <= event.draft_normalized_offset <= report.draft_units
                or type(event.minimum_matching_units) is not int
                or (event.minimum_matching_units != BLOCK_MATCH_UNITS
                    if report.status == "blocked"
                    else not SHORT_SOURCE_REVIEW_UNITS <= event.minimum_matching_units <= REVIEW_MATCH_UNITS)
                or event.draft_normalized_offset + event.minimum_matching_units > report.draft_units):
            raise CopyProtectionError("비복제 보호 근거가 올바르지 않습니다.")
    result = [f"원문 비복제 검사: {report.status}",
              f"검사한 참고 원문: {report.references_checked}개",
              f"원고 유효 문자: {report.draft_units}자"]
    if report.evidence:
        result.append(f"일치 최소 길이: {report.evidence.minimum_matching_units}자 · "
                      f"참고 입력 번호: {report.evidence.reference_number} · "
                      f"원고 정규화 위치: {report.evidence.draft_normalized_offset}")
    result.append("주의: 단순 연속 문자 검사이며 유사성·저작권의 최종 판단은 아닙니다.")
    return "\n".join(result)