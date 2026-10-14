"""Stage 43 (ANF-REQ-033): episode-indexed, explicitly authored character knowledge.

This is a *structured canon checker*, not an NLP detector: callers must label
which fact IDs a character uses in a scene. An absent knowledge event is NOT
permission to use a fact. Nothing is inferred from reference novels or sent out.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sqlite3
from uuid import uuid4

from .characters import CharacterStore
from .novel_bible import NovelBibleError, _id, _now, _revision, _text


class KnowledgeError(NovelBibleError):
    """User-content-free validation and consistency error."""


@dataclass(frozen=True)
class KnowledgeFact:
    fact_id: str
    project_id: str
    description: str
    revision: int
    created_at: str


@dataclass(frozen=True)
class KnowledgeEvent:
    project_id: str
    character_id: str
    fact_id: str
    episode: int
    knows: bool
    revision: int
    updated_at: str


@dataclass(frozen=True)
class KnowledgeState:
    project_id: str
    character_id: str
    fact_id: str
    episode: int
    knows: bool
    status: str  # known, not_recorded, not_yet_learned, not_known
    effective_episode: int | None


@dataclass(frozen=True)
class KnowledgeViolation:
    fact_id: str
    reason: str  # not_recorded, not_yet_learned, not_known


@dataclass(frozen=True)
class KnowledgeCheck:
    project_id: str
    character_id: str
    episode: int
    allowed: bool
    violations: tuple[KnowledgeViolation, ...]


def _episode(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 1_000_000:
        raise KnowledgeError("회차는 1 이상 1000000 이하의 정수여야 합니다.")
    return value


def _description(value: object) -> str:
    try:
        return _text(value)
    except NovelBibleError:
        raise KnowledgeError("지식 사실의 형식 또는 길이가 올바르지 않습니다.") from None


def _timestamp(value: object) -> None:
    if type(value) is not str:
        raise KnowledgeError("저장된 지식 기록이 손상되었습니다.")
    try:
        date = datetime.fromisoformat(value)
    except (ValueError, OverflowError):
        raise KnowledgeError("저장된 지식 기록이 손상되었습니다.") from None
    if date.tzinfo is None or date.utcoffset() is None:
        raise KnowledgeError("저장된 지식 기록이 손상되었습니다.")


def _fact(row: sqlite3.Row) -> KnowledgeFact:
    try:
        item = KnowledgeFact(row["fact_id"], row["project_id"], row["description"],
                             row["revision"], row["created_at"])
        _id(item.fact_id)
        _id(item.project_id)
        _description(item.description)
        _revision(item.revision)
        _timestamp(item.created_at)
        return item
    except (NovelBibleError, TypeError, KeyError, IndexError, OverflowError):
        raise KnowledgeError("저장된 지식 사실이 손상되었습니다.") from None


def _event(row: sqlite3.Row) -> KnowledgeEvent:
    try:
        raw = row["knows"]
        if type(raw) is not int or raw not in (0, 1):
            raise KnowledgeError("저장된 지식 기록이 손상되었습니다.")
        item = KnowledgeEvent(row["project_id"], row["character_id"],
                              row["fact_id"], row["episode"], bool(raw),
                              row["revision"], row["updated_at"])
        _id(item.project_id)
        _id(item.character_id)
        _id(item.fact_id)
        _episode(item.episode)
        _revision(item.revision)
        _timestamp(item.updated_at)
        return item
    except (NovelBibleError, TypeError, KeyError, IndexError, OverflowError):
        raise KnowledgeError("저장된 지식 기록이 손상되었습니다.") from None


class CharacterKnowledgeStore(CharacterStore):
    """Novel Bible project/character-scoped facts and episode transitions.

    A fact is immutable to avoid silently changing the meaning of past events.
    Corrections require explicit deletion (which cascades events) and re-entry.
    Each transition applies from its episode until the next transition. An
    unknown or unrecorded fact always fails a usage check (fail closed).
    """

    def __init__(self, database_path: str | Path = ":memory:") -> None:
        super().__init__(database_path)
        with self._db:
            # Composite FKs prevent cross-project event links even for raw SQL.
            self._db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS
                ux_bible_characters_project_character
                ON bible_characters(project_id, character_id)""")
            self._db.execute("""CREATE TABLE IF NOT EXISTS bible_knowledge_facts (
                fact_id TEXT PRIMARY KEY CHECK(length(fact_id)=32),
                project_id TEXT NOT NULL REFERENCES bible_projects(project_id) ON DELETE CASCADE,
                description TEXT NOT NULL CHECK(length(description) BETWEEN 1 AND 4000),
                revision INTEGER NOT NULL DEFAULT 1 CHECK(revision=1),
                created_at TEXT NOT NULL,
                UNIQUE(project_id, fact_id)
            )""")
            self._db.execute("""CREATE INDEX IF NOT EXISTS ix_bible_knowledge_facts_project
                ON bible_knowledge_facts(project_id)""")
            self._db.execute("""CREATE TABLE IF NOT EXISTS bible_knowledge_events (
                project_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                fact_id TEXT NOT NULL,
                episode INTEGER NOT NULL CHECK(episode BETWEEN 1 AND 1000000),
                knows INTEGER NOT NULL CHECK(knows IN (0,1)),
                revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 2147483647),
                updated_at TEXT NOT NULL,
                PRIMARY KEY(project_id, character_id, fact_id, episode),
                FOREIGN KEY(project_id, character_id)
                    REFERENCES bible_characters(project_id, character_id) ON DELETE CASCADE,
                FOREIGN KEY(project_id, fact_id)
                    REFERENCES bible_knowledge_facts(project_id, fact_id) ON DELETE CASCADE
            )""")
            self._db.execute("""CREATE INDEX IF NOT EXISTS ix_bible_knowledge_timeline
                ON bible_knowledge_events(project_id, character_id, fact_id, episode DESC)""")

    def _bump(self, project_id: str) -> None:
        self._db.execute("UPDATE bible_projects SET revision=revision+1 WHERE project_id=?",
                         (project_id,))

    def create_fact(self, project_id: str, description: str) -> KnowledgeFact:
        project_id, description = _id(project_id), _description(description)
        fact_id = uuid4().hex
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self.get_project(project_id)
            self._db.execute("""INSERT INTO bible_knowledge_facts
                (fact_id, project_id, description, revision, created_at)
                VALUES (?, ?, ?, 1, ?)""", (fact_id, project_id, description, _now()))
            self._bump(project_id)
        return self.get_fact(project_id, fact_id)

    def get_fact(self, project_id: str, fact_id: str) -> KnowledgeFact:
        project_id, fact_id = _id(project_id), _id(fact_id)
        self.get_project(project_id)
        row = self._db.execute("""SELECT * FROM bible_knowledge_facts
            WHERE project_id=? AND fact_id=?""", (project_id, fact_id)).fetchone()
        if row is None:
            raise KnowledgeError("해당 작품의 지식 사실을 찾을 수 없습니다.")
        return _fact(row)

    def list_facts(self, project_id: str) -> tuple[KnowledgeFact, ...]:
        project_id = _id(project_id)
        self.get_project(project_id)
        return tuple(_fact(row) for row in self._db.execute("""SELECT * FROM bible_knowledge_facts
            WHERE project_id=? ORDER BY created_at, fact_id""", (project_id,)))

    def delete_fact(self, project_id: str, fact_id: str, *, expected_revision: int) -> None:
        project_id, fact_id = _id(project_id), _id(fact_id)
        expected_revision = _revision(expected_revision)
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self.get_project(project_id)
            cursor = self._db.execute("""DELETE FROM bible_knowledge_facts
                WHERE project_id=? AND fact_id=? AND revision=?""",
                (project_id, fact_id, expected_revision))
            if cursor.rowcount != 1:
                raise KnowledgeError("지식 사실이 변경되었거나 삭제되었습니다.")
            self._bump(project_id)

    def save_event(self, project_id: str, character_id: str, fact_id: str,
                   episode: int, *, knows: bool, expected_revision: int | None = None
                   ) -> KnowledgeEvent:
        project_id, character_id, fact_id = _id(project_id), _id(character_id), _id(fact_id)
        episode = _episode(episode)
        if type(knows) is not bool:
            raise KnowledgeError("지식 상태는 참 또는 거짓이어야 합니다.")
        if expected_revision is not None:
            expected_revision = _revision(expected_revision)
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self.get_character(project_id, character_id)
            self.get_fact(project_id, fact_id)
            row = self._db.execute("""SELECT revision FROM bible_knowledge_events
                WHERE project_id=? AND character_id=? AND fact_id=? AND episode=?""",
                (project_id, character_id, fact_id, episode)).fetchone()
            if row is None:
                if expected_revision is not None:
                    raise KnowledgeError("지식 기록이 변경되었거나 삭제되었습니다.")
                self._db.execute("""INSERT INTO bible_knowledge_events
                    (project_id, character_id, fact_id, episode, knows, revision, updated_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?)""",
                    (project_id, character_id, fact_id, episode, int(knows), _now()))
            else:
                current = _revision(row["revision"])
                if current != expected_revision:
                    raise KnowledgeError("지식 기록이 변경되었습니다. 최신 버전을 확인하세요.")
                if current == 2**31 - 1:
                    raise KnowledgeError("지식 기록 버전 한도에 도달했습니다.")
                self._db.execute("""UPDATE bible_knowledge_events
                    SET knows=?, revision=revision+1, updated_at=?
                    WHERE project_id=? AND character_id=? AND fact_id=? AND episode=?""",
                    (int(knows), _now(), project_id, character_id, fact_id, episode))
            self._bump(project_id)
        return self.get_event(project_id, character_id, fact_id, episode)

    def get_event(self, project_id: str, character_id: str, fact_id: str,
                  episode: int) -> KnowledgeEvent:
        project_id, character_id, fact_id = _id(project_id), _id(character_id), _id(fact_id)
        episode = _episode(episode)
        self.get_character(project_id, character_id)
        self.get_fact(project_id, fact_id)
        row = self._db.execute("""SELECT * FROM bible_knowledge_events
            WHERE project_id=? AND character_id=? AND fact_id=? AND episode=?""",
            (project_id, character_id, fact_id, episode)).fetchone()
        if row is None:
            raise KnowledgeError("지식 기록을 찾을 수 없습니다.")
        return _event(row)

    def list_events(self, project_id: str, character_id: str, *,
                    fact_id: str | None = None) -> tuple[KnowledgeEvent, ...]:
        project_id, character_id = _id(project_id), _id(character_id)
        self.get_character(project_id, character_id)
        if fact_id is not None:
            fact_id = _id(fact_id)
            self.get_fact(project_id, fact_id)
            rows = self._db.execute("""SELECT * FROM bible_knowledge_events
                WHERE project_id=? AND character_id=? AND fact_id=?
                ORDER BY episode, fact_id""", (project_id, character_id, fact_id))
        else:
            rows = self._db.execute("""SELECT * FROM bible_knowledge_events
                WHERE project_id=? AND character_id=? ORDER BY episode, fact_id""",
                (project_id, character_id))
        return tuple(_event(row) for row in rows)

    def delete_event(self, project_id: str, character_id: str, fact_id: str,
                     episode: int, *, expected_revision: int) -> None:
        project_id, character_id, fact_id = _id(project_id), _id(character_id), _id(fact_id)
        episode, expected_revision = _episode(episode), _revision(expected_revision)
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self.get_character(project_id, character_id)
            self.get_fact(project_id, fact_id)
            cursor = self._db.execute("""DELETE FROM bible_knowledge_events
                WHERE project_id=? AND character_id=? AND fact_id=? AND episode=? AND revision=?""",
                (project_id, character_id, fact_id, episode, expected_revision))
            if cursor.rowcount != 1:
                raise KnowledgeError("지식 기록이 변경되었거나 삭제되었습니다.")
            self._bump(project_id)

    def knowledge_at(self, project_id: str, character_id: str, fact_id: str,
                     episode: int) -> KnowledgeState:
        project_id, character_id, fact_id = _id(project_id), _id(character_id), _id(fact_id)
        episode = _episode(episode)
        self.get_character(project_id, character_id)
        self.get_fact(project_id, fact_id)
        row = self._db.execute("""SELECT * FROM bible_knowledge_events
            WHERE project_id=? AND character_id=? AND fact_id=? AND episode<=?
            ORDER BY episode DESC LIMIT 1""",
            (project_id, character_id, fact_id, episode)).fetchone()
        if row is not None:
            event = _event(row)
            status = "known" if event.knows else "not_known"
            return KnowledgeState(project_id, character_id, fact_id, episode,
                                  event.knows, status, event.episode)
        upcoming = self._db.execute("""SELECT * FROM bible_knowledge_events
            WHERE project_id=? AND character_id=? AND fact_id=? AND episode>?
            ORDER BY episode LIMIT 1""",
            (project_id, character_id, fact_id, episode)).fetchone()
        if upcoming is not None:
            _event(upcoming)  # fail closed on corrupt future events
        status = "not_yet_learned" if upcoming is not None and bool(upcoming["knows"]) else "not_recorded"
        return KnowledgeState(project_id, character_id, fact_id, episode, False, status, None)

    def check_uses(self, project_id: str, character_id: str, episode: int,
                   fact_ids: tuple[str, ...] | list[str]) -> KnowledgeCheck:
        project_id, character_id, episode = _id(project_id), _id(character_id), _episode(episode)
        if (type(fact_ids) not in (tuple, list) or not 1 <= len(fact_ids) <= 100
                or any(type(value) is not str for value in fact_ids)
                or len(set(fact_ids)) != len(fact_ids)):
            raise KnowledgeError("검사할 지식 식별자는 1~100개의 서로 다른 ID여야 합니다.")
        self.get_character(project_id, character_id)
        violations = []
        for fact_id in fact_ids:
            state = self.knowledge_at(project_id, character_id, fact_id, episode)
            if not state.knows:
                violations.append(KnowledgeViolation(fact_id, state.status))
        return KnowledgeCheck(project_id, character_id, episode,
                              not violations, tuple(violations))

    def require_known(self, project_id: str, character_id: str, episode: int,
                      fact_ids: tuple[str, ...] | list[str]) -> None:
        """Block a structured scene use unless ALL referenced facts are known."""
        if not self.check_uses(project_id, character_id, episode, fact_ids).allowed:
            raise KnowledgeError("인물이 해당 회차에 알지 못하는 정보가 포함되어 있습니다.")
