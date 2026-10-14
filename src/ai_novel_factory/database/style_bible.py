"""Stage 48 (ANF-REQ-038): user-authored Style Bible and offline generation context.

No reference prose is imported. This module prepares *data* for a future local
writer; it does not invoke a model, execute instructions, or authorize publishing.
Priority: Novel Bible > Style Bible > validated anonymous reference statistics.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Mapping

from .novel_bible import (
    ContextField, NovelBibleError, NovelBibleStore, _id, _key, _now,
    _revision, _safe_statistics, _text,
)

MAX_STYLE_RULES = 32
MAX_STYLE_BYTES = 32_768


class StyleBibleError(NovelBibleError):
    """Sanitized error; never includes private writing rules or reference text."""


@dataclass(frozen=True)
class StyleRule:
    project_id: str
    key: str
    directive: str
    revision: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class GenerationContext:
    """Immutable, structured input for a future *local* writer (not a prompt)."""
    project_id: str
    project_revision: int
    fields: tuple[ContextField, ...]
    overridden_style_keys: tuple[str, ...]
    overridden_reference_keys: tuple[str, ...]
    style_rule_revisions: tuple[tuple[str, int], ...]

    def to_json(self) -> str:
        """Explicit, deterministic data export. Values remain quoted JSON strings."""
        return json.dumps({
            "schema": "anf.generation_context.v1",
            "project_id": self.project_id,
            "project_revision": self.project_revision,
            "fields": [{"key": item.key, "value": item.value, "source": item.source}
                       for item in self.fields],
            "overridden_style_keys": list(self.overridden_style_keys),
            "overridden_reference_keys": list(self.overridden_reference_keys),
            "style_rule_revisions": [list(pair) for pair in self.style_rule_revisions],
            "publication_approved": False,
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _directive(value: object) -> str:
    try:
        return _text(value)
    except NovelBibleError:
        raise StyleBibleError("문체 규칙의 형식 또는 길이가 올바르지 않습니다.") from None


def _style_key(value: object) -> str:
    try:
        return _key(value)
    except NovelBibleError:
        raise StyleBibleError("문체 항목 코드가 올바르지 않습니다.") from None


def _style(row: sqlite3.Row) -> StyleRule:
    try:
        item = StyleRule(row["project_id"], row["rule_key"], row["directive"],
                         row["revision"], row["created_at"], row["updated_at"])
        _id(item.project_id)
        _style_key(item.key)
        _directive(item.directive)
        _revision(item.revision)
        for stamp in (item.created_at, item.updated_at):
            if datetime.fromisoformat(stamp).tzinfo is None:
                raise ValueError("timestamp without timezone")
        return item
    except (TypeError, ValueError, KeyError, IndexError, OverflowError):
        raise StyleBibleError("저장된 문체 규칙이 손상되었습니다.") from None


class StyleBibleStore(NovelBibleStore):
    """Project-scoped SQLite store; explicit writes, optimistic revisions."""

    def __init__(self, database_path: str | Path = ":memory:") -> None:
        super().__init__(database_path)
        with self._db:
            self._db.execute("""CREATE TABLE IF NOT EXISTS bible_style_rules (
                project_id TEXT NOT NULL REFERENCES bible_projects(project_id) ON DELETE CASCADE,
                rule_key TEXT NOT NULL CHECK(length(rule_key) BETWEEN 1 AND 64),
                directive TEXT NOT NULL CHECK(length(directive) BETWEEN 1 AND 4000),
                revision INTEGER NOT NULL CHECK(revision>=1),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(project_id, rule_key)
            )""")

    def get_style_rule(self, project_id: str, key: str) -> StyleRule:
        project_id, key = _id(project_id), _style_key(key)
        self.get_project(project_id)
        row = self._db.execute("""SELECT * FROM bible_style_rules
            WHERE project_id=? AND rule_key=?""", (project_id, key)).fetchone()
        if row is None:
            raise StyleBibleError("문체 규칙을 찾을 수 없습니다.")
        return _style(row)

    def list_style_rules(self, project_id: str) -> tuple[StyleRule, ...]:
        project_id = _id(project_id)
        self.get_project(project_id)
        rows = self._db.execute("""SELECT * FROM bible_style_rules
            WHERE project_id=? ORDER BY rule_key""", (project_id,))
        return tuple(_style(row) for row in rows)

    def _check_limits(self, project_id: str, key: str, directive: str) -> None:
        # Reads only the same project's rules; validates corruption before writes.
        existing = self.list_style_rules(project_id)
        count = len(existing)
        size = sum(len(rule.directive.encode("utf-8")) for rule in existing)
        previous = next((rule for rule in existing if rule.key == key), None)
        if previous is None:
            count += 1
        else:
            size -= len(previous.directive.encode("utf-8"))
        size += len(directive.encode("utf-8"))
        if count > MAX_STYLE_RULES or size > MAX_STYLE_BYTES:
            raise StyleBibleError("작품별 문체 규칙 개수 또는 전체 크기 제한을 초과했습니다.")

    def save_style_rule(self, project_id: str, key: str, directive: str,
                        *, expected_revision: int | None = None) -> StyleRule:
        project_id, key, directive = _id(project_id), _style_key(key), _directive(directive)
        if expected_revision is not None:
            expected_revision = _revision(expected_revision)
            if expected_revision >= 2**31 - 1:
                raise StyleBibleError("문체 규칙 버전 한도에 도달했습니다.")
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self.get_project(project_id)
            row = self._db.execute("""SELECT revision FROM bible_style_rules
                WHERE project_id=? AND rule_key=?""", (project_id, key)).fetchone()
            if row is None and expected_revision is not None:
                raise StyleBibleError("문체 규칙이 변경되었거나 삭제되었습니다.")
            if row is not None and expected_revision != row["revision"]:
                raise StyleBibleError("문체 규칙이 변경되었습니다. 최신 버전을 확인하세요.")
            self._check_limits(project_id, key, directive)
            stamp = _now()
            if row is None:
                self._db.execute("""INSERT INTO bible_style_rules VALUES
                    (?, ?, ?, 1, ?, ?)""", (project_id, key, directive, stamp, stamp))
            else:
                self._db.execute("""UPDATE bible_style_rules
                    SET directive=?, revision=revision+1, updated_at=?
                    WHERE project_id=? AND rule_key=?""", (directive, stamp, project_id, key))
            self._db.execute("""UPDATE bible_projects SET revision=revision+1
                WHERE project_id=?""", (project_id,))
        return self.get_style_rule(project_id, key)

    def delete_style_rule(self, project_id: str, key: str, *, expected_revision: int) -> None:
        project_id, key = _id(project_id), _style_key(key)
        expected_revision = _revision(expected_revision)
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self.get_project(project_id)
            cursor = self._db.execute("""DELETE FROM bible_style_rules
                WHERE project_id=? AND rule_key=? AND revision=?""",
                (project_id, key, expected_revision))
            if cursor.rowcount != 1:
                raise StyleBibleError("문체 규칙이 변경되었거나 삭제되었습니다.")
            self._db.execute("""UPDATE bible_projects SET revision=revision+1
                WHERE project_id=?""", (project_id,))

    def build_generation_context(self, project_id: str,
                                 reference_statistics: Mapping[str, float] | None = None
                                 ) -> GenerationContext:
        """Resolve canon in a single SQLite snapshot; no persistence of stats.

        A missing Novel Bible or missing Style Bible fails closed. The same key
        from user canon suppresses the Style Bible entry, which suppresses
        reference statistics. This is a structured context, not AI inference.
        """
        project_id = _id(project_id)
        stats = _safe_statistics(reference_statistics)
        # SAVEPOINT works both outside and inside a caller's transaction;
        # unlike `with self._db`, it never commits unrelated caller writes.
        self._db.execute("SAVEPOINT style_context_read")
        try:
            project = self.get_project(project_id)
            rules = self.list_rules(project_id)
            styles = self.list_style_rules(project_id)
            if not rules:
                raise StyleBibleError("Novel Bible 설정이 없어 생성 컨텍스트를 만들 수 없습니다.")
            if not styles:
                raise StyleBibleError("Style Bible 설정이 없어 생성 컨텍스트를 만들 수 없습니다.")
            if (len(styles) > MAX_STYLE_RULES or
                    sum(len(item.directive.encode("utf-8")) for item in styles) > MAX_STYLE_BYTES):
                raise StyleBibleError("저장된 문체 규칙의 개수 또는 크기가 올바르지 않습니다.")
            novel_keys = {rule.key for rule in rules}
            style_keys = {style.key for style in styles}
            values = {key: ContextField(key, val, "reference_statistic")
                      for key, val in stats.items()}
            for style in styles:
                values[style.key] = ContextField(style.key, style.directive, "style_bible")
            for rule in rules:
                values[rule.key] = ContextField(rule.key, rule.value, "novel_bible")
            overridden_styles = tuple(sorted(novel_keys & style_keys))
            overridden_refs = tuple(sorted(set(stats) & (novel_keys | style_keys)))
            context = GenerationContext(
                project.project_id, project.revision,
                tuple(values[key] for key in sorted(values)),
                overridden_styles, overridden_refs,
                tuple((style.key, style.revision) for style in styles),
            )
        except BaseException:
            self._db.execute("ROLLBACK TO SAVEPOINT style_context_read")
            self._db.execute("RELEASE SAVEPOINT style_context_read")
            raise
        self._db.execute("RELEASE SAVEPOINT style_context_read")
        return context
