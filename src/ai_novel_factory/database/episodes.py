"""Stage 49 / ANF-REQ-039: user-authored episode artifacts, persisted offline.

The plot, scenes, draft, final manuscript, summary and *manual* check records
are kept in the existing project-scoped Novel Bible SQLite database. No source
novels are ingested, no AI is called and a final manuscript is NOT publication
approval. All writes are explicit and local.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json
import sqlite3
from uuid import uuid4

from .novel_bible import NovelBibleError, NovelBibleStore, _id, _key, _now, _revision


class EpisodeError(NovelBibleError):
    """Never include the user's manuscript, file path or secrets in errors."""


MAX_EPISODES = 1000
MAX_SCENES = 200
MAX_CHECKS = 500
MAX_EPISODE_BYTES = 1_100_000
MAX_FIELD_BYTES = {"plot": 80_000, "draft": 500_000,
                   "final_text": 500_000, "summary": 80_000}
CHECK_OUTCOMES = frozenset({"PASS", "WARN", "FAIL", "NOT_RUN"})


@dataclass(frozen=True)
class Episode:
    project_id: str
    episode: int
    plot: str
    draft: str
    final_text: str
    summary: str
    revision: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Scene:
    project_id: str
    episode: int
    scene_id: str
    position: int
    text: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class CheckRecord:
    project_id: str
    episode: int
    check_id: str
    category: str
    outcome: str
    note: str
    content_revision: int
    created_at: str


@dataclass(frozen=True)
class EpisodeSnapshot:
    episode: Episode
    scenes: tuple[Scene, ...]
    checks: tuple[CheckRecord, ...]

    def to_json(self, *, reveal: bool = False) -> str:
        """Explicit local export; default excludes user-authored manuscript text."""
        ep = self.episode
        data = {
            "project_id": ep.project_id, "episode": ep.episode,
            "revision": ep.revision, "publication_approved": False,
            "plot": ep.plot if reveal else "[redacted]",
            "draft": ep.draft if reveal else "[redacted]",
            "final_text": ep.final_text if reveal else "[redacted]",
            "summary": ep.summary if reveal else "[redacted]",
            "scenes": [{"scene_id": s.scene_id, "position": s.position,
                        "text": s.text if reveal else "[redacted]"}
                       for s in self.scenes],
            "checks": [{"check_id": c.check_id, "category": c.category,
                        "outcome": c.outcome, "content_revision": c.content_revision,
                        "stale": c.content_revision != ep.revision,
                        "note": c.note if reveal else "[redacted]"}
                       for c in self.checks],
        }
        return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _number(value: object, *, maximum: int = 1_000_000) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise EpisodeError("회차 또는 장면 번호가 올바르지 않습니다.")
    return value


def _content(value: object, *, limit: int) -> str:
    if type(value) is not str:
        raise EpisodeError("원고 내용의 형식 또는 길이가 올바르지 않습니다.")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError:
        raise EpisodeError("원고 내용의 형식 또는 길이가 올바르지 않습니다.") from None
    if (size > limit or "\x00" in value or any(
            (ord(c) < 32 and c not in "\n\t\r") or ord(c) == 127 for c in value)):
        raise EpisodeError("원고 내용의 형식 또는 길이가 올바르지 않습니다.")
    return value


def _stamp(value: object) -> None:
    try:
        if type(value) is not str:
            raise ValueError
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise EpisodeError("저장된 회차 정보가 손상되었습니다.") from None


def _episode(row: sqlite3.Row) -> Episode:
    try:
        item = Episode(*(row[key] for key in (
            "project_id", "episode", "plot", "draft", "final_text", "summary",
            "revision", "created_at", "updated_at")))
        _id(item.project_id)
        _number(item.episode)
        _revision(item.revision)
        for key, limit in MAX_FIELD_BYTES.items():
            _content(getattr(item, key), limit=limit)
        _stamp(item.created_at)
        _stamp(item.updated_at)
        if sum(len(getattr(item, key).encode("utf-8")) for key in MAX_FIELD_BYTES) > MAX_EPISODE_BYTES:
            raise EpisodeError("저장된 회차 정보가 손상되었습니다.")
        return item
    except (NovelBibleError, KeyError, IndexError, TypeError, ValueError, OverflowError):
        raise EpisodeError("저장된 회차 정보가 손상되었습니다.") from None


