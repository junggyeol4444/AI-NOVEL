"""Read-only, chapter-aware author canon for the existing local novel writer.

The writer receives saved facts only through the explicitly approved local model.
This module never promotes AI drafts to canon, copies reference novels, publishes,
or writes to the author's database. Future knowledge and relationship changes are
not treated as facts already known at an earlier episode.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3

_PROJECT_ID = re.compile(r"[0-9a-f]{32}\Z")
# These table names are fixed identifiers, never constructed from user input.
_CANON_TABLES = (
    "bible_characters", "bible_style_rules", "bible_world_entries",
    "bible_relationship_events", "bible_timeline_events", "bible_timeline_order",
    "bible_foreshadow_threads", "bible_foreshadow_events",
    "bible_knowledge_facts", "bible_knowledge_events",
)


@dataclass(frozen=True)
class SavedAuthorContext:
    memory: str
    style: str
    source_stamp: str


def _section(label: str, entries: list[str], budget: int) -> str:
    """Keep whole records, disclose any omitted items, and never invent facts."""
    if not entries:
        return ""
    result = label + "\n"
    kept = 0
    for entry in entries:
        line = "- " + entry.replace("\x00", "") + "\n"
        if len(result) + len(line) + 44 > budget:
            break
        result += line
        kept += 1
    if kept < len(entries):
        result += f"[저장 기록 {len(entries) - kept}개 문맥 한도로 생략: 미검증]\n"
    return result[:budget]


def _rows(db: sqlite3.Connection, table: str, project_id: str) -> list[dict]:
    # No dynamic SQL except the hard-coded allowlist above.
    if table not in _CANON_TABLES:
        raise ValueError("invalid canon table")
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                      (table,)).fetchone():
        return []
    return [dict(row) for row in db.execute(
        f'SELECT * FROM "{table}" WHERE project_id=?', (project_id,))]


def read_saved_author_context(
    database_path: str | Path, project_id: str, episode: int,
) -> SavedAuthorContext:
    """Load saved author rules, time-scoped canon and a stable whole-canon lease.

    The source stamp intentionally includes future records, too: it must stay
    identical while a batch progresses from chapter N to N+1, yet change when
    an author edits any canon entry during an in-flight local model request.
    """
    if (type(project_id) is not str or not _PROJECT_ID.fullmatch(project_id)
            or type(episode) is not int or not 1 <= episode <= 1_000_000):
        raise ValueError("invalid author canon request")
    path = str(database_path)
    if not path or "\x00" in path or path.startswith(("file:", "\\\\", "//")):
        raise ValueError("invalid local canon database path")
    # The caller has already opened an existing EpisodeStore. PRAGMA query_only
    # ensures this reader cannot mutate the author's data or SQLite schema.
    with sqlite3.connect(path, timeout=10) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        if not db.execute("SELECT 1 FROM bible_projects WHERE project_id=?",
                          (project_id,)).fetchone():
            raise ValueError("author project is not available")
        tables = {name: _rows(db, name, project_id) for name in _CANON_TABLES}

    # Canonicalize row ordering so a SQLite query plan change cannot invalidate
    # a long-running writer. Only a SHA digest leaves this local function.
    stable = {name: sorted(rows, key=lambda row: json.dumps(
        row, sort_keys=True, ensure_ascii=False, default=str))
        for name, rows in tables.items()}
    stamp = sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
    names = {row["character_id"]: row["name"]
             for row in tables["bible_characters"]}

    style = _section("작가가 저장한 Style Bible 문체 규칙:", [
        f'{row["rule_key"]}: {row["directive"][:450]}'
        for row in sorted(tables["bible_style_rules"],
                          key=lambda row: row["rule_key"])], 2600)

    world = _section("작가가 저장한 세계관·조직·지역·능력·아이템:", [
        f'{row["category"]} {row["name"]}: {row["description"][:220]}'
        for row in sorted(tables["bible_world_entries"],
                          key=lambda row: (row["category"], row["name"]))], 800)

    relations_latest = {}
    for row in sorted(tables["bible_relationship_events"],
                      key=lambda row: row["episode"]):
        if row["episode"] <= episode:
            relations_latest[(row["first_character_id"],
                              row["second_character_id"])] = row
    relations = _section("해당 회차까지 기록된 인물 관계(미래 변경 미포함):", [
        f'{names.get(row["first_character_id"], "미등록 인물")}—'
        f'{names.get(row["second_character_id"], "미등록 인물")}: '
        f'{row["relationship"][:170]} ({row["episode"]}화부터)'
        for _, row in sorted(relations_latest.items())], 650)

    foreshadow_latest = {}
    for row in sorted(tables["bible_foreshadow_events"],
                      key=lambda row: (row["episode"], row["sequence"])):
        if row["episode"] <= episode:
            foreshadow_latest[row["thread_id"]] = row
    thread_titles = {row["thread_id"]: row["title"]
                     for row in tables["bible_foreshadow_threads"]}
    foreshadow = _section("해당 회차까지 작가가 저장한 복선(검수 승인 아님):", [
        f'{thread_titles.get(thread_id, "미등록 복선")}: '
        f'{row["action"]} {row["episode"]}화 {row["note"][:150]}'
        for thread_id, row in sorted(foreshadow_latest.items())], 550)

    timeline = _section("작가의 사건 시간선 계획(발생 확정 아님):", [
        f'{row["title"]}: {row["when_value"] or "상대시간/미지정"}'
        for row in sorted(tables["bible_timeline_events"],
                          key=lambda row: row["event_id"])], 450)

    knowledge_latest = {}
    for row in sorted(tables["bible_knowledge_events"],
                      key=lambda row: row["episode"]):
        if row["episode"] <= episode:
            knowledge_latest[(row["character_id"], row["fact_id"])] = row
    facts = {row["fact_id"]: row["description"]
             for row in tables["bible_knowledge_facts"]}
    knowledge = _section("회차 시점에 명시적으로 기록된 인물 지식(미기록은 추정 금지):", [
        f'{names.get(character_id, "미등록 인물")}: '
        f'{facts.get(fact_id, "미등록 사실")[:110]} / '
        f'{"알고 있음" if row["knows"] else "모르거나 상실함"} '
        f'({row["episode"]}화부터)'
        for (character_id, fact_id), row in sorted(knowledge_latest.items())], 450)

    return SavedAuthorContext(world + relations + foreshadow + timeline + knowledge,
                              style, stamp)