"""Offline text/draft copyright guard CLI; reads files, persists nothing."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .copy_protection import MAX_REFERENCES, MAX_RAW_REFERENCE_CHARS, MAX_RAW_DRAFT_CHARS, MAX_REFERENCE_UNITS, MAX_DRAFT_UNITS, _normalize, CopyProtectionError, analyze_copy_protection, render_copy_protection
from .import_pipeline import _LIMITS, _open_bounded, _parse_bytes
from .plaintext_parser import ReferenceParseError


def _read_document(path: str) -> str:
    target = Path(path)
    suffix = target.suffix.lower()
    if suffix not in _LIMITS:
        raise ReferenceParseError("지원되지 않는 입력 문서 형식입니다.")
    raw = _open_bounded(target, _LIMITS[suffix])
    parsed = _parse_bytes(raw, suffix, encoding=None)
    return parsed.text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="로컬 원문 비복제 구간 검사 (데이터 저장 없음)")
    parser.add_argument("--draft", required=True, help="검사할 원고 TXT/MD/DOCX/PDF")
    parser.add_argument("--reference", required=True, nargs="+", help="참고 원문 1~100개")
    args = parser.parse_args(argv)
    try:
        if len(args.reference) > MAX_REFERENCES:
            raise ReferenceParseError('참고 원문 개수 제한을 초과했습니다.')
        draft = _read_document(args.draft)
        if len(draft) > MAX_RAW_DRAFT_CHARS or not 1 <= len(_normalize(draft)) <= MAX_DRAFT_UNITS:
            raise CopyProtectionError('검사 원고의 유효 문자 또는 크기 제한을 초과했습니다.')
        references = []
        raw_total = 0
        units_total = 0
        for path in args.reference:
            reference = _read_document(path)
            raw_total += len(reference)
            if raw_total > MAX_RAW_REFERENCE_CHARS:
                raise CopyProtectionError('참고 원문 총크기가 검사 제한을 초과했습니다.')
            units = len(_normalize(reference))
            if not units:
                raise CopyProtectionError('유효 문자가 없는 참고 원문은 검사할 수 없습니다.')
            units_total += units
            if units_total > MAX_REFERENCE_UNITS:
                raise CopyProtectionError('참고 원문의 유효 문자 총량이 검사 제한을 초과했습니다.')
            references.append(reference)
        report = analyze_copy_protection(draft, references)
    except (ReferenceParseError, CopyProtectionError):
        print("비복제 보호 검사를 완료할 수 없습니다. 파일과 제한을 확인하세요.", file=sys.stderr)
        return 2  # failed/inconclusive is never a pass
    print(render_copy_protection(report))
    return 0 if report.allowed_for_automatic_use else 1


if __name__ == "__main__":
    raise SystemExit(main())