def _scene(row: sqlite3.Row) -> Scene:
    try:
        item = Scene(*(row[key] for key in (
            "project_id", "episode", "scene_id", "position", "text",
            "created_at", "updated_at")))
        _id(item.project_id)
        _id(item.scene_id)
        _number(item.episode)
        _number(item.position, maximum=MAX_SCENES)
        _content(item.text, limit=80_000)
        _stamp(item.created_at)
        _stamp(item.updated_at)
        return item
    except (NovelBibleError, KeyError, IndexError, TypeError, ValueError, OverflowError):
        raise EpisodeError("저장된 장면 정보가 손상되었습니다.") from None


def _check(row: sqlite3.Row) -> CheckRecord:
    try:
        item = CheckRecord(*(row[key] for key in (
            "project_id", "episode", "check_id", "category", "outcome",
            "note", "content_revision", "created_at")))
        _id(item.project_id)
        _id(item.check_id)
        _number(item.episode)
        _key(item.category)
        if type(item.outcome) is not str or item.outcome not in CHECK_OUTCOMES:
            raise ValueError
        _content(item.note, limit=8192)
        _revision(item.content_revision)
        _stamp(item.created_at)
        return item
    except (NovelBibleError, KeyError, IndexError, TypeError, ValueError, OverflowError):
        raise EpisodeError("저장된 검사 기록이 손상되었습니다.") from None


