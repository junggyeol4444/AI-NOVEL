"""Stage 30 local SQLite storage for privacy-limited reference profiles.

Uses the same connection as the Stage-19 metadata catalog. No network, GitHub,
source novel excerpts, word lists, model prompts, or absolute file paths.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from .reference_catalog import CatalogError, ReferenceCatalog, ReferenceRecord
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_novel_factory.references.reference_profile import ReferenceProfile

PROFILE_SCHEMA_VERSION = 1

MAX_PROFILE_JSON_BYTES = 2_000_000


class ProfileStorageError(ValueError):
    """Safe metadata-only error; never includes untrusted DB contents."""


@dataclass(frozen=True)
class ProfileListing:
    reference_id: str
    file_name: str  # only basename from already registered metadata
    source_format: str
    status: str
    episode_count: int
    updated_at: str


class ReferenceProfileStore:
    """SQLite profile store sharing an existing ReferenceCatalog's connection."""

    def __init__(self, catalog: ReferenceCatalog) -> None:
        if not isinstance(catalog, ReferenceCatalog):
            raise ProfileStorageError("로컬 참고작 목록 저장소가 필요합니다.")
        self._catalog = catalog
        self._db = catalog._db
        with self._db:
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS reference_profiles (
                    reference_id TEXT NOT NULL PRIMARY KEY
                        REFERENCES reference_files(reference_id) ON DELETE CASCADE,
                    schema_version INTEGER NOT NULL CHECK(schema_version = 1),
                    profile_json TEXT NOT NULL CHECK(length(profile_json) <= 2000000),
                    updated_at TEXT NOT NULL
                )
            """)
            self._db.execute("CREATE INDEX IF NOT EXISTS ix_reference_profiles_updated ON reference_profiles(updated_at DESC)")

    def save(self, reference_id: str, profile: ReferenceProfile) -> None:
        """Upsert a complete validated profile; no partial rows on SQL failure."""
        from ai_novel_factory.references.reference_profile import validate_profile
        validate_profile(profile)
        try:
            record = self._catalog.get(reference_id)
        except CatalogError:
            raise ProfileStorageError("등록되지 않은 참고작 프로필은 저장할 수 없습니다.") from None
        expected_format = "md" if profile.source_format == "markdown" else profile.source_format
        if record.source_format != expected_format:
            raise ProfileStorageError("참고작 파일 형식과 프로필이 일치하지 않습니다.")
        data = json.dumps(asdict(profile), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        if len(data.encode("utf-8")) > MAX_PROFILE_JSON_BYTES:
            raise ProfileStorageError("참고작 프로필 크기가 허용 범위를 초과했습니다.")
        now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        with self._db:
            self._db.execute("""
                INSERT INTO reference_profiles(reference_id, schema_version, profile_json, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(reference_id) DO UPDATE SET
                  schema_version=excluded.schema_version,
                  profile_json=excluded.profile_json,
                  updated_at=excluded.updated_at
            """, (reference_id, PROFILE_SCHEMA_VERSION, data, now))

    def get(self, reference_id: str) -> ReferenceProfile:
        row = self._db.execute(
            "SELECT schema_version, profile_json FROM reference_profiles WHERE reference_id=?",
            (reference_id,),
        ).fetchone()
        if row is None:
            raise ProfileStorageError("저장된 참고작 프로필을 찾을 수 없습니다.")
        if row["schema_version"] != PROFILE_SCHEMA_VERSION:
            raise ProfileStorageError("현재 프로그램에서 지원하지 않는 프로필 버전입니다.")
        from ai_novel_factory.references.reference_profile import (
            EpisodeProfile, ReferenceProfile, validate_profile,
        )
        try:
            if len(row["profile_json"].encode("utf-8")) > MAX_PROFILE_JSON_BYTES:
                raise ValueError("oversized")
            raw = json.loads(row["profile_json"])
            expected = {field.name for field in fields(ReferenceProfile)}
            episode_fields = {field.name for field in fields(EpisodeProfile)}
            if type(raw) is not dict or set(raw) != expected or type(raw["episodes"]) is not list:
                raise ValueError("unexpected keys")
            episodes = raw["episodes"]
            if len(episodes) > 10000 or any(type(e) is not dict or set(e) != episode_fields for e in episodes):
                raise ValueError("invalid episodes")
            raw["episodes"] = tuple(EpisodeProfile(**e) for e in episodes)
            result = ReferenceProfile(**raw)
            validate_profile(result)
            return result
        except (TypeError, ValueError, KeyError, OverflowError):
            raise ProfileStorageError("참고작 프로필 데이터가 손상되었거나 지원하지 않는 형식입니다.") from None

    def list(self, *, limit: int = 100, offset: int = 0) -> tuple[ProfileListing, ...]:
        if type(limit) is not int or type(offset) is not int or not 1 <= limit <= 1000 or offset < 0:
            raise ProfileStorageError("프로필 목록 범위가 올바르지 않습니다.")
        rows = self._db.execute("""
            SELECT r.reference_id, r.file_name, r.source_format, r.status,
                   p.profile_json, p.updated_at
            FROM reference_profiles p
            JOIN reference_files r ON r.reference_id=p.reference_id
            ORDER BY p.updated_at DESC, r.reference_id DESC LIMIT ? OFFSET ?
        """, (limit, offset)).fetchall()
        # Build just the visible list; never return stored raw JSON to the UI.
        output: list[ProfileListing] = []
        for row in rows:
            profile = self.get(row["reference_id"])
            output.append(ProfileListing(
                row["reference_id"], row["file_name"], row["source_format"],
                row["status"], profile.episode_count, row["updated_at"],
            ))
        return tuple(output)

    def count(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM reference_profiles").fetchone()[0]

    def delete(self, reference_id: str) -> bool:
        """Delete only derived profile, leaving reference-file metadata intact."""
        with self._db:
            return self._db.execute("DELETE FROM reference_profiles WHERE reference_id=?", (reference_id,)).rowcount > 0
