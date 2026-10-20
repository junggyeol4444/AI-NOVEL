"""Stage 39 offline similarity baseline CLI: private inputs, numeric output."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .import_pipeline import _LIMITS, _open_bounded, _parse_bytes
from .plaintext_parser import ReferenceParseError
from .copy_protection import MAX_REFERENCES, MAX_RAW_REFERENCE_CHARS, MAX_RAW_DRAFT_CHARS, MAX_REFERENCE_UNITS, MAX_DRAFT_UNITS, _normalize
from .similarity_baseline import (
    SimilarityCheckError, analyze_similarity_baseline, render_similarity_baseline,
)


def _read(path: str):
    target = Path(path)
    suffix = target.suffix.lower()
    if suffix not in _LIMITS:
        raise SimilarityCheckError("지원되지 않는 입력 문서 형식입니다.")
    raw = _open_bounded(target, _LIMITS[suffix])
    return _parse_bytes(raw, suffix, encoding=None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="로컬 유사성 기준선 검사 (원문 저장 없음)")
    parser.add_argument("--draft", required=True, help="검사 원고 경로")
    parser.add_argument("--reference", required=True, nargs="+", help="참고 원문 1~100개")
    args = parser.parse_args(argv)
    try:
        if len(args.reference) > MAX_REFERENCES:
            raise SimilarityCheckError("참고 문서 개수 제한을 초과했습니다.")
        draft = _read(args.draft)
        if len(draft.text) > MAX_RAW_DRAFT_CHARS or not 1 <= len(_normalize(draft.text)) <= MAX_DRAFT_UNITS:
            raise SimilarityCheckError('검사 원고의 유효 문자 또는 크기 제한을 초과했습니다.')
        refs = []
        raw_total = 0
        units_total = 0
        for path in args.reference:
            reference = _read(path)
            raw_total += len(reference.text)
            if raw_total > MAX_RAW_REFERENCE_CHARS:
                raise SimilarityCheckError('참고 원문 총크기가 검사 제한을 초과했습니다.')
            units = len(_normalize(reference.text))
            if not units:
                raise SimilarityCheckError('유효 문자가 없는 참고 원문은 검사할 수 없습니다.')
            units_total += units
            if units_total > MAX_REFERENCE_UNITS:
                raise SimilarityCheckError('참고 원문의 유효 문자 총량이 검사 제한을 초과했습니다.')
            refs.append(reference)
        report = analyze_similarity_baseline(draft, refs)
        print(render_similarity_baseline(report))
        return 0 if report.allowed_for_automatic_use else 1
    except (ReferenceParseError, SimilarityCheckError):
        print("로컬 유사성 검사를 완료할 수 없습니다. 입력 파일과 크기를 확인하세요.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())