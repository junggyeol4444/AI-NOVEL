"""Stage 37: user-confirmed, offline statistical pattern-use audit trail.

Only fixed genre/feature codes, anonymous record UUIDs, a numeric similarity,
UTC timestamp and a SHA-256 fingerprint of aggregate *numbers* are persisted.
Never store original reference text, filenames, source quotes, project names,
paths, prompts, AI outputs, or raw excerpts. Search activity is NOT recorded.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
import re
from uuid import uuid4

from ai_novel_factory.database.reference_catalog import ReferenceCatalog
from ai_novel_factory.database.element_selections import ElementSelectionStore, ElementSelectionStorageError
from ai_novel_factory.references.element_selection import FEATURE_KEYS
from ai_novel_factory.references.genre_patterns import GENRE_NAMES
from ai_novel_factory.references.related_pattern_search import (
    MAX_RESULTS, RelatedPatternError, RelatedPatternSearch,
)

_ID = re.compile(r"[0-9a-f]{32}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00\Z")
_MAX_PAGE = 100


class PatternUsageError(ValueError):
    """Privacy-preserving validation error (no external string echoed)."""


@dataclass(frozen=True)
class PatternUsageRecord:
    usage_id: str
    source_genre: str
    pattern_genre: str
    weighting: str
    selected_keys: tuple[str, ...]
    similarity_percent: float | None
    created_at: str
    current: bool


def _genres(source: str, target: str, weighting: str) -> None:
    if type(source) is not str or source not in GENRE_NAMES:
        raise PatternUsageError("기준 장르 코드가 올바르지 않습니다.")
    if type(target) is not str or target not in GENRE_NAMES:
        raise PatternUsageError("선택한 패턴 장르 코드가 올바르지 않습니다.")
    if type(weighting) is not str or weighting not in ("equal", "characters"):
        raise PatternUsageError("가중치 설정이 올바르지 않습니다.")


def _id(value: object) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise PatternUsageError("사용 기록 ID가 올바르지 않습니다.")
    return value


def _selection_snapshot(selections: ElementSelectionStore, search: RelatedPatternSearch,
                        source: str, target: str, weighting: str):
    """Re-evaluate the selected numeric recipe; reject stale/unsafe patterns."""
    try:
        selected = selections.get(source, weighting=weighting)
        if (selected.genre != source or selected.weighting != weighting
                or not 1 <= len(selected.selected_keys) <= len(FEATURE_KEYS)
                or len(selected.selected_keys) != len(selected.elements)
                or any(item.key != key or type(item.observed_mean) not in (int, float)
                       or not isfinite(item.observed_mean)
                       for key, item in zip(selected.selected_keys, selected.elements))):
            raise PatternUsageError("선택된 통계 요소가 유효하지 않습니다.")
        # Explicitly use the same stage-36 safeguards for other-genre patterns.
        differences = ()
        similarity = None
        if target != source:
            matches = search.search(source, weighting=weighting, limit=MAX_RESULTS).matches
            match = next((match for match in matches if match.genre == target), None)
            if match is None:
                raise PatternUsageError("선택한 패턴이 오래됐거나 편중 기준을 통과하지 못했습니다.")
            differences = tuple((m.key, m.distance) for m in match.differences)
            similarity = match.similarity_percent
        fingerprint_data = [source, target, weighting, list(selected.selected_keys),
                            selected.reference_count, selected.max_share_percent,
                            [[item.key, item.observed_mean] for item in selected.elements],
                            differences, similarity]
        fingerprint = sha256(json.dumps(fingerprint_data, ensure_ascii=True,
                                        separators=(",", ":"), allow_nan=False).encode("ascii")).hexdigest()
        return selected.selected_keys, similarity, fingerprint
    except (ElementSelectionStorageError, RelatedPatternError, OverflowError, TypeError):
        raise PatternUsageError("패턴 구성이 없거나 최신 상태가 아닙니다.") from None


def _record(row, current: bool) -> PatternUsageRecord:
    try:
        uid = _id(row["usage_id"])
        source, target, weighting = row["source_genre"], row["pattern_genre"], row["weighting"]
        _genres(source, target, weighting)
        keys = json.loads(row["keys_json"])
        if (type(keys) is not list or not 1 <= len(keys) <= len(FEATURE_KEYS)
                or any(type(k) is not str or k not in FEATURE_KEYS for k in keys)
                or len(set(keys)) != len(keys)
                or tuple(keys) != tuple(k for k in FEATURE_KEYS if k in keys)):
            raise ValueError("noncanonical")
        similarity = row["similarity_percent"]
        if (similarity is not None and
            (type(similarity) not in (int, float) or not isfinite(similarity)
             or not 0 <= similarity <= 100)):
            raise ValueError("bad similarity")
        if (source == target) != (similarity is None):
            raise ValueError("bad similarity mode")
        if type(row["signature"]) is not str or not _HASH.fullmatch(row["signature"]):
            raise ValueError("bad fingerprint")
        if (type(row["created_at"]) is not str or not _TIME.fullmatch(row["created_at"])):
            raise ValueError("bad timestamp")
        datetime.fromisoformat(row["created_at"])
    except (TypeError, ValueError, KeyError, IndexError, OverflowError):
        raise PatternUsageError("저장된 사용 기록이 손상되었습니다.") from None
    return PatternUsageRecord(uid, source, target, weighting, tuple(keys),
                              float(similarity) if similarity is not None else None,
                              row["created_at"], current)


class PatternUsageStore:
    """A local append-only usage journal with explicit delete and freshness checks."""

    def __init__(self, catalog: ReferenceCatalog):
        if not isinstance(catalog, ReferenceCatalog):
            raise PatternUsageError("로컬 SQLite 참고작 저장소가 필요합니다.")
        self._db = catalog._db
        self._selections = ElementSelectionStore(catalog)
        self._search = RelatedPatternSearch(catalog)
        with self._db:
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS reference_pattern_usage (
                    usage_id TEXT PRIMARY KEY CHECK(length(usage_id)=32),
                    source_genre TEXT NOT NULL,
                    pattern_genre TEXT NOT NULL,
                    weighting TEXT NOT NULL CHECK(weighting IN ('equal','characters')),
                    keys_json TEXT NOT NULL CHECK(length(keys_json) BETWEEN 3 AND 256),
                    similarity_percent REAL,
                    signature TEXT NOT NULL CHECK(length(signature)=64),
                    created_at TEXT NOT NULL
                )
            """)
            self._db.execute("""
                CREATE INDEX IF NOT EXISTS ix_pattern_usage_time
                ON reference_pattern_usage(created_at DESC, usage_id DESC)
            """)
            self._db.execute("""
                CREATE INDEX IF NOT EXISTS ix_pattern_usage_genre_time
                ON reference_pattern_usage(source_genre, created_at DESC)
            """)

    def _snapshot(self, source: str, target: str, weighting: str):
        return _selection_snapshot(self._selections, self._search, source, target, weighting)

    def record(self, source_genre: str, *, pattern_genre: str | None = None,
               weighting: str = "equal") -> PatternUsageRecord:
        """Write one entry only on an explicit user action, never on search/view."""
        target = source_genre if pattern_genre is None else pattern_genre
        _genres(source_genre, target, weighting)
        keys, similarity, signature = self._snapshot(source_genre, target, weighting)
        uid = uuid4().hex
        timestamp = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        with self._db:
            self._db.execute("""
                INSERT INTO reference_pattern_usage
                (usage_id, source_genre, pattern_genre, weighting, keys_json,
                 similarity_percent, signature, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (uid, source_genre, target, weighting,
                  json.dumps(keys, separators=(",", ":")), similarity, signature, timestamp))
        return self.get(uid)

    def _decode(self, row, freshness_cache=None) -> PatternUsageRecord:
        # Validate all stored fields before passing them back to callers.
        preliminary = _record(row, False)
        cache_key = (preliminary.source_genre, preliminary.pattern_genre, preliminary.weighting)
        cached = freshness_cache.get(cache_key) if freshness_cache is not None else None
        if cached is None:
            try:
                cached = self._snapshot(*cache_key)
            except PatternUsageError:
                cached = ((), None, "")
            if freshness_cache is not None:
                freshness_cache[cache_key] = cached
        keys, similarity, signature = cached
        current = (keys == preliminary.selected_keys
                   and similarity == preliminary.similarity_percent
                   and signature == row["signature"])
        return PatternUsageRecord(preliminary.usage_id, preliminary.source_genre,
                                  preliminary.pattern_genre, preliminary.weighting,
                                  preliminary.selected_keys, preliminary.similarity_percent,
                                  preliminary.created_at, current)

    def get(self, usage_id: str) -> PatternUsageRecord:
        uid = _id(usage_id)
        row = self._db.execute(
            "SELECT * FROM reference_pattern_usage WHERE usage_id=?", (uid,)).fetchone()
        if row is None:
            raise PatternUsageError("사용 기록이 없습니다.")
        return self._decode(row)

    def list(self, *, source_genre: str | None = None,
             pattern_genre: str | None = None, current: bool | None = None,
             limit: int = 100, offset: int = 0) -> tuple[PatternUsageRecord, ...]:
        if source_genre is not None and (type(source_genre) is not str or source_genre not in GENRE_NAMES):
            raise PatternUsageError("검색할 기준 장르 코드가 올바르지 않습니다.")
        if pattern_genre is not None and (type(pattern_genre) is not str or pattern_genre not in GENRE_NAMES):
            raise PatternUsageError("검색할 패턴 장르 코드가 올바르지 않습니다.")
        if current is not None and type(current) is not bool:
            raise PatternUsageError("최신 상태 필터가 올바르지 않습니다.")
        if type(limit) is not int or not 1 <= limit <= _MAX_PAGE or type(offset) is not int or offset < 0:
            raise PatternUsageError("검색 범위가 올바르지 않습니다.")
        clauses, params = [], []
        if source_genre is not None:
            clauses.append("source_genre=?")
            params.append(source_genre)
        if pattern_genre is not None:
            clauses.append("pattern_genre=?")
            params.append(pattern_genre)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        # Freshness is dynamic; apply the current filter before pagination.
        # Cap work to a fixed bound for a GUI-friendly local query.
        if current is None:
            rows = self._db.execute(
                "SELECT * FROM reference_pattern_usage" + where
                + " ORDER BY created_at DESC, usage_id DESC LIMIT ? OFFSET ?",
                (*params, limit, offset)).fetchall()
            cache = {}
            return tuple(self._decode(row, cache) for row in rows)
        # Status filtering runs in bounded SQL batches to retain paging semantics.
        result = []
        scanned = 0
        cache = {}
        while len(result) < limit:
            batch = self._db.execute(
                "SELECT * FROM reference_pattern_usage" + where
                + " ORDER BY created_at DESC, usage_id DESC LIMIT 100 OFFSET ?",
                (*params, scanned)).fetchall()
            if not batch:
                break
            scanned += len(batch)
            for row in batch:
                item = self._decode(row, cache)
                if item.current is current:
                    if offset:
                        offset -= 1
                    else:
                        result.append(item)
                        if len(result) >= limit:
                            break
        return tuple(result)

    def count(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM reference_pattern_usage").fetchone()[0])

    def delete(self, usage_id: str) -> bool:
        uid = _id(usage_id)
        with self._db:
            return self._db.execute(
                "DELETE FROM reference_pattern_usage WHERE usage_id=?", (uid,)).rowcount > 0


def render_usage_record(record: PatternUsageRecord) -> str:
    """Render audited fixed-category identifiers only, never user prose."""
    if (type(record) is not PatternUsageRecord
            or type(record.usage_id) is not str or not _ID.fullmatch(record.usage_id)
            or type(record.source_genre) is not str or record.source_genre not in GENRE_NAMES
            or type(record.pattern_genre) is not str or record.pattern_genre not in GENRE_NAMES
            or record.weighting not in ("equal", "characters")
            or type(record.selected_keys) is not tuple
            or not 1 <= len(record.selected_keys) <= len(FEATURE_KEYS)
            or len(set(record.selected_keys)) != len(record.selected_keys)
            or any(key not in FEATURE_KEYS for key in record.selected_keys)
            or tuple(record.selected_keys) != tuple(k for k in FEATURE_KEYS if k in record.selected_keys)
            or type(record.created_at) is not str or not _TIME.fullmatch(record.created_at)
            or type(record.current) is not bool
            or ((record.source_genre == record.pattern_genre) != (record.similarity_percent is None))
            or (record.similarity_percent is not None
                and (type(record.similarity_percent) not in (int, float)
                     or not isfinite(record.similarity_percent)
                     or not 0 <= record.similarity_percent <= 100))):
        raise PatternUsageError("사용 기록 표시 형식이 올바르지 않습니다.")
    status = "현재 선택과 일치" if record.current else "구성 변경됨·재검토 필요"
    return (f"패턴 사용 기록: {record.usage_id}\n"
            f"기준 장르: {GENRE_NAMES[record.source_genre]}\n"
            f"참고 패턴: {GENRE_NAMES[record.pattern_genre]}\n"
            f"가중치: {record.weighting}\n"
            f"선택 요소: {', '.join(record.selected_keys)}\n"
            f"기록 시각(UTC): {record.created_at}\n"
            f"상태: {status}\n"
            "참고 통계의 사용 이력이며 원문·문체 복제나 실제 AI 집필 기록이 아닙니다.")
