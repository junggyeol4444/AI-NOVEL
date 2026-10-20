"""Explicit, transient local reference-file comparison for current saved draft.

Source texts are never returned, stored, logged, sent to the writer, nor
uploaded. Only a user-initiated click can supply a list of paths. This is
NOT a comprehensive reference coverage, semantic plagiarism, copyright, or
publication approval: missing annotations and unverified catalog must remain
UNEXAMINED. Never truncate a selected work to fabricate a 'clear' verdict.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from ai_novel_factory.reference_similarity_checker import (
    ReferenceMaterial, ReferenceSimilarityError, ReferenceSimilarityReport,
    check_reference_similarity,
)
from ai_novel_factory.references.copy_protection import (
    MAX_RAW_REFERENCE_CHARS, MAX_REFERENCE_UNITS, _normalize,
)
from ai_novel_factory.references.import_pipeline import (
    _LIMITS, _open_bounded, _parse_bytes,
)
from ai_novel_factory.references.plaintext_parser import ReferenceParseError


class OptInSimilarityError(ValueError):
    """Safe fixed messages only: never include local filenames or passages."""


@dataclass(frozen=True, slots=True)
class OptInComparison:
    checked_files: int
    report: ReferenceSimilarityReport
    source_data_persisted: bool = False
    corpus_coverage_certified: bool = False
    manuscript_approved: bool = False


def compare_explicit_reference_files(
    project_id: str, episode: int, saved_draft: str,
    paths: tuple[str, ...],
) -> OptInComparison:
    """Compare all chosen document text in memory; no silent partial coverage.

    Max 20 source works / 1m raw chars / 500k normalized units are the
    *existing* similarity engine bounds, not new approval thresholds. If
    exceeded, fail closed and require a different explicit workflow.
    """
    if (type(paths) is not tuple or not 1 <= len(paths) <= 20
            or any(type(name) is not str or not name for name in paths)
            or len(set(paths)) != len(paths)):
        raise OptInSimilarityError('참고소설은 중복 없이 1~20개 직접 선택해야 합니다.')
    refs = []
    total_raw_chars = 0
    total_units = 0
    total_bytes = 0
    for name in paths:
        path = Path(name)
        if (not path.is_absolute() or path.is_symlink()
                or name.startswith(('\\\\', '//'))
                or path.suffix.lower() not in _LIMITS):
            raise OptInSimilarityError('지원하지 않는 파일 경로 또는 형식입니다.')
        try:
            raw = _open_bounded(path, _LIMITS[path.suffix.lower()])
            total_bytes += len(raw)
            if total_bytes > 32 * 1024 * 1024:
                raise OptInSimilarityError('선택한 전체 참고파일 크기가 제한을 초과했습니다.')
            parsed = _parse_bytes(raw, path.suffix.lower(), None)
            if getattr(parsed, 'image_only_pages', ()):
                raise OptInSimilarityError(
                    '이미지 전용 PDF 페이지는 OCR 없이 전수 비교할 수 없습니다.')
        except (ReferenceParseError, OSError, ValueError) as exc:
            if isinstance(exc, OptInSimilarityError):
                raise
            raise OptInSimilarityError(
                '선택한 참고파일 전체를 안전하게 분석할 수 없습니다.') from None
        total_raw_chars += len(parsed.text)
        total_units += len(_normalize(parsed.text))
        if (total_raw_chars > MAX_RAW_REFERENCE_CHARS
                or total_units > MAX_REFERENCE_UNITS):
            raise OptInSimilarityError(
                '전체 원문이 비교 엔진 제한을 초과했습니다. 부분 검사로 통과 처리하지 않습니다.')
        refs.append(ReferenceMaterial(
            reference_id=uuid4().hex, source_sha256=sha256(raw).hexdigest(),
            text=parsed.text))
    # No catalog identity/source certification; missing scene and abstract
    # structure coverage are explicit unexamined reasons on the report.
    try:
        report = check_reference_similarity(
            project_id, episode, saved_draft, references=tuple(refs))
    except (ReferenceSimilarityError, ValueError):
        raise OptInSimilarityError(
            '선택한 원문 범위를 비교할 수 없습니다. 결과는 미검증으로 유지합니다.') from None
    return OptInComparison(len(refs), report)
