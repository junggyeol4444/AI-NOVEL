"""Stage 35: explicit user-selected statistical feature recipes in local SQLite.

Stores fixed genre, weighting, feature keys, and timestamp. Every read
revalidates current genre membership and the 60% per-work cap; never persist
source text, author name, title, file path, or numeric prompt targets.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re

from .reference_catalog import ReferenceCatalog
from .genre_patterns import GenrePatternStore
from .pattern_strengths import PatternStrengthStore
from ai_novel_factory.references.element_selection import (
    ElementSelection, ElementSelectionError, FEATURE_KEYS,
    select_elements, validate_element_keys,
)
from ai_novel_factory.references.genre_patterns import GENRE_NAMES
from ai_novel_factory.references.pattern_strength import preview_strengths


class ElementSelectionStorageError(ValueError):
    """Redacted local database/validation problem."""


@dataclass(frozen=True)
class SavedElementSelection:
    genre: str
    weighting: str
    selected_keys: tuple[str, ...]
    updated_at: str
    current: bool


def _validate_key(genre: str, weighting: str) -> None:
    if type(genre) is not str or genre not in GENRE_NAMES:
        raise ElementSelectionStorageError("장르 코드가 올바르지 않습니다.")
    if type(weighting) is not str or weighting not in ("equal", "characters"):
        raise ElementSelectionStorageError("가중치 종류가 올바르지 않습니다.")


def _decode_keys(raw: object) -> tuple[str, ...]:
    try:
        data = json.loads(raw)
        keys = validate_element_keys(data)
        if list(keys) != data:
            raise ValueError("not canonical")
        return keys
    except (TypeError, ValueError, ElementSelectionError):
        raise ElementSelectionStorageError("저장된 통계 항목 설정이 손상되었습니다.") from None


class ElementSelectionStore:
    """All data reside in the user's ReferenceCatalog SQLite connection."""

    def __init__(self, catalog: ReferenceCatalog):
        if not isinstance(catalog, ReferenceCatalog):
            raise ElementSelectionStorageError("로컬 SQLite 참고작 저장소가 필요합니다.")
        self._db = catalog._db
        self._genres = GenrePatternStore(catalog)
        self._strengths = PatternStrengthStore(catalog)
        with self._db:
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS reference_element_selections (
                    genre TEXT NOT NULL,
                    weighting TEXT NOT NULL CHECK(weighting IN ('equal', 'characters')),
                    keys_json TEXT NOT NULL CHECK(length(keys_json) BETWEEN 3 AND 256),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(genre, weighting)
                )
            """)

    def _resolve(self, genre: str, weighting: str, keys: object) -> ElementSelection:
        _validate_key(genre, weighting)
        try:
            preview = preview_strengths(self._genres, self._strengths, genre, weighting=weighting)
            return select_elements(preview, keys)
        except (ValueError, TypeError, OverflowError):
            raise ElementSelectionStorageError(
                "장르 패턴이 오래됐거나 작품별 강도 편중 기준을 통과하지 못했습니다."
            ) from None

    def save(self, genre: str, keys: object, *, weighting: str = "equal") -> ElementSelection:
        _validate_key(genre, weighting)
        selected = validate_element_keys(keys)
        result = self._resolve(genre, weighting, selected)
        at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        encoded = json.dumps(selected, separators=(",", ":"))
        with self._db:
            self._db.execute("""
                INSERT INTO reference_element_selections(genre, weighting, keys_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(genre, weighting) DO UPDATE SET
                    keys_json=excluded.keys_json, updated_at=excluded.updated_at
            """, (genre, weighting, encoded, at))
        return result

    def get(self, genre: str, *, weighting: str = "equal") -> ElementSelection:
        _validate_key(genre, weighting)
        row = self._db.execute("""
            SELECT keys_json FROM reference_element_selections
            WHERE genre=? AND weighting=?
        """, (genre, weighting)).fetchone()
        if row is None:
            raise ElementSelectionStorageError("저장된 참고 요소 선택이 없습니다.")
        return self._resolve(genre, weighting, _decode_keys(row["keys_json"]))

    def list(self) -> tuple[SavedElementSelection, ...]:
        rows = self._db.execute("""
            SELECT genre, weighting, keys_json, updated_at
            FROM reference_element_selections ORDER BY genre, weighting
        """).fetchall()
        values = []
        for row in rows:
            genre, weighting = row["genre"], row["weighting"]
            _validate_key(genre, weighting)
            keys = _decode_keys(row["keys_json"])
            # Never interpolate stored timestamps or allow arbitrary DB text in UI.
            timestamp = row["updated_at"]
            if type(timestamp) is not str or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00", timestamp) is None:
                raise ElementSelectionStorageError("저장된 시각 값이 올바르지 않습니다.")
            try:
                self._resolve(genre, weighting, keys)
                current = True
            except ElementSelectionStorageError:
                current = False
            values.append(SavedElementSelection(genre, weighting, keys, timestamp, current))
        return tuple(values)

    def delete(self, genre: str, *, weighting: str = "equal") -> bool:
        _validate_key(genre, weighting)
        with self._db:
            return self._db.execute("""
                DELETE FROM reference_element_selections WHERE genre=? AND weighting=?
            """, (genre, weighting)).rowcount > 0
