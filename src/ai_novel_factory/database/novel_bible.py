"""Stage 41: local, user-authored Novel Bible with absolute precedence.

Only an explicit user save may persist canon text. Reference statistics are
validated as anonymous numbers and never persisted by this module. This is a
foundation for stages 42-49, not a manuscript generator or publication system.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
import os
import re
import sqlite3
from typing import Mapping
from uuid import uuid4

from ai_novel_factory.references.element_selection import FEATURE_KEYS

_ID = re.compile(r"[0-9a-f]{32}\Z")
_KEY = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_MAX_TEXT = 4000
_MAX_BYTES = 8192


class NovelBibleError(ValueError):
    """Never embeds user-authored canon or reference text in errors."""


@dataclass(frozen=True)
class BibleProject:
    project_id: str
    title: str
    revision: int
    created_at: str


@dataclass(frozen=True)
class BibleRule:
    project_id: str
    key: str
    value: str
    revision: int
    updated_at: str


@dataclass(frozen=True)
class ContextField:
    key: str
    value: str | float
    source: str  # 'novel_bible' or 'reference_statistic'


@dataclass(frozen=True)
class ResolvedContext:
    project_id: str
    project_revision: int
    fields: tuple[ContextField, ...]
    overridden_reference_keys: tuple[str, ...]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _id(value: object) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise NovelBibleError("작품 식별자가 올바르지 않습니다.")
    return value


def _key(value: object) -> str:
    if type(value) is not str or not _KEY.fullmatch(value):
        raise NovelBibleError("설정 항목 코드는 영문 소문자와 숫자, 밑줄만 허용합니다.")
    return value


def _text(value: object, *, title: bool = False) -> str:
    limit = 120 if title else _MAX_TEXT
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise NovelBibleError("작품 설정 내용의 형식 또는 길이가 올바르지 않습니다.")
    try:
        byte_length = len(value.encode("utf-8"))
    except UnicodeError:
        raise NovelBibleError("작품 설정 내용의 형식 또는 길이가 올바르지 않습니다.") from None
    if (byte_length > (_MAX_BYTES if not title else 480)
            or any((ord(c) < 32 and c not in "\n\t") or ord(c) == 127 for c in value)
            or (title and ("\n" in value or "\t" in value))):
        raise NovelBibleError("작품 설정 내용의 형식 또는 길이가 올바르지 않습니다.")
    return value


def _revision(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 2**31 - 1:
        raise NovelBibleError("설정 버전이 올바르지 않습니다.")
    return value


def _project(row: sqlite3.Row) -> BibleProject:
    try:
        obj = BibleProject(row["project_id"], row["title"], row["revision"], row["created_at"])
        _id(obj.project_id)
        _text(obj.title, title=True)
        if type(obj.revision) is not int or obj.revision < 0:
            raise NovelBibleError("저장된 작품 정보가 손상되었습니다.")
        datetime.fromisoformat(obj.created_at)
        return obj
    except (TypeError, ValueError, KeyError, IndexError, OverflowError):
        raise NovelBibleError("저장된 작품 정보가 손상되었습니다.") from None


def _rule(row: sqlite3.Row) -> BibleRule:
    try:
        obj = BibleRule(row["project_id"], row["rule_key"], row["rule_value"],
                        row["revision"], row["updated_at"])
        _id(obj.project_id)
        _key(obj.key)
        _text(obj.value)
        _revision(obj.revision)
        datetime.fromisoformat(obj.updated_at)
        return obj
    except (TypeError, ValueError, KeyError, IndexError, OverflowError):
        raise NovelBibleError("저장된 작품 설정이 손상되었습니다.") from None


def _safe_statistics(values: Mapping[str, float] | None) -> dict[str, float]:
    if values is None:
        return {}
    if not isinstance(values, Mapping) or len(values) > len(FEATURE_KEYS):
        raise NovelBibleError("참고 통계 항목이 올바르지 않습니다.")
    result: dict[str, float] = {}
    for key, value in values.items():
        if (type(key) is not str or key not in FEATURE_KEYS
                or type(value) not in (int, float) or not isfinite(value)
                or abs(value) > 1_000_000_000):
            raise NovelBibleError("참고 통계는 허용된 항목의 유한한 숫자만 사용할 수 있습니다.")
        result[key] = float(value)
    return result


class NovelBibleStore:
    """SQLite canon storage, independent from the reference catalog.

    Explicit user actions create/update/delete rules. Existing rules require
    an exact expected revision for edits, preventing silent lost updates.
    """

    def __init__(self, database_path: str | Path = ":memory:") -> None:
        path = str(database_path) if isinstance(database_path, Path) else database_path
        if type(path) is not str or not path or "\x00" in path:
            raise NovelBibleError("로컬 SQLite 파일 경로가 올바르지 않습니다.")
        if path != ":memory:":
            if path.startswith(("file:", "\\\\", "//")):
                raise NovelBibleError("원격 경로나 SQLite URI는 사용할 수 없습니다.")
            candidate = Path(path)
            if (not candidate.parent.is_dir() or candidate.is_symlink()
                    or (candidate.exists() and not candidate.is_file())):
                raise NovelBibleError("로컬 SQLite 파일을 사용할 수 없습니다.")
        self._db = sqlite3.connect(path, timeout=10)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA busy_timeout=10000")
        if path != ":memory:" and os.name == "posix":
            # Keep locally authored canon private by default (not encryption).
            os.chmod(path, 0o600)
        with self._db:
            self._db.execute("""CREATE TABLE IF NOT EXISTS bible_projects (
                project_id TEXT PRIMARY KEY CHECK(length(project_id)=32),
                title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
                revision INTEGER NOT NULL DEFAULT 0 CHECK(revision>=0),
                created_at TEXT NOT NULL
            )""")
            self._db.execute("""CREATE TABLE IF NOT EXISTS bible_rules (
                project_id TEXT NOT NULL REFERENCES bible_projects(project_id) ON DELETE CASCADE,
                rule_key TEXT NOT NULL CHECK(length(rule_key) BETWEEN 1 AND 64),
                rule_value TEXT NOT NULL CHECK(length(rule_value) BETWEEN 1 AND 4000),
                revision INTEGER NOT NULL CHECK(revision>=1),
                updated_at TEXT NOT NULL,
                PRIMARY KEY(project_id, rule_key)
            )""")
            self._db.execute("CREATE INDEX IF NOT EXISTS ix_bible_rules_project ON bible_rules(project_id)")

    def __enter__(self) -> NovelBibleStore:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._db.close()

    def create_project(self, title: str) -> BibleProject:
        title = _text(title, title=True)
        uid = uuid4().hex
        with self._db:
            self._db.execute("INSERT INTO bible_projects VALUES (?, ?, 0, ?)", (uid, title, _now()))
        return self.get_project(uid)

    def get_project(self, project_id: str) -> BibleProject:
        project_id = _id(project_id)
        row = self._db.execute("SELECT * FROM bible_projects WHERE project_id=?", (project_id,)).fetchone()
        if row is None:
            raise NovelBibleError("작품을 찾을 수 없습니다.")
        return _project(row)

    def list_projects(self) -> tuple[BibleProject, ...]:
        return tuple(_project(row) for row in self._db.execute(
            "SELECT * FROM bible_projects ORDER BY created_at, project_id"))

    def delete_project(self, project_id: str) -> None:
        project_id = _id(project_id)
        with self._db:
            cursor = self._db.execute("DELETE FROM bible_projects WHERE project_id=?", (project_id,))
            if cursor.rowcount != 1:
                raise NovelBibleError("작품을 찾을 수 없습니다.")

    def get_rule(self, project_id: str, key: str) -> BibleRule:
        project_id, key = _id(project_id), _key(key)
        row = self._db.execute("SELECT * FROM bible_rules WHERE project_id=? AND rule_key=?",
                               (project_id, key)).fetchone()
        if row is None:
            raise NovelBibleError("설정 항목을 찾을 수 없습니다.")
        return _rule(row)

    def list_rules(self, project_id: str) -> tuple[BibleRule, ...]:
        self.get_project(project_id)
        return tuple(_rule(row) for row in self._db.execute(
            "SELECT * FROM bible_rules WHERE project_id=? ORDER BY rule_key", (project_id,)))

    def save_rule(self, project_id: str, key: str, value: str,
                  *, expected_revision: int | None = None) -> BibleRule:
        project_id, key, value = _id(project_id), _key(key), _text(value)
        if expected_revision is not None:
            _revision(expected_revision)
        with self._db:
            # Serialize check+write even when multiple connections edit same DB.
            self._db.execute("BEGIN IMMEDIATE")
            self.get_project(project_id)
            row = self._db.execute(
                "SELECT revision FROM bible_rules WHERE project_id=? AND rule_key=?",
                (project_id, key)).fetchone()
            if row is None:
                if expected_revision is not None:
                    raise NovelBibleError("설정이 변경되었거나 삭제되었습니다.")
                self._db.execute("INSERT INTO bible_rules VALUES (?, ?, ?, 1, ?)",
                                 (project_id, key, value, _now()))
            else:
                if expected_revision != row["revision"]:
                    raise NovelBibleError("설정이 변경되었습니다. 최신 버전을 확인하세요.")
                self._db.execute("""UPDATE bible_rules SET rule_value=?, revision=revision+1,
                                   updated_at=? WHERE project_id=? AND rule_key=?""",
                                 (value, _now(), project_id, key))
            self._db.execute("UPDATE bible_projects SET revision=revision+1 WHERE project_id=?",
                             (project_id,))
        return self.get_rule(project_id, key)

    def delete_rule(self, project_id: str, key: str, *, expected_revision: int) -> None:
        project_id, key = _id(project_id), _key(key)
        expected_revision = _revision(expected_revision)
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self.get_project(project_id)
            cursor = self._db.execute(
                "DELETE FROM bible_rules WHERE project_id=? AND rule_key=? AND revision=?",
                (project_id, key, expected_revision))
            if cursor.rowcount != 1:
                raise NovelBibleError("설정이 변경되었거나 삭제되었습니다.")
            self._db.execute("UPDATE bible_projects SET revision=revision+1 WHERE project_id=?",
                             (project_id,))

    def resolve_context(self, project_id: str,
                        reference_statistics: Mapping[str, float] | None = None) -> ResolvedContext:
        """User canon ALWAYS overrides conflicting anonymous reference numbers.

        No source text or statistical input is persisted. A missing Bible rule
        set fails closed; this is NOT an authorization to generate/publish.
        """
        project = self.get_project(project_id)
        rules = self.list_rules(project_id)
        if not rules:
            raise NovelBibleError("Novel Bible 설정이 없어 생성 컨텍스트를 만들 수 없습니다.")
        statistics = _safe_statistics(reference_statistics)
        values: dict[str, ContextField] = {
            key: ContextField(key, val, "reference_statistic") for key, val in statistics.items()
        }
        conflicts = tuple(sorted(key for key in statistics if any(rule.key == key for rule in rules)))
        for rule in rules:
            values[rule.key] = ContextField(rule.key, rule.value, "novel_bible")
        return ResolvedContext(project.project_id, project.revision,
                               tuple(values[key] for key in sorted(values)), conflicts)
