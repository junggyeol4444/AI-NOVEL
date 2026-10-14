"""Stage 32: local SQLite genre tags and reproducible pattern selection.

Stores only fixed genre codes, anonymous local reference UUIDs and timestamps.
Stored selection sets are re-aggregated on reading; statistical output never
becomes stale when a source profile is updated, and no source text is stored.
No GitHub, HTTP, AI, remote DB, or filesystem access beyond the catalog DB.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re

from ai_novel_factory.database.reference_catalog import ReferenceCatalog
from ai_novel_factory.database.reference_profiles import ProfileStorageError, ReferenceProfileStore
from ai_novel_factory.references.genre_patterns import (
    GENRE_NAMES, GenrePattern, build_genre_pattern, validate_genre,
)
from ai_novel_factory.references.plaintext_parser import ReferenceParseError
from ai_novel_factory.references.profile_collection import MAX_COLLECTION_REFERENCES, WEIGHTING_MODES

_ID = re.compile(r"[0-9a-f]{32}\Z")


class GenreStorageError(ValueError):
    """Safe error without source filename, path or DB text."""


@dataclass(frozen=True)
class SavedGenreSelection:
    genre: str
    weighting: str
    reference_count: int
    updated_at: str
    current: bool  # False when labels/membership have changed since last build.


def _check_id(reference_id: str) -> None:
    if type(reference_id) is not str or _ID.fullmatch(reference_id) is None:
        raise GenreStorageError("참고작 ID 형식이 올바르지 않습니다.")


def _check_genre(genre: str) -> None:
    try:
        validate_genre(genre)
    except ReferenceParseError:
        raise GenreStorageError("지원하지 않는 장르 코드입니다.") from None


def _check_weighting(weighting: str) -> None:
    if type(weighting) is not str or weighting not in WEIGHTING_MODES:
        raise GenreStorageError("통합 가중치가 올바르지 않습니다.")


class GenrePatternStore:
    """Genre tags and reusable selection recipes in the same local SQLite DB.

    A selected genre uses 2..50 current reference profiles. A saved recipe is
    the *set of reference IDs*, not text or a frozen statistical result. On
    reload it re-reads and re-calculates profiles and rejects changed cohorts.
    """

    def __init__(self, catalog: ReferenceCatalog) -> None:
        if not isinstance(catalog, ReferenceCatalog):
            raise GenreStorageError("로컬 SQLite 참고작 저장소가 필요합니다.")
        self._db = catalog._db
        self._profiles = ReferenceProfileStore(catalog)
        # All values in this SQL constraint originate from the code-owned,
        # constant-only taxonomy. Never concatenate user input into SQL.
        genres_sql = ", ".join("'" + key + "'" for key in GENRE_NAMES)
        with self._db:
            self._db.execute(f"""
                CREATE TABLE IF NOT EXISTS reference_genres (
                    reference_id TEXT PRIMARY KEY REFERENCES reference_files(reference_id)
                        ON DELETE CASCADE,
                    genre TEXT NOT NULL CHECK(genre IN ({genres_sql}))
                )
            """)
            self._db.execute("CREATE INDEX IF NOT EXISTS ix_reference_genres_genre ON reference_genres(genre)")
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS genre_pattern_selections (
                    genre TEXT NOT NULL,
                    weighting TEXT NOT NULL CHECK(weighting IN ('equal', 'characters')),
                    reference_ids_json TEXT NOT NULL CHECK(length(reference_ids_json) <= 1800),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(genre, weighting)
                )
            """)

    def assign(self, reference_id: str, genre: str) -> None:
        """Only a user explicitly chooses a genre; there is no classifier."""
        _check_id(reference_id)
        _check_genre(genre)
        try:
            self._profiles.get(reference_id)
        except (ProfileStorageError, ReferenceParseError):
            raise GenreStorageError("해당 참고작의 분석 프로필이 없습니다.") from None
        with self._db:
            self._db.execute("""
                INSERT INTO reference_genres(reference_id, genre) VALUES (?, ?)
                ON CONFLICT(reference_id) DO UPDATE SET genre=excluded.genre
            """, (reference_id, genre))

    def unassign(self, reference_id: str) -> bool:
        _check_id(reference_id)
        with self._db:
            return self._db.execute("DELETE FROM reference_genres WHERE reference_id=?",
                                    (reference_id,)).rowcount > 0

    def list_assignments(self, genre: str | None = None) -> tuple[tuple[str, str], ...]:
        if genre is not None:
            _check_genre(genre)
        if genre is None:
            rows = self._db.execute("SELECT reference_id, genre FROM reference_genres "
                                    "ORDER BY genre, reference_id").fetchall()
        else:
            rows = self._db.execute("SELECT reference_id, genre FROM reference_genres "
                                    "WHERE genre=? ORDER BY reference_id", (genre,)).fetchall()
        for row in rows:
            _check_id(row["reference_id"])
            _check_genre(row["genre"])
        return tuple((row["reference_id"], row["genre"]) for row in rows)

    def _genre_ids(self, genre: str) -> tuple[str, ...]:
        ids = tuple(ref for ref, _ in self.list_assignments(genre))
        if not 2 <= len(ids) <= MAX_COLLECTION_REFERENCES:
            raise GenreStorageError("해당 장르에는 분석 완료 참고작 2~50개가 필요합니다.")
        return ids

    def _load(self, genre: str, weighting: str, ids: tuple[str, ...]) -> GenrePattern:
        profiles = []
        for reference_id in ids:
            try:
                profiles.append(self._profiles.get(reference_id))
            except (ProfileStorageError, ReferenceParseError):
                raise GenreStorageError("선택된 참고작 프로필이 누락되거나 손상됐습니다.") from None
        try:
            return build_genre_pattern(genre, profiles, weighting=weighting)
        except ReferenceParseError:
            raise GenreStorageError("장르 패턴을 계산하지 못했습니다.") from None

    def build(self, genre: str, *, weighting: str = "equal", save: bool = True) -> GenrePattern:
        """Compute first; write selection only after all source profiles pass."""
        _check_genre(genre)
        _check_weighting(weighting)
        ids = self._genre_ids(genre)
        pattern = self._load(genre, weighting, ids)
        if type(save) is not bool:
            raise GenreStorageError("저장 설정이 올바르지 않습니다.")
        if save:
            at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
            payload = json.dumps(ids, separators=(",", ":"))
            with self._db:
                self._db.execute("""
                    INSERT INTO genre_pattern_selections
                        (genre, weighting, reference_ids_json, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(genre, weighting) DO UPDATE SET
                      reference_ids_json=excluded.reference_ids_json,
                      updated_at=excluded.updated_at
                """, (genre, weighting, payload, at))
        return pattern

    def _saved_ids(self, raw: str) -> tuple[str, ...]:
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            raise GenreStorageError("저장된 장르 선정 정보가 손상됐습니다.") from None
        if (type(parsed) is not list or not 2 <= len(parsed) <= MAX_COLLECTION_REFERENCES
                or any(type(x) is not str or _ID.fullmatch(x) is None for x in parsed)
                or len(set(parsed)) != len(parsed) or parsed != sorted(parsed)):
            raise GenreStorageError("저장된 장르 선정 정보가 손상됐습니다.")
        return tuple(parsed)

    def get(self, genre: str, *, weighting: str = "equal") -> GenrePattern:
        """Fail closed on cohort changes; never silently mix genres."""
        _check_genre(genre)
        _check_weighting(weighting)
        row = self._db.execute("""
            SELECT reference_ids_json FROM genre_pattern_selections
            WHERE genre=? AND weighting=?
        """, (genre, weighting)).fetchone()
        if row is None:
            raise GenreStorageError("저장된 장르 패턴이 없습니다.")
        ids = self._saved_ids(row["reference_ids_json"])
        if ids != self._genre_ids(genre):
            raise GenreStorageError("장르 분류가 변경되었습니다. 패턴을 다시 구축하세요.")
        return self._load(genre, weighting, ids)

    def list_patterns(self) -> tuple[SavedGenreSelection, ...]:
        rows = self._db.execute("""
            SELECT genre, weighting, reference_ids_json, updated_at
            FROM genre_pattern_selections ORDER BY genre, weighting
        """).fetchall()
        result = []
        for row in rows:
            _check_genre(row["genre"])
            _check_weighting(row["weighting"])
            ids = self._saved_ids(row["reference_ids_json"])
            current = ids == tuple(ref for ref, _ in self.list_assignments(row["genre"]))
            result.append(SavedGenreSelection(row["genre"], row["weighting"],
                                              len(ids), row["updated_at"], current))
        return tuple(result)

    def delete(self, genre: str, *, weighting: str = "equal") -> bool:
        """Remove derived selection recipe only; original profiles untouched."""
        _check_genre(genre)
        _check_weighting(weighting)
        with self._db:
            return self._db.execute("""
                DELETE FROM genre_pattern_selections WHERE genre=? AND weighting=?
            """, (genre, weighting)).rowcount > 0
