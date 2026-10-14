"""Stage 44 (ANF-REQ-034): offline, project-scoped, user-authored world canon.

Worldbuilding entries are Novel Bible canon, not material inferred from reference
novels. No external requests, automated generation, or publication is performed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sqlite3
from uuid import uuid4

from .novel_bible import NovelBibleError, NovelBibleStore, _id, _now, _revision, _text


WORLD_CATEGORIES = frozenset({"worldview", "organization", "region", "ability", "item"})


class WorldCanonError(NovelBibleError):
    """Errors intentionally contain no user-authored worldbuilding text."""


@dataclass(frozen=True)
class WorldEntry:
    entry_id: str
    project_id: str
    category: str
    name: str
    description: str
    revision: int
    created_at: str
    updated_at: str


def _category(value: object) -> str:
    if type(value) is not str or value not in WORLD_CATEGORIES:
        raise WorldCanonError("세계관 항목 종류가 올바르지 않습니다.")
    return value


def _name(value: object) -> str:
    try:
        name = _text(value, title=True)
        if name != name.strip():
            raise WorldCanonError("세계관 항목 이름의 형식이 올바르지 않습니다.")
        return name
    except NovelBibleError:
        raise WorldCanonError("세계관 항목 이름의 형식이 올바르지 않습니다.") from None


def _description(value: object) -> str:
    try:
        return _text(value)
    except NovelBibleError:
        raise WorldCanonError("세계관 항목 설명의 형식 또는 길이가 올바르지 않습니다.") from None


def _timestamp(value: object) -> None:
    try:
        if type(value) is not str:
            raise ValueError("invalid timestamp")
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("missing timezone")
    except (ValueError, OverflowError, TypeError):
        raise WorldCanonError("저장된 세계관 항목이 손상되었습니다.") from None


def _entry(row: sqlite3.Row) -> WorldEntry:
    try:
        item = WorldEntry(
            row["entry_id"], row["project_id"], row["category"],
            row["name"], row["description"], row["revision"],
            row["created_at"], row["updated_at"],
        )
        _id(item.entry_id)
        _id(item.project_id)
        _category(item.category)
        _name(item.name)
        _description(item.description)
        _revision(item.revision)
        _timestamp(item.created_at)
        _timestamp(item.updated_at)
        return item
    except (NovelBibleError, TypeError, ValueError, KeyError, IndexError, OverflowError):
        raise WorldCanonError("저장된 세계관 항목이 손상되었습니다.") from None


class WorldCanonStore(NovelBibleStore):
    """Explicit worldbuilding CRUD in the same local SQLite as Novel Bible.

    All mutations are atomic and bump the parent project's revision. Existing
    entries require a matching revision; failed writes never bump the project.
    An entry ID is stable across edits and unique across all projects.
    """

    def __init__(self, database_path: str | Path = ":memory:") -> None:
        super().__init__(database_path)
        with self._db:
            self._db.execute("""CREATE TABLE IF NOT EXISTS bible_world_entries (
                entry_id TEXT PRIMARY KEY CHECK(length(entry_id)=32),
                project_id TEXT NOT NULL REFERENCES bible_projects(project_id) ON DELETE CASCADE,
                category TEXT NOT NULL CHECK(category IN
                    ('worldview', 'organization', 'region', 'ability', 'item')),
                name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 120),
                description TEXT NOT NULL CHECK(length(description) BETWEEN 1 AND 4000),
                revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 2147483647),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(project_id, category, name)
            )""")
            self._db.execute("""CREATE INDEX IF NOT EXISTS ix_bible_world_project_category
                ON bible_world_entries(project_id, category, name)""")

    def _bump_world_project(self, project_id: str) -> None:
        self._db.execute("UPDATE bible_projects SET revision=revision+1 WHERE project_id=?",
                         (project_id,))

    def create_entry(self, project_id: str, *, category: str, name: str,
                     description: str) -> WorldEntry:
        project_id = _id(project_id)
        category, name, description = _category(category), _name(name), _description(description)
        entry_id, timestamp = uuid4().hex, _now()
        try:
            with self._db:
                self._db.execute("BEGIN IMMEDIATE")
                self.get_project(project_id)
                self._db.execute("""INSERT INTO bible_world_entries
                    (entry_id, project_id, category, name, description,
                     revision, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
                    (entry_id, project_id, category, name, description, timestamp, timestamp))
                self._bump_world_project(project_id)
        except sqlite3.IntegrityError:
            raise WorldCanonError("세계관 항목이 중복되었거나 저장할 수 없습니다.") from None
        return self.get_entry(project_id, entry_id)

    def get_entry(self, project_id: str, entry_id: str) -> WorldEntry:
        project_id, entry_id = _id(project_id), _id(entry_id)
        self.get_project(project_id)
        row = self._db.execute("""SELECT * FROM bible_world_entries
            WHERE project_id=? AND entry_id=?""", (project_id, entry_id)).fetchone()
        if row is None:
            raise WorldCanonError("해당 작품의 세계관 항목을 찾을 수 없습니다.")
        return _entry(row)

    def list_entries(self, project_id: str, *, category: str | None = None
                     ) -> tuple[WorldEntry, ...]:
        project_id = _id(project_id)
        if category is not None:
            category = _category(category)
        self.get_project(project_id)
        if category is None:
            rows = self._db.execute("""SELECT * FROM bible_world_entries
                WHERE project_id=? ORDER BY category, name, entry_id""", (project_id,))
        else:
            rows = self._db.execute("""SELECT * FROM bible_world_entries
                WHERE project_id=? AND category=? ORDER BY name, entry_id""",
                (project_id, category))
        return tuple(_entry(row) for row in rows)

    def update_entry(self, project_id: str, entry_id: str, *, expected_revision: int,
                     category: str | None = None, name: str | None = None,
                     description: str | None = None) -> WorldEntry:
        project_id, entry_id = _id(project_id), _id(entry_id)
        expected_revision = _revision(expected_revision)
        if expected_revision == 2**31 - 1:
            raise WorldCanonError("세계관 항목 버전 한도에 도달했습니다.")
        changes: dict[str, str] = {}
        if category is not None:
            changes["category"] = _category(category)
        if name is not None:
            changes["name"] = _name(name)
        if description is not None:
            changes["description"] = _description(description)
        if not changes:
            raise WorldCanonError("수정할 세계관 항목이 없습니다.")
        try:
            with self._db:
                self._db.execute("BEGIN IMMEDIATE")
                old = self.get_entry(project_id, entry_id)
                if old.revision != expected_revision:
                    raise WorldCanonError("세계관 항목이 변경되었습니다. 최신 버전을 확인하세요.")
                assignments = ", ".join(f"{field}=?" for field in changes)
                cursor = self._db.execute(
                    f"UPDATE bible_world_entries SET {assignments}, revision=revision+1, "
                    "updated_at=? WHERE project_id=? AND entry_id=? AND revision=?",
                    (*changes.values(), _now(), project_id, entry_id, expected_revision))
                if cursor.rowcount != 1:
                    raise WorldCanonError("세계관 항목이 변경되었거나 삭제되었습니다.")
                self._bump_world_project(project_id)
        except sqlite3.IntegrityError:
            raise WorldCanonError("세계관 항목이 중복되었거나 수정할 수 없습니다.") from None
        return self.get_entry(project_id, entry_id)

    def delete_entry(self, project_id: str, entry_id: str, *, expected_revision: int) -> None:
        project_id, entry_id = _id(project_id), _id(entry_id)
        expected_revision = _revision(expected_revision)
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self.get_project(project_id)
            cursor = self._db.execute("""DELETE FROM bible_world_entries
                WHERE project_id=? AND entry_id=? AND revision=?""",
                (project_id, entry_id, expected_revision))
            if cursor.rowcount != 1:
                raise WorldCanonError("세계관 항목이 변경되었거나 삭제되었습니다.")
            self._bump_world_project(project_id)
