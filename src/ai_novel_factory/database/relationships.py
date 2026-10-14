"""Stage 45 / ANF-REQ-035: explicitly authored, episode-indexed character relationships.

Pairs are unordered: A--B and B--A represent the same shared relationship.
This models a *shared* relationship description, not each person's private view.
Transitions are effective from their episode until the next saved transition.
No reference novel data, model inference, network requests or publication.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sqlite3

from .characters import CharacterStore
from .novel_bible import NovelBibleError, _id, _now, _revision, _text


class RelationshipError(NovelBibleError):
    """Does not echo user-authored descriptions, secrets or identifiers."""


@dataclass(frozen=True)
class RelationshipEvent:
    project_id: str
    first_character_id: str
    second_character_id: str
    episode: int
    relationship: str
    notes: str
    revision: int
    updated_at: str


@dataclass(frozen=True)
class RelationshipState:
    project_id: str
    first_character_id: str
    second_character_id: str
    requested_episode: int
    status: str  # 'recorded' or 'not_recorded'
    effective_episode: int | None
    relationship: str | None
    notes: str | None
    revision: int | None


def _episode(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 1_000_000:
        raise RelationshipError("회차는 1 이상 1000000 이하의 정수여야 합니다.")
    return value


def _pair(first: object, second: object) -> tuple[str, str]:
    try:
        a, b = _id(first), _id(second)
    except NovelBibleError:
        raise RelationshipError("인물 식별자가 올바르지 않습니다.") from None
    if a == b:
        raise RelationshipError("동일 인물끼리 관계를 기록할 수 없습니다.")
    return tuple(sorted((a, b)))


def _relationship(value: object) -> str:
    try:
        return _text(value)
    except NovelBibleError:
        raise RelationshipError("관계 내용의 형식 또는 길이가 올바르지 않습니다.") from None


def _notes(value: object) -> str:
    if type(value) is str and value == "":
        return ""
    try:
        return _text(value)
    except NovelBibleError:
        raise RelationshipError("관계 메모의 형식 또는 길이가 올바르지 않습니다.") from None


def _event(row: sqlite3.Row) -> RelationshipEvent:
    try:
        obj = RelationshipEvent(row["project_id"], row["first_character_id"],
            row["second_character_id"], row["episode"], row["relationship"],
            row["notes"], row["revision"], row["updated_at"])
        _id(obj.project_id)
        if _pair(obj.first_character_id, obj.second_character_id) != (
                obj.first_character_id, obj.second_character_id):
            raise RelationshipError("저장된 인물 관계 기록이 손상되었습니다.")
        _episode(obj.episode)
        _relationship(obj.relationship)
        _notes(obj.notes)
        _revision(obj.revision)
        if type(obj.updated_at) is not str:
            raise ValueError("invalid timestamp")
        stamp = datetime.fromisoformat(obj.updated_at)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("timezone required")
        return obj
    except (NovelBibleError, TypeError, ValueError, KeyError, IndexError, OverflowError):
        raise RelationshipError("저장된 인물 관계 기록이 손상되었습니다.") from None


class RelationshipStore(CharacterStore):
    """Project-isolated SQLite timeline of user-supplied relationship canon.

    A relation at episode E supersedes the previous event at E or earlier.
    No earlier event means 'not_recorded', NOT friendship or any other guess.
    Every mutation uses an immediate transaction and bumps Novel Bible revision.
    """

    def __init__(self, database_path: str | Path = ":memory:") -> None:
        super().__init__(database_path)
        with self._db:
            self._db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS
                ux_relationship_characters_project_id
                ON bible_characters(project_id, character_id)""")
            self._db.execute("""CREATE TABLE IF NOT EXISTS bible_relationship_events (
                project_id TEXT NOT NULL REFERENCES bible_projects(project_id) ON DELETE CASCADE,
                first_character_id TEXT NOT NULL,
                second_character_id TEXT NOT NULL,
                episode INTEGER NOT NULL CHECK(episode BETWEEN 1 AND 1000000),
                relationship TEXT NOT NULL CHECK(length(relationship) BETWEEN 1 AND 4000),
                notes TEXT NOT NULL CHECK(length(notes) <= 4000),
                revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 2147483647),
                updated_at TEXT NOT NULL,
                PRIMARY KEY(project_id, first_character_id, second_character_id, episode),
                CHECK(first_character_id < second_character_id),
                FOREIGN KEY(project_id, first_character_id)
                    REFERENCES bible_characters(project_id, character_id) ON DELETE CASCADE,
                FOREIGN KEY(project_id, second_character_id)
                    REFERENCES bible_characters(project_id, character_id) ON DELETE CASCADE
            )""")
            self._db.execute("""CREATE INDEX IF NOT EXISTS ix_bible_relationship_timeline
                ON bible_relationship_events(project_id, first_character_id,
                    second_character_id, episode DESC)""")

    def _bump_relationship_project(self, project_id: str) -> None:
        self._db.execute("UPDATE bible_projects SET revision=revision+1 WHERE project_id=?",
                         (project_id,))

    def save_relation(self, project_id: str, first_character_id: str,
                      second_character_id: str, episode: int, *, relationship: str,
                      notes: str = "", expected_revision: int | None = None
                      ) -> RelationshipEvent:
        project_id = _id(project_id)
        a, b = _pair(first_character_id, second_character_id)
        episode = _episode(episode)
        relationship, notes = _relationship(relationship), _notes(notes)
        if expected_revision is not None:
            expected_revision = _revision(expected_revision)
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self.get_character(project_id, a)
            self.get_character(project_id, b)
            row = self._db.execute("""SELECT revision FROM bible_relationship_events
                WHERE project_id=? AND first_character_id=? AND second_character_id=?
                AND episode=?""", (project_id, a, b, episode)).fetchone()
            if row is None:
                if expected_revision is not None:
                    raise RelationshipError("관계 기록이 변경되었거나 삭제되었습니다.")
                self._db.execute("""INSERT INTO bible_relationship_events
                    (project_id, first_character_id, second_character_id, episode,
                     relationship, notes, revision, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
                    (project_id, a, b, episode, relationship, notes, _now()))
            else:
                current = _revision(row["revision"])
                if expected_revision != current:
                    raise RelationshipError("관계 기록이 변경되었습니다. 최신 버전을 확인하세요.")
                if current == 2**31 - 1:
                    raise RelationshipError("관계 기록 버전 한도에 도달했습니다.")
                cursor = self._db.execute("""UPDATE bible_relationship_events
                    SET relationship=?, notes=?, revision=revision+1, updated_at=?
                    WHERE project_id=? AND first_character_id=? AND second_character_id=?
                    AND episode=? AND revision=?""",
                    (relationship, notes, _now(), project_id, a, b, episode, current))
                if cursor.rowcount != 1:
                    raise RelationshipError("관계 기록이 변경되었습니다. 최신 버전을 확인하세요.")
            self._bump_relationship_project(project_id)
        return self.get_event(project_id, a, b, episode)

    def get_event(self, project_id: str, first_character_id: str,
                  second_character_id: str, episode: int) -> RelationshipEvent:
        project_id = _id(project_id)
        a, b = _pair(first_character_id, second_character_id)
        episode = _episode(episode)
        self.get_character(project_id, a)
        self.get_character(project_id, b)
        row = self._db.execute("""SELECT * FROM bible_relationship_events
            WHERE project_id=? AND first_character_id=? AND second_character_id=?
            AND episode=?""", (project_id, a, b, episode)).fetchone()
        if row is None:
            raise RelationshipError("해당 회차의 관계 기록을 찾을 수 없습니다.")
        return _event(row)

    def history(self, project_id: str, first_character_id: str,
                second_character_id: str) -> tuple[RelationshipEvent, ...]:
        project_id = _id(project_id)
        a, b = _pair(first_character_id, second_character_id)
        self.get_character(project_id, a)
        self.get_character(project_id, b)
        return tuple(_event(row) for row in self._db.execute("""SELECT *
            FROM bible_relationship_events WHERE project_id=? AND first_character_id=?
            AND second_character_id=? ORDER BY episode""", (project_id, a, b)))

    def get_at(self, project_id: str, first_character_id: str,
               second_character_id: str, episode: int) -> RelationshipState:
        project_id = _id(project_id)
        a, b = _pair(first_character_id, second_character_id)
        episode = _episode(episode)
        self.get_character(project_id, a)
        self.get_character(project_id, b)
        row = self._db.execute("""SELECT * FROM bible_relationship_events
            WHERE project_id=? AND first_character_id=? AND second_character_id=?
            AND episode<=? ORDER BY episode DESC LIMIT 1""",
            (project_id, a, b, episode)).fetchone()
        if row is None:
            return RelationshipState(project_id, a, b, episode, "not_recorded",
                                     None, None, None, None)
        item = _event(row)
        return RelationshipState(project_id, a, b, episode, "recorded", item.episode,
                                 item.relationship, item.notes, item.revision)

    def list_at(self, project_id: str, episode: int) -> tuple[RelationshipState, ...]:
        """One effective relation per unordered pair, omitting unrecorded pairs."""
        project_id, episode = _id(project_id), _episode(episode)
        self.get_project(project_id)
        rows = self._db.execute("""SELECT e.* FROM bible_relationship_events e
            WHERE e.project_id=? AND e.episode=(
                SELECT MAX(l.episode) FROM bible_relationship_events l
                WHERE l.project_id=e.project_id
                  AND l.first_character_id=e.first_character_id
                  AND l.second_character_id=e.second_character_id
                  AND l.episode<=?)
            ORDER BY e.first_character_id, e.second_character_id""",
            (project_id, episode))
        result = []
        for row in rows:
            item = _event(row)
            result.append(RelationshipState(project_id, item.first_character_id,
                item.second_character_id, episode, "recorded", item.episode,
                item.relationship, item.notes, item.revision))
        return tuple(result)

    def delete_event(self, project_id: str, first_character_id: str,
                     second_character_id: str, episode: int, *,
                     expected_revision: int) -> None:
        project_id = _id(project_id)
        a, b = _pair(first_character_id, second_character_id)
        episode, expected_revision = _episode(episode), _revision(expected_revision)
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self.get_character(project_id, a)
            self.get_character(project_id, b)
            cursor = self._db.execute("""DELETE FROM bible_relationship_events
                WHERE project_id=? AND first_character_id=? AND second_character_id=?
                AND episode=? AND revision=?""",
                (project_id, a, b, episode, expected_revision))
            if cursor.rowcount != 1:
                raise RelationshipError("관계 기록이 변경되었거나 삭제되었습니다.")
            self._bump_relationship_project(project_id)
