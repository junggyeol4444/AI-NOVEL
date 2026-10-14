"""Stage 46 / ANF-REQ-036: local, explicitly authored event chronology.

Absolute dates are UTC *day intervals*, not fabricated midnight instants.
Timezone-aware datetimes are precise instants. Relative offsets use whole minutes.
A precedence edge is strict; cycles or provably impossible dates are rejected
atomically. Overlapping date intervals are intentionally inconclusive.
No manuscript inference, reference-text ingestion, network or publication.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from .novel_bible import NovelBibleStore, NovelBibleError, _id, _now, _revision, _text


class TimelineError(NovelBibleError):
    """Errors never contain user-authored titles, dates or identifiers."""


@dataclass(frozen=True)
class TimelineEvent:
    project_id: str
    event_id: str
    title: str
    when: str | None
    anchor_event_id: str | None
    offset_minutes: int | None
    revision: int
    updated_at: str


@dataclass(frozen=True)
class TimelineAudit:
    project_id: str
    event_count: int
    precedence_count: int
    unresolved_event_ids: tuple[str, ...]
    # Strict, explicit + inferred relative chronological constraints checked.
    checked_pairs: int


_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_MAX_OFFSET = 525_600_000  # 1000 years, in minutes


def _when(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str or len(value) > 64:
        raise TimelineError("사건 날짜 또는 시간 형식이 올바르지 않습니다.")
    try:
        if _DATE_RE.fullmatch(value):
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError
            return value
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None or stamp.utcoffset() is None or stamp.microsecond:
            raise ValueError
        return stamp.astimezone(timezone.utc).isoformat(timespec="seconds")
    except (ValueError, OverflowError, TypeError):
        raise TimelineError("사건 날짜 또는 시간 형식이 올바르지 않습니다.") from None


def _offset(value: object) -> int:
    if type(value) is not int or not -_MAX_OFFSET <= value <= _MAX_OFFSET:
        raise TimelineError("상대시간은 허용 범위의 정수 분 단위여야 합니다.")
    return value


def _title(value: object) -> str:
    try:
        return _text(value, title=True)
    except NovelBibleError:
        raise TimelineError("사건 제목 형식이 올바르지 않습니다.") from None


def _event(row: sqlite3.Row) -> TimelineEvent:
    try:
        item = TimelineEvent(*(row[key] for key in (
            "project_id", "event_id", "title", "when_value", "anchor_event_id",
            "offset_minutes", "revision", "updated_at")))
        _id(item.project_id)
        _id(item.event_id)
        _title(item.title)
        _when(item.when)
        if (item.anchor_event_id is None) != (item.offset_minutes is None):
            raise ValueError
        if item.anchor_event_id is not None:
            _id(item.anchor_event_id)
            _offset(item.offset_minutes)
        if item.when is not None and item.anchor_event_id is not None:
            raise ValueError
        _revision(item.revision)
        stamp = datetime.fromisoformat(item.updated_at)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError
        return item
    except (ValueError, TypeError, KeyError, IndexError, OverflowError):
        raise TimelineError("저장된 사건 기록이 손상되었습니다.") from None


def _interval(value: str) -> tuple[datetime, datetime]:
    if _DATE_RE.fullmatch(value):
        start = datetime.combine(date.fromisoformat(value), datetime.min.time(), timezone.utc)
        # An inclusive end would mishandle same-day, time-unknown events.
        return start, start + timedelta(days=1)
    stamp = datetime.fromisoformat(value)
    return stamp, stamp


class EventTimelineStore(NovelBibleStore):
    """Project-scoped SQLite event facts with transactional chronology validation."""

    def __init__(self, database_path: str | Path = ":memory:") -> None:
        super().__init__(database_path)
        with self._db:
            self._db.execute("""CREATE TABLE IF NOT EXISTS bible_timeline_events (
                project_id TEXT NOT NULL REFERENCES bible_projects(project_id) ON DELETE CASCADE,
                event_id TEXT NOT NULL CHECK(length(event_id)=32),
                title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
                when_value TEXT,
                anchor_event_id TEXT,
                offset_minutes INTEGER CHECK(offset_minutes BETWEEN -525600000 AND 525600000),
                revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 2147483647),
                updated_at TEXT NOT NULL,
                PRIMARY KEY(project_id, event_id),
                CHECK((anchor_event_id IS NULL) = (offset_minutes IS NULL)),
                CHECK(when_value IS NULL OR anchor_event_id IS NULL)
            )""")
            self._db.execute("""CREATE TABLE IF NOT EXISTS bible_timeline_order (
                project_id TEXT NOT NULL REFERENCES bible_projects(project_id) ON DELETE CASCADE,
                before_id TEXT NOT NULL,
                after_id TEXT NOT NULL,
                PRIMARY KEY(project_id, before_id, after_id),
                CHECK(before_id <> after_id),
                FOREIGN KEY(project_id, before_id) REFERENCES
                    bible_timeline_events(project_id, event_id) ON DELETE CASCADE,
                FOREIGN KEY(project_id, after_id) REFERENCES
                    bible_timeline_events(project_id, event_id) ON DELETE CASCADE
            )""")
            self._db.execute("""CREATE INDEX IF NOT EXISTS ix_timeline_anchor
                ON bible_timeline_events(project_id, anchor_event_id)""")

    def _bump(self, project_id: str) -> None:
        self._db.execute("UPDATE bible_projects SET revision=revision+1 WHERE project_id=?",
                         (project_id,))

    def _read_events(self, project_id: str) -> dict[str, TimelineEvent]:
        return {event.event_id: event for event in (
            _event(row) for row in self._db.execute(
                "SELECT * FROM bible_timeline_events WHERE project_id=? ORDER BY event_id",
                (project_id,)))}

    def audit(self, project_id: str) -> TimelineAudit:
        """Raise TimelineError on cycles, dangling anchors, or impossible strict order.

        The validator intentionally does not guess ordering of unresolved/overlapping
        dates. A relative chain rooted in an unknown date remains unresolved.
        """
        project_id = _id(project_id)
        self.get_project(project_id)
        events = self._read_events(project_id)
        if len(events) > 512:
            raise TimelineError("작품당 사건 검사 한도(512개)를 초과했습니다.")
        intervals: dict[str, tuple[datetime, datetime] | None] = {}
        visiting: set[str] = set()

        def resolve(uid: str) -> tuple[datetime, datetime] | None:
            if uid in intervals:
                return intervals[uid]
            if uid in visiting:
                raise TimelineError("사건 상대시간 참조가 순환합니다.")
            if uid not in events:
                raise TimelineError("사건 상대시간 참조가 존재하지 않습니다.")
            visiting.add(uid)
            item = events[uid]
            if item.when is not None:
                try:
                    result = _interval(item.when)
                except (OverflowError, ValueError):
                    raise TimelineError("사건 날짜 계산 범위를 벗어났습니다.") from None
            elif item.anchor_event_id is not None:
                anchor = resolve(item.anchor_event_id)
                if anchor is None:
                    result = None
                else:
                    try:
                        shift = timedelta(minutes=item.offset_minutes)
                        result = (anchor[0] + shift, anchor[1] + shift)
                    except OverflowError:
                        raise TimelineError("상대시간 계산 범위를 벗어났습니다.") from None
            else:
                result = None
            visiting.remove(uid)
            intervals[uid] = result
            return result

        for uid in events:
            resolve(uid)

        graph: dict[str, set[str]] = {uid: set() for uid in events}
        count = 0
        for row in self._db.execute("""SELECT before_id, after_id FROM bible_timeline_order
            WHERE project_id=? ORDER BY before_id, after_id""", (project_id,)):
            before, after = row["before_id"], row["after_id"]
            if before not in events or after not in events:
                raise TimelineError("사건 순서 참조가 존재하지 않습니다.")
            graph[before].add(after)
            count += 1
            if count > 2048:
                raise TimelineError("사건 순서 검사 한도(2048개)를 초과했습니다.")
        # Resolve each relative chain into (root event, total minute offset).
        # Two events anchored to the same root have a known relative order
        # even if the root has NO absolute date. Equal offsets mean simultaneity.
        relative_positions: dict[str, tuple[str, int]] = {}

        def position(uid: str) -> tuple[str, int]:
            if uid in relative_positions:
                return relative_positions[uid]
            item = events[uid]
            if item.anchor_event_id is None:
                result = (uid, 0)
            else:
                root, minutes = position(item.anchor_event_id)
                result = (root, minutes + item.offset_minutes)
            relative_positions[uid] = result
            return result

        for uid in events:
            position(uid)
        groups: dict[str, list[tuple[int, str]]] = {}
        for uid, (root, minutes) in relative_positions.items():
            groups.setdefault(root, []).append((minutes, uid))
        for group in groups.values():
            group.sort()
            for i, (first_minute, before) in enumerate(group):
                for second_minute, after in group[i + 1:]:
                    if first_minute < second_minute:
                        graph[before].add(after)
        state: dict[str, int] = {}
        checked: set[tuple[str, str]] = set()

        def same_instant_root(uid: str) -> tuple[str, int]:
            return relative_positions[uid]

        def walk(uid: str) -> set[str]:
            if state.get(uid) == 1:
                raise TimelineError("사건 순서가 순환합니다.")
            if state.get(uid) == 2:
                return closure[uid]
            state[uid] = 1
            reachable: set[str] = set()
            for next_uid in graph[uid]:
                reachable.add(next_uid)
                reachable.update(walk(next_uid))
            state[uid] = 2
            closure[uid] = reachable
            return reachable

        closure: dict[str, set[str]] = {}
        for uid in graph:
            walk(uid)
        for before, targets in closure.items():
            for after in targets:
                checked.add((before, after))
                if same_instant_root(before) == same_instant_root(after):
                    raise TimelineError("동시 사건 사이에 엄격한 선후관계를 지정할 수 없습니다.")
                first, second = intervals[before], intervals[after]
                if first is not None and second is not None:
                    # Day intervals are half-open. For exact instants both
                    # endpoints are equal, so equality cannot satisfy '<'.
                    if first[0] >= second[1]:
                        raise TimelineError("사건의 날짜와 선후관계가 상충합니다.")
        return TimelineAudit(project_id, len(events), count,
            tuple(uid for uid in sorted(events) if intervals[uid] is None), len(checked))

    def create_event(self, project_id: str, *, title: str, when: str | None = None,
                     anchor_event_id: str | None = None,
                     offset_minutes: int | None = None) -> TimelineEvent:
        project_id, title, when = _id(project_id), _title(title), _when(when)
        self._validate_time_args(when, anchor_event_id, offset_minutes)
        uid = uuid4().hex
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self.get_project(project_id)
            self._db.execute("""INSERT INTO bible_timeline_events VALUES
                (?, ?, ?, ?, ?, ?, 1, ?)""", (project_id, uid, title, when,
                  anchor_event_id, offset_minutes, _now()))
            self.audit(project_id)
            self._bump(project_id)
        return self.get_event(project_id, uid)

    @staticmethod
    def _validate_time_args(when: str | None, anchor: str | None,
                            offset: int | None) -> None:
        if anchor is None:
            if offset is not None:
                raise TimelineError("상대시간 기준 사건이 필요합니다.")
        else:
            _id(anchor)
            _offset(offset)
            if when is not None:
                raise TimelineError("절대시간과 상대시간을 동시에 지정할 수 없습니다.")

    def get_event(self, project_id: str, event_id: str) -> TimelineEvent:
        project_id, event_id = _id(project_id), _id(event_id)
        self.get_project(project_id)
        row = self._db.execute("""SELECT * FROM bible_timeline_events
            WHERE project_id=? AND event_id=?""", (project_id, event_id)).fetchone()
        if row is None:
            raise TimelineError("사건 기록을 찾을 수 없습니다.")
        return _event(row)

    def list_events(self, project_id: str) -> tuple[TimelineEvent, ...]:
        project_id = _id(project_id)
        self.get_project(project_id)
        return tuple(self._read_events(project_id).values())

    def update_event(self, project_id: str, event_id: str, *, title: str,
                     when: str | None = None, anchor_event_id: str | None = None,
                     offset_minutes: int | None = None,
                     expected_revision: int) -> TimelineEvent:
        project_id, event_id = _id(project_id), _id(event_id)
        title, when, expected_revision = _title(title), _when(when), _revision(expected_revision)
        self._validate_time_args(when, anchor_event_id, offset_minutes)
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            current = self.get_event(project_id, event_id)
            if current.revision != expected_revision or current.revision == 2**31 - 1:
                raise TimelineError("사건 기록이 변경되었습니다. 최신 버전을 확인하세요.")
            self._db.execute("""UPDATE bible_timeline_events SET title=?, when_value=?,
                anchor_event_id=?, offset_minutes=?, revision=revision+1, updated_at=?
                WHERE project_id=? AND event_id=? AND revision=?""",
                (title, when, anchor_event_id, offset_minutes, _now(),
                 project_id, event_id, expected_revision))
            self.audit(project_id)
            self._bump(project_id)
        return self.get_event(project_id, event_id)

    def add_order(self, project_id: str, before_id: str, after_id: str) -> TimelineAudit:
        project_id, before_id, after_id = _id(project_id), _id(before_id), _id(after_id)
        if before_id == after_id:
            raise TimelineError("동일한 사건을 자신보다 앞에 둘 수 없습니다.")
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self.get_event(project_id, before_id)
            self.get_event(project_id, after_id)
            try:
                self._db.execute("INSERT INTO bible_timeline_order VALUES (?, ?, ?)",
                                 (project_id, before_id, after_id))
            except sqlite3.IntegrityError:
                raise TimelineError("이미 등록된 사건 순서입니다.") from None
            result = self.audit(project_id)
            self._bump(project_id)
        return result

    def remove_order(self, project_id: str, before_id: str, after_id: str) -> None:
        project_id, before_id, after_id = _id(project_id), _id(before_id), _id(after_id)
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self.get_project(project_id)
            cursor = self._db.execute("""DELETE FROM bible_timeline_order
                WHERE project_id=? AND before_id=? AND after_id=?""",
                (project_id, before_id, after_id))
            if cursor.rowcount != 1:
                raise TimelineError("사건 순서 기록을 찾을 수 없습니다.")
            self.audit(project_id)
            self._bump(project_id)

    def delete_event(self, project_id: str, event_id: str, *, expected_revision: int) -> None:
        project_id, event_id, expected_revision = _id(project_id), _id(event_id), _revision(expected_revision)
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self.get_event(project_id, event_id)
            if self._db.execute("""SELECT 1 FROM bible_timeline_events
                WHERE project_id=? AND anchor_event_id=? LIMIT 1""",
                (project_id, event_id)).fetchone():
                raise TimelineError("다른 사건의 상대시간 기준이므로 삭제할 수 없습니다.")
            if self._db.execute("""SELECT 1 FROM bible_timeline_order WHERE project_id=?
                AND (before_id=? OR after_id=?) LIMIT 1""",
                (project_id, event_id, event_id)).fetchone():
                raise TimelineError("사건 순서 연결을 먼저 삭제해야 합니다.")
            cursor = self._db.execute("""DELETE FROM bible_timeline_events
                WHERE project_id=? AND event_id=? AND revision=?""",
                (project_id, event_id, expected_revision))
            if cursor.rowcount != 1:
                raise TimelineError("사건 기록이 변경되었습니다. 최신 버전을 확인하세요.")
            self._bump(project_id)
