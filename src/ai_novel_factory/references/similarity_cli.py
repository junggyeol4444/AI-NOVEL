"""Stage 39 offline similarity baseline CLI: private inputs, numeric output."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .import_pipeline import _LIMITS, _open_bounded, _parse_bytes
from .plaintext_parser import ReferenceParseError
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
    parser.add_argument("--reference", required=True, nargs="+", help="참고 원문 1~20개")
    args = parser.parse_args(argv)
    try:
        if len(args.reference) > 20:
            raise SimilarityCheckError("참고 문서 개수 제한을 초과했습니다.")
        draft = _read(args.draft)
        refs = [_read(p) for p in args.reference]
        report = analyze_similarity_baseline(draft, refs)
        print(render_similarity_baseline(report))
        return 0 if report.allowed_for_automatic_use else 1
    except (ReferenceParseError, SimilarityCheckError):
        print("로컬 유사성 검사를 완료할 수 없습니다. 입력 파일과 크기를 확인하세요.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
