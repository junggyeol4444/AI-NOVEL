"""Stage 42 (ANF-REQ-032): local, project-scoped Novel Bible characters.

Character records are user-authored canon, NOT inferred from reference works.
No automatic generation, publication, network access or model integration occurs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sqlite3
from uuid import uuid4

from .novel_bible import NovelBibleError, NovelBibleStore, _id, _now, _revision, _text


class CharacterError(NovelBibleError):
    """Sanitized error: never includes names, dialogue, secrets, or paths."""


@dataclass(frozen=True)
class BibleCharacter:
    character_id: str
    project_id: str
    name: str
    personality: str
    goal: str
    speech_style: str
    secret: str
    revision: int
    created_at: str
    updated_at: str


def _content(value: object, *, optional: bool = False) -> str:
    if optional and value == "" and type(value) is str:
        return ""
    try:
        return _text(value)
    except NovelBibleError:
        raise CharacterError("인물 설정 내용의 형식 또는 길이가 올바르지 않습니다.") from None


def _name(value: object) -> str:
    try:
        name = _text(value, title=True)
        if name != name.strip():
            raise CharacterError("인물 이름의 형식이 올바르지 않습니다.")
        return name
    except NovelBibleError:
        raise CharacterError("인물 이름의 형식이 올바르지 않습니다.") from None


def _character(row: sqlite3.Row) -> BibleCharacter:
    try:
        item = BibleCharacter(
            row["character_id"], row["project_id"], row["name"],
            row["personality"], row["goal"], row["speech_style"],
            row["secret"], row["revision"], row["created_at"], row["updated_at"],
        )
        _id(item.character_id)
        _id(item.project_id)
        _name(item.name)
        _content(item.personality)
        _content(item.goal)
        _content(item.speech_style)
        _content(item.secret, optional=True)
        _revision(item.revision)
        for value in (item.created_at, item.updated_at):
            date = datetime.fromisoformat(value)
            if date.tzinfo is None:
                raise ValueError("missing timezone")
        return item
    except (TypeError, ValueError, KeyError, IndexError, OverflowError):
        raise CharacterError("저장된 인물 설정이 손상되었습니다.") from None


class CharacterStore(NovelBibleStore):
    """Extends the SAME local Novel Bible SQLite file with character canon.

    All mutations are explicit and serialized with BEGIN IMMEDIATE. Existing
    records require their current revision; the parent project revision is
    bumped for every character change. Secrets are never automatically logged.
    """

    def __init__(self, database_path: str | Path = ":memory:") -> None:
        super().__init__(database_path)
        with self._db:
            self._db.execute("""CREATE TABLE IF NOT EXISTS bible_characters (
                character_id TEXT PRIMARY KEY CHECK(length(character_id)=32),
                project_id TEXT NOT NULL REFERENCES bible_projects(project_id) ON DELETE CASCADE,
                name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 120),
                personality TEXT NOT NULL CHECK(length(personality) BETWEEN 1 AND 4000),
                goal TEXT NOT NULL CHECK(length(goal) BETWEEN 1 AND 4000),
                speech_style TEXT NOT NULL CHECK(length(speech_style) BETWEEN 1 AND 4000),
                secret TEXT NOT NULL CHECK(length(secret)<=4000),
                revision INTEGER NOT NULL CHECK(revision>=1),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(project_id, name)
            )""")
            self._db.execute("""CREATE INDEX IF NOT EXISTS ix_bible_characters_project
                                ON bible_characters(project_id)""")

    def create_character(
        self, project_id: str, *, name: str, personality: str, goal: str,
        speech_style: str, secret: str = "",
    ) -> BibleCharacter:
        project_id = _id(project_id)
        fields = (_name(name), _content(personality), _content(goal),
                  _content(speech_style), _content(secret, optional=True))
        character_id = uuid4().hex
        timestamp = _now()
        try:
            with self._db:
                self._db.execute("BEGIN IMMEDIATE")
                self.get_project(project_id)
                self._db.execute("""INSERT INTO bible_characters
                    (character_id, project_id, name, personality, goal, speech_style,
                     secret, revision, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                    (character_id, project_id, *fields, timestamp, timestamp))
                self._db.execute("""UPDATE bible_projects SET revision=revision+1
                                    WHERE project_id=?""", (project_id,))
        except sqlite3.IntegrityError:
            raise CharacterError("동일한 인물 이름이 있거나 인물 정보를 저장할 수 없습니다.") from None
        return self.get_character(project_id, character_id)

    def get_character(self, project_id: str, character_id: str) -> BibleCharacter:
        project_id, character_id = _id(project_id), _id(character_id)
        self.get_project(project_id)
        row = self._db.execute("""SELECT * FROM bible_characters
                                  WHERE project_id=? AND character_id=?""",
                               (project_id, character_id)).fetchone()
        if row is None:
            raise CharacterError("인물을 찾을 수 없습니다.")
        return _character(row)

    def list_characters(self, project_id: str) -> tuple[BibleCharacter, ...]:
        project_id = _id(project_id)
        self.get_project(project_id)
        return tuple(_character(row) for row in self._db.execute(
            """SELECT * FROM bible_characters WHERE project_id=?
               ORDER BY name, character_id""", (project_id,)))

    def update_character(
        self, project_id: str, character_id: str, *, expected_revision: int,
        name: str | None = None, personality: str | None = None,
        goal: str | None = None, speech_style: str | None = None,
        secret: str | None = None,
    ) -> BibleCharacter:
        project_id, character_id = _id(project_id), _id(character_id)
        expected_revision = _revision(expected_revision)
        if expected_revision >= 2**31 - 1:
            raise CharacterError("인물 설정 버전 한도에 도달했습니다.")
        changes: dict[str, str] = {}
        for field, value in (("name", name), ("personality", personality),
                             ("goal", goal), ("speech_style", speech_style),
                             ("secret", secret)):
            if value is not None:
                changes[field] = (_name(value) if field == "name" else
                                  _content(value, optional=field == "secret"))
        if not changes:
            raise CharacterError("수정할 인물 항목이 없습니다.")
        try:
            with self._db:
                self._db.execute("BEGIN IMMEDIATE")
                old = self.get_character(project_id, character_id)
                if old.revision != expected_revision:
                    raise CharacterError("인물 설정이 변경되었습니다. 최신 버전을 확인하세요.")
                assignments = ", ".join(f"{key}=?" for key in changes)
                self._db.execute(
                    f"UPDATE bible_characters SET {assignments}, revision=revision+1, "
                    "updated_at=? WHERE project_id=? AND character_id=? AND revision=?",
                    (*changes.values(), _now(), project_id, character_id, expected_revision))
                self._db.execute("""UPDATE bible_projects SET revision=revision+1
                                    WHERE project_id=?""", (project_id,))
        except sqlite3.IntegrityError:
            raise CharacterError("동일한 인물 이름이 있거나 인물 정보를 수정할 수 없습니다.") from None
        return self.get_character(project_id, character_id)

    def delete_character(self, project_id: str, character_id: str, *,
                         expected_revision: int) -> None:
        project_id, character_id = _id(project_id), _id(character_id)
        expected_revision = _revision(expected_revision)
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self.get_project(project_id)
            cursor = self._db.execute("""DELETE FROM bible_characters
                WHERE project_id=? AND character_id=? AND revision=?""",
                (project_id, character_id, expected_revision))
            if cursor.rowcount != 1:
                raise CharacterError("인물 설정이 변경되었거나 삭제되었습니다.")
            self._db.execute("""UPDATE bible_projects SET revision=revision+1
                                WHERE project_id=?""", (project_id,))
