"""Stage 19: private, local-only reference-file metadata catalog.

No reference text, API credentials, or full user filesystem paths are stored.
This is a SQLite desktop adapter; PostgreSQL integration remains a later step.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
import re
import sqlite3
from uuid import uuid4


_FORMATS = frozenset({"txt", "md", "markdown", "epub", "docx", "pdf"})
_STATUSES = frozenset({"registered", "analyzing", "analyzed", "failed"})
_TRANSITIONS = {
    "registered": frozenset({"analyzing"}),
    "analyzing": frozenset({"analyzed", "failed"}),
    "analyzed": frozenset({"analyzing"}),
    "failed": frozenset({"analyzing"}),
}
_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")


class CatalogError(ValueError):
    """Invalid catalog input or illegal state transition."""


@dataclass(frozen=True)
class ReferenceRecord:
    reference_id: str
    file_name: str
    source_format: str
    byte_count: int
    sha256: str
    status: str
    created_at: str
    updated_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _basename(filename: str) -> str:
    if not isinstance(filename, str) or not filename.strip():
        raise CatalogError("파일 이름이 필요합니다.")
    # Accept either Windows or POSIX input paths but persist basename only.
    normalized = filename.replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1].strip()
    if (not name or name in {".", ".."} or len(name) > 255
            or any(ord(c) < 32 or ord(c) == 127 for c in name)):
        raise CatalogError("파일 이름이 올바르지 않습니다.")
    return name


def _validate_registration(file_name: str, source_format: str, byte_count: int, sha256: str):
    name = _basename(file_name)
    if not isinstance(source_format, str) or source_format.casefold() not in _FORMATS:
        raise CatalogError("지원하지 않는 참고소설 형식입니다.")
    fmt = source_format.casefold()
    if fmt == "markdown":
        fmt = "md"
    if Path(name).suffix.lower().lstrip(".") not in {fmt, "markdown" if fmt == "md" else fmt}:
        raise CatalogError("확장자와 파일 형식이 일치하지 않습니다.")
    if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count <= 0:
        raise CatalogError("파일 크기는 양의 정수여야 합니다.")
    if not isinstance(sha256, str) or _SHA256.fullmatch(sha256) is None:
        raise CatalogError("SHA-256 파일 식별자가 올바르지 않습니다.")
    return name, fmt, sha256.lower()


def _record(row: sqlite3.Row) -> ReferenceRecord:
    return ReferenceRecord(**dict(row))


class ReferenceCatalog:
    """Simple transactional metadata registry; caller calculates SHA-256 elsewhere.

    Use ``with ReferenceCatalog(path) as catalog: ...`` to close resources.
    The database path must be local and its parent directory must already exist;
    in-memory databases are supported for tests. Never use this for raw text.
    """

    def __init__(self, database_path: str | Path = ":memory:") -> None:
        if isinstance(database_path, Path):
            database_path = str(database_path)
        if not isinstance(database_path, str) or not database_path:
            raise CatalogError("DB 경로가 올바르지 않습니다.")
        if database_path != ":memory:":
            candidate = Path(database_path)
            if not candidate.parent.is_dir():
                raise CatalogError("DB 상위 폴더가 존재하지 않습니다.")
        self._db = sqlite3.connect(database_path, timeout=10)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA busy_timeout=10000")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS reference_files (
              reference_id TEXT PRIMARY KEY,
              file_name TEXT NOT NULL,
              source_format TEXT NOT NULL,
              byte_count INTEGER NOT NULL CHECK (byte_count > 0),
              sha256 TEXT NOT NULL UNIQUE,
              status TEXT NOT NULL DEFAULT 'registered'
                CHECK (status IN ('registered','analyzing','analyzed','failed')),
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_reference_files_status_created
              ON reference_files(status, created_at DESC);
        """)

    def __enter__(self) -> "ReferenceCatalog":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._db.close()

    def register(self, *, file_name: str, source_format: str,
                 byte_count: int, sha256: str) -> ReferenceRecord:
        """Register immutable file identity, reusing prior ID for same hash."""
        name, fmt, checksum = _validate_registration(file_name, source_format, byte_count, sha256)
        with self._db:
            row = self._db.execute(
                "SELECT * FROM reference_files WHERE sha256 = ?", (checksum,)
            ).fetchone()
            if row is not None:
                if row["byte_count"] != byte_count or row["source_format"] != fmt:
                    raise CatalogError("기존 파일 식별자와 메타데이터가 일치하지 않습니다.")
                return _record(row)
            timestamp = _now()
            key = uuid4().hex
            self._db.execute(
                """INSERT INTO reference_files
                   (reference_id, file_name, source_format, byte_count, sha256,
                    status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'registered', ?, ?)""",
                (key, name, fmt, byte_count, checksum, timestamp, timestamp),
            )
            return self.get(key)

    def get(self, reference_id: str) -> ReferenceRecord:
        row = self._db.execute(
            "SELECT * FROM reference_files WHERE reference_id = ?", (reference_id,)
        ).fetchone()
        if row is None:
            raise CatalogError("등록된 참고소설을 찾을 수 없습니다.")
        return _record(row)

    def list(self, *, status: str | None = None, limit: int = 100,
             offset: int = 0) -> tuple[ReferenceRecord, ...]:
        if status is not None and status not in _STATUSES:
            raise CatalogError("올바르지 않은 분석 상태입니다.")
        if (isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000
                or isinstance(offset, bool) or not isinstance(offset, int) or offset < 0):
            raise CatalogError("목록 조회 범위가 올바르지 않습니다.")
        if status is None:
            rows = self._db.execute(
                "SELECT * FROM reference_files ORDER BY created_at DESC, reference_id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        else:
            rows = self._db.execute(
                "SELECT * FROM reference_files WHERE status=? ORDER BY created_at DESC, reference_id DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            ).fetchall()
        return tuple(_record(row) for row in rows)

    def count(self, *, status: str | None = None) -> int:
        if status is not None and status not in _STATUSES:
            raise CatalogError("올바르지 않은 분석 상태입니다.")
        if status is None:
            return self._db.execute("SELECT COUNT(*) FROM reference_files").fetchone()[0]
        return self._db.execute(
            "SELECT COUNT(*) FROM reference_files WHERE status=?", (status,)
        ).fetchone()[0]

    def change_status(self, reference_id: str, new_status: str) -> ReferenceRecord:
        if new_status not in _STATUSES:
            raise CatalogError("올바르지 않은 분석 상태입니다.")
        with self._db:
            old = self.get(reference_id)
            if new_status not in _TRANSITIONS[old.status]:
                raise CatalogError("허용되지 않은 분석 상태 변경입니다.")
            self._db.execute(
                "UPDATE reference_files SET status=?, updated_at=? WHERE reference_id=?",
                (new_status, _now(), reference_id),
            )
            return self.get(reference_id)
