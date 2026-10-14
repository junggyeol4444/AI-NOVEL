"""Stage 47 / ANF-REQ-037: explicitly authored, episode-indexed foreshadowing.

No model inference, reference-text ingestion, external requests or publication.
Only the owner's saved Novel Bible facts enter this local SQLite store.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sqlite3
from uuid import uuid4

from .novel_bible import NovelBibleError, NovelBibleStore, _id, _now, _revision, _text


class ForeshadowError(NovelBibleError):
    """Errors do not echo user-authored story details."""


ACTIONS = frozenset({"INSTALL", "REVISIT", "RESOLVE", "ABANDON"})
STATUSES = frozenset({"OPEN", "DEVELOPING", "RESOLVED", "ABANDONED"})
FINAL = frozenset({"RESOLVED", "ABANDONED"})
MAX_THREADS = 512
MAX_EVENTS = 4096


@dataclass(frozen=True)
class ForeshadowThread:
    project_id: str
    thread_id: str
    title: str
    revision: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ForeshadowEvent:
    project_id: str
    thread_id: str
    event_id: str
    episode: int
    sequence: int
    action: str
    note: str
    created_at: str


@dataclass(frozen=True)
class ForeshadowState:
    project_id: str
    thread_id: str
    requested_episode: int
    status: str  # NOT_INSTALLED before the first INSTALL; otherwise one of STATUSES
    effective_episode: int | None
    last_action: str | None
    revision: int


@dataclass(frozen=True)
class ForeshadowAudit:
    project_id: str
    thread_count: int
    event_count: int
    open_count: int
    developing_count: int
    resolved_count: int
    abandoned_count: int
    unfinished_thread_ids: tuple[str, ...]


def _episode(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 1_000_000:
        raise ForeshadowError("회차는 1 이상 1000000 이하의 정수여야 합니다.")
    return value


def _action(value: object) -> str:
    if type(value) is not str or value not in ACTIONS:
        raise ForeshadowError("복선 기록 유형이 올바르지 않습니다.")
    return value


def _title(value: object) -> str:
    try:
        return _text(value, title=True)
    except NovelBibleError:
        raise ForeshadowError("복선 제목 형식이 올바르지 않습니다.") from None


def _note(value: object) -> str:
    if type(value) is str and not value:
        return ""
    try:
        return _text(value)
    except NovelBibleError:
        raise ForeshadowError("복선 메모 형식이 올바르지 않습니다.") from None


def _stamp(value: object) -> None:
    try:
        if type(value) is not str:
            raise ValueError
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise ForeshadowError("저장된 복선 기록이 손상되었습니다.") from None


def _thread(row: sqlite3.Row) -> ForeshadowThread:
    try:
        item = ForeshadowThread(*(row[k] for k in (
            "project_id", "thread_id", "title", "revision", "created_at", "updated_at")))
        _id(item.project_id)
        _id(item.thread_id)
        _title(item.title)
        _revision(item.revision)
        _stamp(item.created_at)
        _stamp(item.updated_at)
        return item
    except (NovelBibleError, KeyError, IndexError, TypeError, ValueError, OverflowError):
        raise ForeshadowError("저장된 복선 기록이 손상되었습니다.") from None


def _event(row: sqlite3.Row) -> ForeshadowEvent:
    try:
        item = ForeshadowEvent(*(row[k] for k in (
            "project_id", "thread_id", "event_id", "episode", "sequence",
            "action", "note", "created_at")))
        _id(item.project_id)
        _id(item.thread_id)
        _id(item.event_id)
        _episode(item.episode)
        if type(item.sequence) is not int or not 1 <= item.sequence <= MAX_EVENTS:
            raise ValueError
        _action(item.action)
        _note(item.note)
        _stamp(item.created_at)
        return item
    except (NovelBibleError, KeyError, IndexError, TypeError, ValueError, OverflowError):
        raise ForeshadowError("저장된 복선 기록이 손상되었습니다.") from None


def _status_after(previous: str | None, action: str) -> str:
    """Strict finite-state machine; terminal statuses cannot be reopened."""
    if previous is None:
        if action == "INSTALL":
            return "OPEN"
    elif previous in ("OPEN", "DEVELOPING"):
        if action == "REVISIT":
            return "DEVELOPING"
        if action == "RESOLVE":
            return "RESOLVED"
        if action == "ABANDON":
            return "ABANDONED"
    raise ForeshadowError("복선 설치·재언급·회수·폐기 순서가 올바르지 않습니다.")


class ForeshadowStore(NovelBibleStore):
    """Project-isolated, transactional foreshadowing state machine.

    Chronology sorts by episode, then insertion sequence for same-episode events.
    Backfilled events are allowed only if the *whole* resulting history is valid.
    Thread revisions protect all timeline edits against stale concurrent writers.
    """

    def __init__(self, database_path: str | Path = ":memory:") -> None:
        super().__init__(database_path)
        with self._db:
            self._db.execute("""CREATE TABLE IF NOT EXISTS bible_foreshadow_threads (
                project_id TEXT NOT NULL REFERENCES bible_projects(project_id) ON DELETE CASCADE,
                thread_id TEXT NOT NULL CHECK(length(thread_id)=32),
                title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
                revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 2147483647),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(project_id, thread_id)
            )""")
            self._db.execute("""CREATE TABLE IF NOT EXISTS bible_foreshadow_events (
                project_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                event_id TEXT NOT NULL CHECK(length(event_id)=32),
                episode INTEGER NOT NULL CHECK(episode BETWEEN 1 AND 1000000),
                sequence INTEGER NOT NULL CHECK(sequence BETWEEN 1 AND 4096),
                action TEXT NOT NULL CHECK(action IN ('INSTALL','REVISIT','RESOLVE','ABANDON')),
                note TEXT NOT NULL CHECK(length(note) <= 4000),
                created_at TEXT NOT NULL,
                PRIMARY KEY(project_id, event_id),
                UNIQUE(project_id, thread_id, sequence),
                FOREIGN KEY(project_id, thread_id) REFERENCES
                    bible_foreshadow_threads(project_id, thread_id) ON DELETE CASCADE
            )""")
            self._db.execute("""CREATE INDEX IF NOT EXISTS ix_foreshadow_chronology
                ON bible_foreshadow_events(project_id, thread_id, episode, sequence)""")

    def _bump(self, project_id: str) -> None:
        self._db.execute("UPDATE bible_projects SET revision=revision+1 WHERE project_id=?",
                         (project_id,))

    def get_thread(self, project_id: str, thread_id: str) -> ForeshadowThread:
        project_id, thread_id = _id(project_id), _id(thread_id)
        self.get_project(project_id)
        row = self._db.execute("""SELECT * FROM bible_foreshadow_threads
            WHERE project_id=? AND thread_id=?""", (project_id, thread_id)).fetchone()
        if row is None:
            raise ForeshadowError("복선 항목을 찾을 수 없습니다.")
        return _thread(row)

    def list_threads(self, project_id: str) -> tuple[ForeshadowThread, ...]:
        project_id = _id(project_id)
        self.get_project(project_id)
        return tuple(_thread(row) for row in self._db.execute("""SELECT *
            FROM bible_foreshadow_threads WHERE project_id=? ORDER BY created_at, thread_id""",
            (project_id,)))

    def history(self, project_id: str, thread_id: str) -> tuple[ForeshadowEvent, ...]:
        project_id, thread_id = _id(project_id), _id(thread_id)
        self.get_thread(project_id, thread_id)
        return tuple(_event(row) for row in self._db.execute("""SELECT *
            FROM bible_foreshadow_events WHERE project_id=? AND thread_id=?
            ORDER BY episode, sequence""", (project_id, thread_id)))

    def _check_history(self, history: tuple[ForeshadowEvent, ...]) -> str:
        status: str | None = None
        if not history:
            raise ForeshadowError("복선 설치 기록이 없습니다.")
        for event in history:
            status = _status_after(status, event.action)
        assert status in STATUSES
        return status

    def audit(self, project_id: str) -> ForeshadowAudit:
        project_id = _id(project_id)
        threads = self.list_threads(project_id)
        if len(threads) > MAX_THREADS:
            raise ForeshadowError("복선 항목 검사 한도를 초과했습니다.")
        counts = {status: 0 for status in STATUSES}
        unfinished: list[str] = []
        total = 0
        for thread in threads:
            events = self.history(project_id, thread.thread_id)
            total += len(events)
            if total > MAX_EVENTS:
                raise ForeshadowError("복선 사건 검사 한도를 초과했습니다.")
            status = self._check_history(events)
            counts[status] += 1
            if status not in FINAL:
                unfinished.append(thread.thread_id)
        return ForeshadowAudit(project_id, len(threads), total, counts["OPEN"],
            counts["DEVELOPING"], counts["RESOLVED"], counts["ABANDONED"],
            tuple(unfinished))

    def get_at(self, project_id: str, thread_id: str, episode: int) -> ForeshadowState:
        episode = _episode(episode)
        thread = self.get_thread(project_id, thread_id)
        self.audit(project_id)  # fail closed on damaged/invalid timelines
        status: str | None = None
        effective: ForeshadowEvent | None = None
        for event in self.history(project_id, thread_id):
            if event.episode > episode:
                break
            status = _status_after(status, event.action)
            effective = event
        return ForeshadowState(thread.project_id, thread.thread_id, episode,
            status or "NOT_INSTALLED", effective.episode if effective else None,
            effective.action if effective else None, thread.revision)

    def _check_revision(self, project_id: str, thread_id: str,
                        expected_revision: int) -> ForeshadowThread:
        expected_revision = _revision(expected_revision)
        current = self.get_thread(project_id, thread_id)
        if current.revision != expected_revision or current.revision >= 2**31 - 1:
            raise ForeshadowError("복선 기록이 변경되었습니다. 최신 버전을 확인하세요.")
        return current

    def _touch(self, project_id: str, thread_id: str, expected_revision: int) -> None:
        cursor = self._db.execute("""UPDATE bible_foreshadow_threads
            SET revision=revision+1, updated_at=?
            WHERE project_id=? AND thread_id=? AND revision=?""",
            (_now(), project_id, thread_id, expected_revision))
        if cursor.rowcount != 1:
            raise ForeshadowError("복선 기록이 변경되었습니다. 최신 버전을 확인하세요.")
        self._bump(project_id)

    def create_thread(self, project_id: str, *, title: str, episode: int,
                      note: str = "") -> ForeshadowThread:
        project_id, title, episode, note = _id(project_id), _title(title), _episode(episode), _note(note)
        thread_id, event_id, now = uuid4().hex, uuid4().hex, _now()
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self.get_project(project_id)
            self._db.execute("""INSERT INTO bible_foreshadow_threads VALUES (?, ?, ?, 1, ?, ?)""",
                (project_id, thread_id, title, now, now))
            self._db.execute("""INSERT INTO bible_foreshadow_events VALUES
                (?, ?, ?, ?, 1, 'INSTALL', ?, ?)""",
                (project_id, thread_id, event_id, episode, note, now))
            self.audit(project_id)
            self._bump(project_id)
        return self.get_thread(project_id, thread_id)

    def add_event(self, project_id: str, thread_id: str, *, episode: int,
                  action: str, note: str = "", expected_revision: int) -> ForeshadowEvent:
        project_id, thread_id = _id(project_id), _id(thread_id)
        episode, action, note = _episode(episode), _action(action), _note(note)
        if action == "INSTALL":
            raise ForeshadowError("설치 기록은 복선 생성 시에만 추가할 수 있습니다.")
        event_id = uuid4().hex
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self._check_revision(project_id, thread_id, expected_revision)
            row = self._db.execute("""SELECT COALESCE(MAX(sequence),0) + 1 AS next
                FROM bible_foreshadow_events WHERE project_id=? AND thread_id=?""",
                (project_id, thread_id)).fetchone()
            if row["next"] > MAX_EVENTS:
                raise ForeshadowError("복선 사건 검사 한도를 초과했습니다.")
            self._db.execute("""INSERT INTO bible_foreshadow_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (project_id, thread_id, event_id, episode, row["next"], action, note, _now()))
            self.audit(project_id)
            self._touch(project_id, thread_id, expected_revision)
        return self.get_event(project_id, thread_id, event_id)

    def get_event(self, project_id: str, thread_id: str, event_id: str) -> ForeshadowEvent:
        project_id, thread_id, event_id = _id(project_id), _id(thread_id), _id(event_id)
        self.get_thread(project_id, thread_id)
        row = self._db.execute("""SELECT * FROM bible_foreshadow_events
            WHERE project_id=? AND thread_id=? AND event_id=?""",
            (project_id, thread_id, event_id)).fetchone()
        if row is None:
            raise ForeshadowError("복선 사건 기록을 찾을 수 없습니다.")
        return _event(row)

    def update_event(self, project_id: str, thread_id: str, event_id: str, *,
                     episode: int, action: str, note: str = "",
                     expected_revision: int) -> ForeshadowEvent:
        project_id, thread_id, event_id = _id(project_id), _id(thread_id), _id(event_id)
        episode, action, note = _episode(episode), _action(action), _note(note)
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self._check_revision(project_id, thread_id, expected_revision)
            current = self.get_event(project_id, thread_id, event_id)
            if (current.action == "INSTALL") != (action == "INSTALL"):
                raise ForeshadowError("설치 기록 유형은 변경할 수 없습니다.")
            self._db.execute("""UPDATE bible_foreshadow_events
                SET episode=?, action=?, note=? WHERE project_id=? AND thread_id=? AND event_id=?""",
                (episode, action, note, project_id, thread_id, event_id))
            self.audit(project_id)
            self._touch(project_id, thread_id, expected_revision)
        return self.get_event(project_id, thread_id, event_id)

    def delete_event(self, project_id: str, thread_id: str, event_id: str, *,
                     expected_revision: int) -> None:
        project_id, thread_id, event_id = _id(project_id), _id(thread_id), _id(event_id)
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self._check_revision(project_id, thread_id, expected_revision)
            event = self.get_event(project_id, thread_id, event_id)
            if event.action == "INSTALL":
                raise ForeshadowError("설치 기록은 삭제할 수 없습니다. 복선 항목을 삭제하세요.")
            self._db.execute("""DELETE FROM bible_foreshadow_events
                WHERE project_id=? AND thread_id=? AND event_id=?""",
                (project_id, thread_id, event_id))
            self.audit(project_id)
            self._touch(project_id, thread_id, expected_revision)

    def update_thread(self, project_id: str, thread_id: str, *, title: str,
                      expected_revision: int) -> ForeshadowThread:
        project_id, thread_id, title = _id(project_id), _id(thread_id), _title(title)
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self._check_revision(project_id, thread_id, expected_revision)
            self._db.execute("""UPDATE bible_foreshadow_threads SET title=?
                WHERE project_id=? AND thread_id=?""", (title, project_id, thread_id))
            self._touch(project_id, thread_id, expected_revision)
        return self.get_thread(project_id, thread_id)

    def delete_thread(self, project_id: str, thread_id: str, *,
                      expected_revision: int) -> None:
        project_id, thread_id = _id(project_id), _id(thread_id)
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self._check_revision(project_id, thread_id, expected_revision)
            cursor = self._db.execute("""DELETE FROM bible_foreshadow_threads
                WHERE project_id=? AND thread_id=? AND revision=?""",
                (project_id, thread_id, expected_revision))
            if cursor.rowcount != 1:
                raise ForeshadowError("복선 기록이 변경되었습니다. 최신 버전을 확인하세요.")
            self.audit(project_id)
            self._bump(project_id)
