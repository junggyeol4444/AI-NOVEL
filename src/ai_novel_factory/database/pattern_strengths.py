"""Stage 34: optional, per-reference influence settings in local SQLite.

Only an anonymous reference UUID and a bounded integer are persisted. There
is no source novel text, network call, author/style cloning or model action.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .reference_catalog import ReferenceCatalog
from .reference_profiles import ProfileStorageError, ReferenceProfileStore
from ai_novel_factory.references.plaintext_parser import ReferenceParseError

DEFAULT_STRENGTH = 50
MAX_STRENGTH = 100
_ID = re.compile(r"[0-9a-f]{32}\Z")


class PatternStrengthStorageError(ValueError):
    """Safe, redacted validation/storage failure."""


@dataclass(frozen=True)
class StrengthSetting:
    reference_id: str
    strength: int


def validate_reference_id(reference_id: str) -> None:
    if type(reference_id) is not str or _ID.fullmatch(reference_id) is None:
        raise PatternStrengthStorageError("참고작 식별자가 올바르지 않습니다.")


def validate_strength(strength: int) -> None:
    if type(strength) is not int or not 0 <= strength <= MAX_STRENGTH:
        raise PatternStrengthStorageError("패턴 강도는 0~100 사이의 정수여야 합니다.")


class PatternStrengthStore:
    """An opt-in local setting; missing rows represent the default 50.

    No changes are made to the genre cohort or stored statistical profiles.
    Deleting its source profile or owning reference cascades through the FK.
    """

    def __init__(self, catalog: ReferenceCatalog) -> None:
        if not isinstance(catalog, ReferenceCatalog):
            raise PatternStrengthStorageError("로컬 참고작 저장소가 필요합니다.")
        self._db = catalog._db
        self._profiles = ReferenceProfileStore(catalog)
        with self._db:
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS reference_pattern_strengths (
                    reference_id TEXT PRIMARY KEY REFERENCES reference_profiles(reference_id)
                        ON DELETE CASCADE,
                    strength INTEGER NOT NULL CHECK(typeof(strength) = 'integer'
                        AND strength BETWEEN 0 AND 100)
                )
            """)

    def _ensure_profile(self, reference_id: str) -> None:
        validate_reference_id(reference_id)
        try:
            self._profiles.get(reference_id)
        except (ProfileStorageError, ReferenceParseError):
            raise PatternStrengthStorageError("해당 참고작의 분석 프로필이 없습니다.") from None

    def get(self, reference_id: str) -> int:
        self._ensure_profile(reference_id)
        row = self._db.execute(
            "SELECT strength FROM reference_pattern_strengths WHERE reference_id=?",
            (reference_id,),
        ).fetchone()
        if row is None:
            return DEFAULT_STRENGTH
        value = row["strength"]
        validate_strength(value)
        return value

    def set(self, reference_id: str, strength: int) -> None:
        validate_strength(strength)
        self._ensure_profile(reference_id)
        with self._db:
            self._db.execute("""
                INSERT INTO reference_pattern_strengths (reference_id, strength)
                VALUES (?, ?)
                ON CONFLICT(reference_id) DO UPDATE SET strength=excluded.strength
            """, (reference_id, strength))

    def reset(self, reference_id: str) -> bool:
        self._ensure_profile(reference_id)
        with self._db:
            return self._db.execute(
                "DELETE FROM reference_pattern_strengths WHERE reference_id=?",
                (reference_id,),
            ).rowcount > 0

    def list_overrides(self) -> tuple[StrengthSetting, ...]:
        rows = self._db.execute("""
            SELECT s.reference_id, s.strength
            FROM reference_pattern_strengths AS s
            INNER JOIN reference_profiles AS p ON p.reference_id = s.reference_id
            ORDER BY s.reference_id
        """).fetchall()
        results = []
        for row in rows:
            validate_reference_id(row["reference_id"])
            validate_strength(row["strength"])
            results.append(StrengthSetting(row["reference_id"], row["strength"]))
        return tuple(results)
