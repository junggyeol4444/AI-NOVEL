"""Offline SQLite schema audit and transactional version stamping (roadmap stage 50).

No destructive table changes are performed. Backups use SQLite's consistent
backup API; migration refuses damaged databases and unknown future versions.
"""
from __future__ import annotations
from contextlib import closing

from dataclasses import dataclass
from pathlib import Path
import sqlite3

SCHEMA_VERSION = 1
REQUIRED_TABLES = frozenset({"bible_projects", "bible_rules"})


class MigrationError(ValueError):
    """Safe errors do not reveal manuscript content."""


@dataclass(frozen=True)
class IntegrityReport:
    version: int
    tables: tuple[str, ...]
    foreign_key_errors: int
    integrity_ok: bool


def _local_path(path: str | Path, *, must_exist: bool = True) -> Path:
    if not isinstance(path, (str, Path)):
        raise MigrationError("올바르지 않은 데이터베이스 경로입니다.")
    value = str(path)
    if not value or "\x00" in value or value.startswith(("file:", "\\\\", "//")) or value == ":memory:":
        raise MigrationError("로컬 SQLite 파일만 허용합니다.")
    p = Path(value)
    if p.is_symlink() or not p.parent.is_dir() or (must_exist and not p.is_file()):
        raise MigrationError("로컬 데이터베이스 파일을 찾을 수 없습니다.")
    return p


def _audit(db: sqlite3.Connection) -> IntegrityReport:
    try:
        integrity = db.execute("PRAGMA integrity_check").fetchall()
        fk = db.execute("PRAGMA foreign_key_check").fetchall()
        tables = tuple(sorted(row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")))
        version = int(db.execute("PRAGMA user_version").fetchone()[0])
    except sqlite3.DatabaseError as exc:
        raise MigrationError("데이터베이스 무결성 검사를 수행할 수 없습니다.") from exc
    return IntegrityReport(version, tables, len(fk), integrity == [("ok",)])


def audit_database(path: str | Path) -> IntegrityReport:
    p = _local_path(path)
    try:
        with closing(sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)) as db, db:
            return _audit(db)
    except sqlite3.DatabaseError as exc:
        raise MigrationError("데이터베이스를 열 수 없습니다.") from exc


def migrate_database(path: str | Path, backup_path: str | Path) -> IntegrityReport:
    """Validate, backup, and stamp schema version; never discard user tables.

    The backup is made before version changes and is exclusively created, so an
    existing backup cannot be overwritten. A failed audit makes no changes.
    """
    source = _local_path(path)
    target = _local_path(backup_path, must_exist=False)
    if source.resolve() == target.resolve() or target.exists():
        raise MigrationError("백업 경로가 원본과 같거나 이미 존재합니다.")
    try:
        with closing(sqlite3.connect(source)) as db, db:
            db.execute("PRAGMA foreign_keys=ON")
            report = _audit(db)
            if (not report.integrity_ok or report.foreign_key_errors
                    or not REQUIRED_TABLES.issubset(report.tables)
                    or report.version > SCHEMA_VERSION):
                raise MigrationError("스키마 버전 또는 데이터 무결성 검사가 실패했습니다.")
            # Reserve target exclusively, then use SQLite online backup.
            with target.open("xb"):
                pass
            try:
                with closing(sqlite3.connect(target)) as backup, backup:
                    db.backup(backup)
                db.execute("BEGIN IMMEDIATE")
                db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                db.commit()
            except BaseException:
                db.rollback()
                target.unlink(missing_ok=True)
                raise
            return _audit(db)
    except sqlite3.DatabaseError as exc:
        raise MigrationError("마이그레이션에 실패했습니다.") from exc
