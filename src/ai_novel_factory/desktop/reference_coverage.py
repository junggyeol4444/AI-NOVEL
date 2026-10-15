"""Read-only metadata coverage; never evidence of manuscript similarity clearance.

Only counts catalog status values. Does not open, copy or transmit source novels.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import sqlite3


@dataclass(frozen=True)
class ReferenceCoverage:
    registered: int | None
    analyzed: int | None
    reason: str = "AVAILABLE"

    @property
    def label(self) -> str:
        if self.reason == "MISSING":
            return "로컬 참고작 목록 파일 없음 · 전수 유사성 검사 NOT_RUN"
        if self.registered is None:
            return "로컬 참고작 목록 확인 불가 · 전수 유사성 검사 NOT_RUN"
        return (f"등록 참고작 {self.registered}개 / 분석 완료 {self.analyzed}개 · "
                "전수 유사성 검사 NOT_RUN")


def read_reference_coverage(path: Path) -> ReferenceCoverage:
    """Count only known metadata in an existing absolute SQLite file.

    A missing file is *unknown*, not a confirmed empty catalog. Opening the
    actual ReferenceCatalog here would create tables or modify existing files.
    """
    if not isinstance(path, Path) or not path.is_absolute() or path.is_symlink():
        return ReferenceCoverage(None, None, "INVALID_PATH")
    if not path.is_file():
        return ReferenceCoverage(None, None, "MISSING")
    try:
        # URI read-only mode must never initialize an absent database.
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
            db.execute("PRAGMA query_only=ON")
            registered, analyzed = db.execute(
                "SELECT COUNT(*), COUNT(CASE WHEN status='analyzed' THEN 1 END) "
                "FROM reference_files"
            ).fetchone()
            return ReferenceCoverage(registered, analyzed)
    except (OSError, sqlite3.Error, ValueError):
        return ReferenceCoverage(None, None, "UNAVAILABLE")
