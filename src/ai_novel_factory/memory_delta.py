"""Stage 81 / ANF-REQ-057: review-only memory deltas from explicitly marked final text.

An external user-approval assertion is REQUIRED; it is not verified identity or
publication authorization. No canon database writes, AI calls, or networking.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import re
import sqlite3
from pathlib import Path

from .database.episodes import EpisodeStore, EpisodeError
from .database.novel_bible import NovelBibleError

MAX_MARKERS = 200
MAX_VALUE = 1024
MARKER = re.compile(r'\[\[ANF_MEMORY\|([^\[\]\n\r]{1,4096})\]\]')
SHA = re.compile(r'[0-9a-f]{64}\Z')
KINDS = frozenset({'FACT', 'RELATIONSHIP', 'FORESHADOW'})
ACTIONS = frozenset({'INSTALL', 'REVISIT', 'RESOLVE', 'ABANDON'})


class MemoryDeltaError(ValueError):
    """Sanitized errors; never echo manuscript, marker contents or local paths."""


def _hash(s: str) -> str:
    return sha256(s.encode('utf-8')).hexdigest()


def _field(s: object) -> str:
    if (type(s) is not str or not s or len(s) > MAX_VALUE or s != s.strip()
            or '|' in s or '[[' in s or ']]' in s or '\x00' in s
            or any(ord(c) < 32 or ord(c) == 127 for c in s)):
        raise MemoryDeltaError('invalid memory annotation field')
    try:
        s.encode('utf-8')
    except UnicodeError:
        raise MemoryDeltaError('invalid memory annotation encoding') from None
    return s


@dataclass(frozen=True)
class FinalTextAttestation:
    """Caller-supplied assertion, NOT a cryptographic or identity verification."""
    project_id: str
    episode_number: int
    episode_revision: int
    final_sha256: str
    approval_reference: str
    explicitly_approved_by_user: bool


@dataclass(frozen=True)
class MemoryChange:
    kind: str
    fields: tuple[str, ...] = field(repr=False)
    start: int
    end: int
    marker_sha256: str
    change_id: str
    status: str = 'PENDING_HUMAN_REVIEW'


@dataclass(frozen=True)
class MemoryDelta:
    project_id: str
    episode_number: int
    episode_revision: int
    final_sha256: str
    approval_reference: str
    changes: tuple[MemoryChange, ...]
    status: str = 'PENDING_HUMAN_REVIEW_NOT_APPLIED'
    canon_applied: bool = False
    publication_approved: bool = False


def _source(store: EpisodeStore, evidence: FinalTextAttestation):
    if type(store) is not EpisodeStore or type(evidence) is not FinalTextAttestation:
        raise MemoryDeltaError('invalid final manuscript evidence')
    if (type(evidence.project_id) is not str or not re.fullmatch(r'[0-9a-f]{32}', evidence.project_id)
            or type(evidence.episode_number) is not int or not 1 <= evidence.episode_number <= 1_000_000
            or type(evidence.episode_revision) is not int or evidence.episode_revision < 1
            or type(evidence.final_sha256) is not str or SHA.fullmatch(evidence.final_sha256) is None
            or type(evidence.approval_reference) is not str
            or re.fullmatch(r'[A-Za-z0-9_-]{8,128}', evidence.approval_reference) is None
            or evidence.explicitly_approved_by_user is not True):
        raise MemoryDeltaError('explicit user finalization attestation required')
    try:
        episode = store.get_episode(evidence.project_id, evidence.episode_number)
    except (EpisodeError, NovelBibleError):
        raise MemoryDeltaError('final manuscript not available') from None
    if (episode.revision != evidence.episode_revision or not episode.final_text.strip()
            or _hash(episode.final_text) != evidence.final_sha256):
        raise MemoryDeltaError('final manuscript revision or hash mismatch')
    return episode


def extract_memory_delta(store: EpisodeStore, evidence: FinalTextAttestation) -> MemoryDelta:
    """Extract *only* explicit [[ANF_MEMORY|...]] annotations, never infer prose.

    Grammar: FACT|entity|statement; RELATIONSHIP|id1|id2|state;
    FORESHADOW|thread_id|action|note. Output is review-only.
    """
    episode = _source(store, evidence)
    text = episode.final_text
    matches = tuple(MARKER.finditer(text))
    if len(matches) > MAX_MARKERS:
        raise MemoryDeltaError('too many memory annotations')
    # Malformed/unclosed markers must not be silently accepted as successful extraction.
    if text.count('[[ANF_MEMORY') != len(matches):
        raise MemoryDeltaError('malformed memory annotation')
    changes = []
    for m in matches:
        pieces = m.group(1).split('|')
        if not pieces or pieces[0] not in KINDS:
            raise MemoryDeltaError('unsupported memory annotation kind')
        kind = pieces[0]
        expected = 3 if kind == 'FACT' else 4
        if len(pieces) != expected:
            raise MemoryDeltaError('invalid memory annotation arity')
        fields = tuple(_field(p) for p in pieces[1:])
        if kind == 'RELATIONSHIP' and fields[0] == fields[1]:
            raise MemoryDeltaError('self relationship not supported')
        if kind == 'FORESHADOW' and fields[1] not in ACTIONS:
            raise MemoryDeltaError('invalid foreshadow action')
        marker_sha = _hash(m.group(0))
        change_id = _hash(f'{evidence.project_id}|{evidence.episode_number}|{evidence.episode_revision}|{evidence.final_sha256}|{m.start()}|{marker_sha}')
        changes.append(MemoryChange(kind, fields, m.start(), m.end(), marker_sha, change_id))
    return MemoryDelta(evidence.project_id, evidence.episode_number,
                       evidence.episode_revision, evidence.final_sha256,
                       evidence.approval_reference, tuple(changes))


class MemoryDeltaReviewStore:
    """Separate SQLite review list. Never mutates Novel Bible canon or episode data."""

    def __init__(self, database_path: str | Path = ':memory:') -> None:
        self._db = sqlite3.connect(str(database_path))
        self._db.row_factory = sqlite3.Row
        self._db.execute('PRAGMA foreign_keys=ON')
        with self._db:
            self._db.execute('''CREATE TABLE IF NOT EXISTS memory_delta_reviews (
                change_id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                episode_number INTEGER NOT NULL, episode_revision INTEGER NOT NULL,
                final_sha256 TEXT NOT NULL, approval_reference TEXT NOT NULL,
                kind TEXT NOT NULL, fields_json TEXT NOT NULL,
                start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL,
                marker_sha256 TEXT NOT NULL, status TEXT NOT NULL
                CHECK(status='PENDING_HUMAN_REVIEW'))''')
            self._db.execute('''CREATE INDEX IF NOT EXISTS ix_memory_delta_episode
                ON memory_delta_reviews(project_id, episode_number, episode_revision)''')

    def close(self) -> None:
        self._db.close()

    def save(self, episode_store: EpisodeStore, evidence: FinalTextAttestation,
             delta: MemoryDelta) -> int:
        """Save all extracted review candidates atomically; duplicates are idempotent."""
        expected = extract_memory_delta(episode_store, evidence)
        if type(delta) is not MemoryDelta or delta != expected:
            raise MemoryDeltaError('memory change list does not match current final manuscript')
        try:
            with self._db:
                for c in delta.changes:
                    self._db.execute('''INSERT OR IGNORE INTO memory_delta_reviews
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (c.change_id, delta.project_id, delta.episode_number,
                         delta.episode_revision, delta.final_sha256,
                         delta.approval_reference, c.kind,
                         json.dumps(c.fields, ensure_ascii=False),
                         c.start, c.end, c.marker_sha256, c.status))
                    # INSERT OR IGNORE cannot mask conflicting/tampered stored rows.
                    row = self._db.execute('SELECT * FROM memory_delta_reviews WHERE change_id=?',
                                           (c.change_id,)).fetchone()
                    if (row is None or row['project_id'] != delta.project_id
                            or row['episode_number'] != delta.episode_number
                            or row['episode_revision'] != delta.episode_revision
                            or row['final_sha256'] != delta.final_sha256
                            or row['approval_reference'] != delta.approval_reference
                            or row['kind'] != c.kind
                            or row['fields_json'] != json.dumps(c.fields, ensure_ascii=False)
                            or row['start_offset'] != c.start or row['end_offset'] != c.end
                            or row['marker_sha256'] != c.marker_sha256
                            or row['status'] != c.status):
                        raise MemoryDeltaError('stored memory review row conflict')
        except sqlite3.DatabaseError:
            raise MemoryDeltaError('memory review storage failure') from None
        return len(delta.changes)

    def list_review(self, episode_store: EpisodeStore, evidence: FinalTextAttestation) -> tuple[MemoryChange, ...]:
        """Return only current, revalidated entries; never return stale or altered data."""
        expected = extract_memory_delta(episode_store, evidence)
        rows = self._db.execute('''SELECT * FROM memory_delta_reviews
            WHERE project_id=? AND episode_number=? AND episode_revision=?
            ORDER BY start_offset''', (evidence.project_id, evidence.episode_number,
                                      evidence.episode_revision)).fetchall()
        if len(rows) != len(expected.changes):
            raise MemoryDeltaError('review list incomplete or stale')
        for row, c in zip(rows, expected.changes):
            if (row['change_id'] != c.change_id or row['kind'] != c.kind
                    or row['fields_json'] != json.dumps(c.fields, ensure_ascii=False)
                    or row['start_offset'] != c.start or row['end_offset'] != c.end
                    or row['marker_sha256'] != c.marker_sha256
                    or row['final_sha256'] != expected.final_sha256
                    or row['approval_reference'] != expected.approval_reference
                    or row['status'] != 'PENDING_HUMAN_REVIEW'):
                raise MemoryDeltaError('review list altered')
        return expected.changes