class EpisodeStore(NovelBibleStore):
    """Project-isolated SQLite episodes with optimistic content revisions.

    Each episode edit and scene mutation increments episode + project revision.
    Manual checks are append-only and record the *current content revision*;
    they become stale after subsequent edits. Checks are not AI verification.
    """

    def __init__(self, database_path: str | Path = ":memory:") -> None:
        super().__init__(database_path)
        with self._db:
            self._db.execute("""CREATE TABLE IF NOT EXISTS bible_episodes (
                project_id TEXT NOT NULL REFERENCES bible_projects(project_id) ON DELETE CASCADE,
                episode INTEGER NOT NULL CHECK(episode BETWEEN 1 AND 1000000),
                plot TEXT NOT NULL DEFAULT '', draft TEXT NOT NULL DEFAULT '',
                final_text TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '',
                revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 2147483647),
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(project_id, episode)
            )""")
            self._db.execute("""CREATE TABLE IF NOT EXISTS bible_episode_scenes (
                project_id TEXT NOT NULL, episode INTEGER NOT NULL,
                scene_id TEXT NOT NULL CHECK(length(scene_id)=32),
                position INTEGER NOT NULL CHECK(position BETWEEN 1 AND 200),
                text TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(project_id, episode, scene_id),
                UNIQUE(project_id, episode, position),
                FOREIGN KEY(project_id, episode) REFERENCES bible_episodes(project_id, episode)
                    ON DELETE CASCADE
            )""")
            self._db.execute("""CREATE TABLE IF NOT EXISTS bible_episode_checks (
                project_id TEXT NOT NULL, episode INTEGER NOT NULL,
                check_id TEXT NOT NULL CHECK(length(check_id)=32),
                category TEXT NOT NULL CHECK(length(category) BETWEEN 1 AND 64),
                outcome TEXT NOT NULL CHECK(outcome IN ('PASS','WARN','FAIL','NOT_RUN')),
                note TEXT NOT NULL, content_revision INTEGER NOT NULL CHECK(content_revision>=1),
                created_at TEXT NOT NULL,
                PRIMARY KEY(project_id, episode, check_id),
                FOREIGN KEY(project_id, episode) REFERENCES bible_episodes(project_id, episode)
                    ON DELETE CASCADE
            )""")
            self._db.execute("""CREATE INDEX IF NOT EXISTS ix_episode_scenes
                ON bible_episode_scenes(project_id, episode, position)""")
            self._db.execute("""CREATE INDEX IF NOT EXISTS ix_episode_checks
                ON bible_episode_checks(project_id, episode, created_at, check_id)""")

    def _bump_project(self, project_id: str) -> None:
        self._db.execute("UPDATE bible_projects SET revision=revision+1 WHERE project_id=?",
                         (project_id,))

    def _require_revision(self, project_id: str, episode: int, revision: int) -> Episode:
        old = self.get_episode(project_id, episode)
        if old.revision != revision:
            raise EpisodeError("회차가 다른 작업에서 수정되었습니다. 최신 버전을 확인하세요.")
        if old.revision >= 2**31 - 1:
            raise EpisodeError("회차 버전 한도에 도달했습니다.")
        return old

    def get_episode(self, project_id: str, episode: int) -> Episode:
        project_id, episode = _id(project_id), _number(episode)
        self.get_project(project_id)
        row = self._db.execute("""SELECT * FROM bible_episodes
            WHERE project_id=? AND episode=?""", (project_id, episode)).fetchone()
        if row is None:
            raise EpisodeError("회차를 찾을 수 없습니다.")
        return _episode(row)

    def list_episodes(self, project_id: str) -> tuple[Episode, ...]:
        project_id = _id(project_id)
        self.get_project(project_id)
        records = tuple(_episode(row) for row in self._db.execute(
            "SELECT * FROM bible_episodes WHERE project_id=? ORDER BY episode", (project_id,)))
        if len(records) > MAX_EPISODES:
            raise EpisodeError("저장된 회차 개수 제한을 초과했습니다.")
        return records

    def create_episode(self, project_id: str, episode: int, *, plot: str = "") -> Episode:
        project_id, episode = _id(project_id), _number(episode)
        plot = _content(plot, limit=MAX_FIELD_BYTES["plot"])
        try:
            with self._db:
                self._db.execute("BEGIN IMMEDIATE")
                self.get_project(project_id)
                if self._db.execute("SELECT COUNT(*) FROM bible_episodes WHERE project_id=?",
                                    (project_id,)).fetchone()[0] >= MAX_EPISODES:
                    raise EpisodeError("작품별 회차 개수 제한을 초과했습니다.")
                stamp = _now()
                self._db.execute("""INSERT INTO bible_episodes
                    (project_id, episode, plot, revision, created_at, updated_at)
                    VALUES (?, ?, ?, 1, ?, ?)""", (project_id, episode, plot, stamp, stamp))
                self._bump_project(project_id)
        except sqlite3.IntegrityError:
            raise EpisodeError("해당 회차가 이미 존재하거나 저장할 수 없습니다.") from None
        return self.get_episode(project_id, episode)

    def update_episode(self, project_id: str, episode: int, *, expected_revision: int,
                       plot: str | None = None, draft: str | None = None,
                       final_text: str | None = None, summary: str | None = None) -> Episode:
        project_id, episode, expected_revision = _id(project_id), _number(episode), _revision(expected_revision)
        changes = {name: _content(value, limit=MAX_FIELD_BYTES[name])
                   for name, value in (("plot", plot), ("draft", draft),
                                       ("final_text", final_text), ("summary", summary))
                   if value is not None}
        if not changes:
            raise EpisodeError("수정할 회차 항목이 없습니다.")
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            old = self._require_revision(project_id, episode, expected_revision)
            sizes = {name: len((changes[name] if name in changes else getattr(old, name)).encode("utf-8"))
                     for name in MAX_FIELD_BYTES}
            if sum(sizes.values()) > MAX_EPISODE_BYTES:
                raise EpisodeError("회차 전체 원고 크기 제한을 초과했습니다.")
            columns = ", ".join(f"{name}=?" for name in changes)
            self._db.execute(f"""UPDATE bible_episodes SET {columns}, revision=revision+1,
                updated_at=? WHERE project_id=? AND episode=? AND revision=?""",
                (*changes.values(), _now(), project_id, episode, expected_revision))
            self._bump_project(project_id)
        return self.get_episode(project_id, episode)

    def delete_episode(self, project_id: str, episode: int, *, expected_revision: int) -> None:
        project_id, episode, expected_revision = _id(project_id), _number(episode), _revision(expected_revision)
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self._require_revision(project_id, episode, expected_revision)
            self._db.execute("DELETE FROM bible_episodes WHERE project_id=? AND episode=?",
                             (project_id, episode))
            self._bump_project(project_id)

    def list_scenes(self, project_id: str, episode: int) -> tuple[Scene, ...]:
        project_id, episode = _id(project_id), _number(episode)
        self.get_episode(project_id, episode)
        scenes = tuple(_scene(row) for row in self._db.execute("""SELECT * FROM bible_episode_scenes
            WHERE project_id=? AND episode=? ORDER BY position""", (project_id, episode)))
        if len(scenes) > MAX_SCENES:
            raise EpisodeError("저장된 장면 개수 제한을 초과했습니다.")
        return scenes

    def add_scene(self, project_id: str, episode: int, position: int, text: str,
                  *, expected_revision: int) -> Scene:
        project_id, episode = _id(project_id), _number(episode)
        position, text, expected_revision = (_number(position, maximum=MAX_SCENES),
                                             _content(text, limit=80_000), _revision(expected_revision))
        scene_id = uuid4().hex
        try:
            with self._db:
                self._db.execute("BEGIN IMMEDIATE")
                self._require_revision(project_id, episode, expected_revision)
                if self._db.execute("""SELECT COUNT(*) FROM bible_episode_scenes
                    WHERE project_id=? AND episode=?""", (project_id, episode)).fetchone()[0] >= MAX_SCENES:
                    raise EpisodeError("장면 개수 제한을 초과했습니다.")
                stamp = _now()
                self._db.execute("""INSERT INTO bible_episode_scenes VALUES
                    (?, ?, ?, ?, ?, ?, ?)""", (project_id, episode, scene_id, position, text, stamp, stamp))
                self._db.execute("""UPDATE bible_episodes SET revision=revision+1, updated_at=?
                    WHERE project_id=? AND episode=?""", (stamp, project_id, episode))
                self._bump_project(project_id)
        except sqlite3.IntegrityError:
            raise EpisodeError("장면 위치가 중복되었거나 저장할 수 없습니다.") from None
        return self.get_scene(project_id, episode, scene_id)

    def get_scene(self, project_id: str, episode: int, scene_id: str) -> Scene:
        project_id, episode, scene_id = _id(project_id), _number(episode), _id(scene_id)
        self.get_episode(project_id, episode)
        row = self._db.execute("""SELECT * FROM bible_episode_scenes
            WHERE project_id=? AND episode=? AND scene_id=?""", (project_id, episode, scene_id)).fetchone()
        if row is None:
            raise EpisodeError("장면을 찾을 수 없습니다.")
        return _scene(row)

    def update_scene(self, project_id: str, episode: int, scene_id: str, *,
                     expected_revision: int, position: int | None = None,
                     text: str | None = None) -> Scene:
        project_id, episode, scene_id = _id(project_id), _number(episode), _id(scene_id)
        expected_revision = _revision(expected_revision)
        changes: dict[str, int | str] = {}
        if position is not None:
            changes["position"] = _number(position, maximum=MAX_SCENES)
        if text is not None:
            changes["text"] = _content(text, limit=80_000)
        if not changes:
            raise EpisodeError("수정할 장면 항목이 없습니다.")
        try:
            with self._db:
                self._db.execute("BEGIN IMMEDIATE")
                self._require_revision(project_id, episode, expected_revision)
                self.get_scene(project_id, episode, scene_id)
                columns = ", ".join(f"{name}=?" for name in changes)
                stamp = _now()
                self._db.execute(f"""UPDATE bible_episode_scenes SET {columns}, updated_at=?
                    WHERE project_id=? AND episode=? AND scene_id=?""",
                    (*changes.values(), stamp, project_id, episode, scene_id))
                self._db.execute("""UPDATE bible_episodes SET revision=revision+1, updated_at=?
                    WHERE project_id=? AND episode=?""", (stamp, project_id, episode))
                self._bump_project(project_id)
        except sqlite3.IntegrityError:
            raise EpisodeError("장면 위치가 중복되었거나 수정할 수 없습니다.") from None
        return self.get_scene(project_id, episode, scene_id)

    def delete_scene(self, project_id: str, episode: int, scene_id: str, *,
                     expected_revision: int) -> None:
        project_id, episode, scene_id = _id(project_id), _number(episode), _id(scene_id)
        expected_revision = _revision(expected_revision)
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self._require_revision(project_id, episode, expected_revision)
            if self._db.execute("""DELETE FROM bible_episode_scenes WHERE project_id=?
                AND episode=? AND scene_id=?""", (project_id, episode, scene_id)).rowcount != 1:
                raise EpisodeError("장면을 찾을 수 없습니다.")
            self._db.execute("""UPDATE bible_episodes SET revision=revision+1, updated_at=?
                WHERE project_id=? AND episode=?""", (_now(), project_id, episode))
            self._bump_project(project_id)

    def add_check(self, project_id: str, episode: int, category: str, outcome: str,
                  note: str = "", *, expected_revision: int) -> CheckRecord:
        project_id, episode, expected_revision = _id(project_id), _number(episode), _revision(expected_revision)
        try:
            category = _key(category)
        except NovelBibleError:
            raise EpisodeError("검사 분류 코드가 올바르지 않습니다.") from None
        if type(outcome) is not str or outcome not in CHECK_OUTCOMES:
            raise EpisodeError("검사 결과 상태가 올바르지 않습니다.")
        note = _content(note, limit=8192)
        check_id = uuid4().hex
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            current = self.get_episode(project_id, episode)
            if current.revision != expected_revision:
                raise EpisodeError("검사 대상 원고가 수정되었습니다. 최신 버전을 확인하세요.")
            if self._db.execute("""SELECT COUNT(*) FROM bible_episode_checks
                WHERE project_id=? AND episode=?""", (project_id, episode)).fetchone()[0] >= MAX_CHECKS:
                raise EpisodeError("검사 기록 개수 제한을 초과했습니다.")
            self._db.execute("""INSERT INTO bible_episode_checks VALUES
                (?, ?, ?, ?, ?, ?, ?, ?)""", (project_id, episode, check_id, category,
                                                   outcome, note, current.revision, _now()))
            self._bump_project(project_id)
        return self.get_check(project_id, episode, check_id)

    def get_check(self, project_id: str, episode: int, check_id: str) -> CheckRecord:
        project_id, episode, check_id = _id(project_id), _number(episode), _id(check_id)
        self.get_episode(project_id, episode)
        row = self._db.execute("""SELECT * FROM bible_episode_checks
            WHERE project_id=? AND episode=? AND check_id=?""", (project_id, episode, check_id)).fetchone()
        if row is None:
            raise EpisodeError("검사 기록을 찾을 수 없습니다.")
        return _check(row)

    def list_checks(self, project_id: str, episode: int) -> tuple[CheckRecord, ...]:
        project_id, episode = _id(project_id), _number(episode)
        self.get_episode(project_id, episode)
        checks = tuple(_check(row) for row in self._db.execute("""SELECT * FROM bible_episode_checks
            WHERE project_id=? AND episode=? ORDER BY created_at, check_id""", (project_id, episode)))
        if len(checks) > MAX_CHECKS:
            raise EpisodeError("저장된 검사 기록 개수 제한을 초과했습니다.")
        return checks

    def snapshot(self, project_id: str, episode: int) -> EpisodeSnapshot:
        """Read episode, scenes and checks in one SQLite snapshot transaction."""
        self._db.execute("SAVEPOINT episode_snapshot_read")
        try:
            record = self.get_episode(project_id, episode)
            scenes = self.list_scenes(project_id, episode)
            checks = self.list_checks(project_id, episode)
            snapshot = EpisodeSnapshot(record, scenes, checks)
        except BaseException:
            self._db.execute("ROLLBACK TO SAVEPOINT episode_snapshot_read")
            self._db.execute("RELEASE SAVEPOINT episode_snapshot_read")
            raise
        self._db.execute("RELEASE SAVEPOINT episode_snapshot_read")
        return snapshot
