"""Stage 82 / ANF-REQ-058: explicitly reviewed Memory Delta -> local Novel Bible.

The caller's approval assertion is NOT independently authenticated. This module
never approves publication, edits a manuscript, uses an AI model, or makes network
requests. All canon changes and the idempotency journal share ONE SQLite commit.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
import sqlite3
from pathlib import Path
from uuid import uuid4

from .database.episodes import EpisodeStore
from .database.characters import CharacterStore
from .database.relationships import RelationshipStore, _pair, _relationship
from .database.world_canon import WorldCanonStore
from .database.event_timeline import EventTimelineStore
from .database.foreshadow import ForeshadowStore, _title, MAX_EVENTS
from .database.novel_bible import NovelBibleError, _id, _now, _revision
from .memory_delta import (FinalTextAttestation, MemoryDeltaReviewStore,
                           MemoryDeltaError, MemoryChange)

REF = re.compile(r'[A-Za-z0-9_-]{8,128}\Z')
SHA = re.compile(r'[0-9a-f]{64}\Z')
FACT_TARGETS = frozenset({'character', 'world', 'timeline'})


class MemoryApplicationError(ValueError):
    """Error messages never include private prose or paths."""


@dataclass(frozen=True)
class MemoryApproval:
    change_id: str
    target_kind: str  # FACT -> character/world/timeline; otherwise relationship/foreshadow
    target_id: str  # FACT -> existing canon ID; FORESHADOW -> thread ID; RELATIONSHIP -> ''
    reviewer_reference: str
    explicitly_approved_by_user: bool
    expected_target_revision: int | None = None
    new_thread_title: str = ''  # only FORESHADOW INSTALL; explicit user-supplied title


@dataclass(frozen=True)
class ApplicationResult:
    project_id: str
    episode_number: int
    applied: int
    already_applied: int
    publication_approved: bool = False


def _fingerprint(payload: object) -> str:
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':')).encode('utf-8')).hexdigest()


def _check_approval(change: MemoryChange, approval: MemoryApproval) -> None:
    if (type(approval) is not MemoryApproval or type(approval.change_id) is not str
            or SHA.fullmatch(approval.change_id) is None
            or approval.change_id != change.change_id
            or type(approval.reviewer_reference) is not str
            or REF.fullmatch(approval.reviewer_reference) is None
            or approval.explicitly_approved_by_user is not True
            or type(approval.target_kind) is not str
            or type(approval.target_id) is not str
            or type(approval.new_thread_title) is not str):
        raise MemoryApplicationError('explicit valid memory approval required')
    if change.kind == 'FACT':
        if (approval.target_kind not in FACT_TARGETS or approval.target_id != change.fields[0]
                or approval.new_thread_title or type(approval.expected_target_revision) is not int):
            raise MemoryApplicationError('invalid fact target or revision')
        _id(approval.target_id)
        _revision(approval.expected_target_revision)
    elif change.kind == 'RELATIONSHIP':
        if (approval.target_kind != 'relationship' or approval.target_id != ''
                or approval.expected_target_revision is not None or approval.new_thread_title):
            raise MemoryApplicationError('invalid relationship approval')
        _id(change.fields[0]); _id(change.fields[1])
    elif change.kind == 'FORESHADOW':
        if approval.target_kind != 'foreshadow' or approval.target_id != change.fields[0]:
            raise MemoryApplicationError('invalid foreshadow target')
        _id(approval.target_id)
        if change.fields[1] == 'INSTALL':
            if approval.expected_target_revision is not None:
                raise MemoryApplicationError('new foreshadow title required')
            _title(approval.new_thread_title)
        elif approval.new_thread_title or type(approval.expected_target_revision) is not int:
            raise MemoryApplicationError('existing foreshadow revision required')
        if approval.expected_target_revision is not None:
            _revision(approval.expected_target_revision)
    else:
        raise MemoryApplicationError('unsupported memory change kind')


class MemoryCanonStore(RelationshipStore, WorldCanonStore, ForeshadowStore, EventTimelineStore):
    """All stage 42/44/45/46/47 canon tables plus stage 82 journal, one connection.

    Fact annotations are *linked* to an existing Character/World/Timeline item;
    they do not silently overwrite that item's user-authored fields. Relationship
    and foreshadow annotations add native chronology records after validation.
    """

    def __init__(self, database_path: str | Path = ':memory:') -> None:
        super().__init__(database_path)
        with self._db:
            self._db.execute('''CREATE UNIQUE INDEX IF NOT EXISTS
                ux_memory_world_project_id ON bible_world_entries(project_id, entry_id)''')
            self._db.execute('''CREATE TABLE IF NOT EXISTS bible_memory_facts (
                change_id TEXT PRIMARY KEY CHECK(length(change_id)=64),
                project_id TEXT NOT NULL REFERENCES bible_projects(project_id) ON DELETE CASCADE,
                episode INTEGER NOT NULL CHECK(episode BETWEEN 1 AND 1000000),
                character_id TEXT, world_id TEXT, timeline_id TEXT,
                fact_text TEXT NOT NULL CHECK(length(fact_text) BETWEEN 1 AND 1024),
                CHECK ((character_id IS NOT NULL) + (world_id IS NOT NULL) +
                       (timeline_id IS NOT NULL) = 1),
                FOREIGN KEY(project_id, character_id) REFERENCES
                    bible_characters(project_id, character_id) ON DELETE CASCADE,
                FOREIGN KEY(project_id, world_id) REFERENCES
                    bible_world_entries(project_id, entry_id) ON DELETE CASCADE,
                FOREIGN KEY(project_id, timeline_id) REFERENCES
                    bible_timeline_events(project_id, event_id) ON DELETE CASCADE
            )''')
            self._db.execute('''CREATE INDEX IF NOT EXISTS ix_memory_facts_project
                ON bible_memory_facts(project_id, episode)''')
            self._db.execute('''CREATE TABLE IF NOT EXISTS bible_memory_applications (
                change_id TEXT PRIMARY KEY CHECK(length(change_id)=64),
                project_id TEXT NOT NULL REFERENCES bible_projects(project_id) ON DELETE CASCADE,
                episode INTEGER NOT NULL, source_sha256 TEXT NOT NULL,
                approval_reference TEXT NOT NULL, reviewer_reference TEXT NOT NULL,
                decision_sha256 TEXT NOT NULL CHECK(length(decision_sha256)=64),
                kind TEXT NOT NULL, target_kind TEXT NOT NULL, target_id TEXT NOT NULL,
                canon_record_id TEXT NOT NULL, canon_sha256 TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )''')

    # Existing stores reuse method names with different signatures. Dispatch
    # explicitly so the combined store cannot accidentally call the wrong API.
    def history(self, project_id: str, *args):
        if len(args) == 1:
            return ForeshadowStore.history(self, project_id, args[0])
        if len(args) == 2:
            return RelationshipStore.history(self, project_id, args[0], args[1])
        raise MemoryApplicationError('invalid history lookup')

    def get_event(self, project_id: str, *args):
        if len(args) == 1:
            return EventTimelineStore.get_event(self, project_id, args[0])
        if len(args) == 2:
            return ForeshadowStore.get_event(self, project_id, args[0], args[1])
        if len(args) == 3:
            return RelationshipStore.get_event(self, project_id, args[0], args[1], args[2])
        raise MemoryApplicationError('invalid event lookup')

    def get_at(self, project_id: str, *args):
        if len(args) == 2:
            return ForeshadowStore.get_at(self, project_id, args[0], args[1])
        if len(args) == 3:
            return RelationshipStore.get_at(self, project_id, args[0], args[1], args[2])
        raise MemoryApplicationError('invalid state lookup')

    def list_facts(self, project_id: str, target_kind: str, target_id: str) -> tuple[tuple[str, str], ...]:
        """Return (change_id, fact) for a validated existing target."""
        if target_kind not in FACT_TARGETS:
            raise MemoryApplicationError('invalid fact target')
        _id(project_id); _id(target_id)
        col = {'character': 'character_id', 'world': 'world_id', 'timeline': 'timeline_id'}[target_kind]
        return tuple((row['change_id'], row['fact_text']) for row in self._db.execute(
            f'SELECT change_id, fact_text FROM bible_memory_facts WHERE project_id=? AND {col}=? ORDER BY episode, change_id',
            (project_id, target_id)))

    def _canon_snapshot(self, kind: str, target: str, record_id: str,
                        project_id: str, episode: int, change: MemoryChange) -> object:
        if kind == 'FACT':
            row = self._db.execute('SELECT * FROM bible_memory_facts WHERE change_id=? AND project_id=?',
                                   (record_id, project_id)).fetchone()
            if row is None:
                raise MemoryApplicationError('applied fact record missing')
            return (row['project_id'], row['episode'], row['character_id'], row['world_id'],
                    row['timeline_id'], row['fact_text'])
        if kind == 'RELATIONSHIP':
            a, b = _pair(change.fields[0], change.fields[1])
            row = self._db.execute('''SELECT * FROM bible_relationship_events
                WHERE project_id=? AND first_character_id=? AND second_character_id=? AND episode=?''',
                (project_id, a, b, episode)).fetchone()
            if row is None:
                raise MemoryApplicationError('applied relationship record missing')
            return (row['project_id'], row['first_character_id'], row['second_character_id'],
                    row['episode'], row['relationship'], row['notes'], row['revision'])
        row = self._db.execute('''SELECT * FROM bible_foreshadow_events
            WHERE project_id=? AND event_id=? AND thread_id=?''',
            (project_id, record_id, target)).fetchone()
        if row is None:
            raise MemoryApplicationError('applied foreshadow record missing')
        return (row['project_id'], row['thread_id'], row['event_id'], row['episode'],
                row['sequence'], row['action'], row['note'])

    def _insert(self, project_id: str, episode: int, change: MemoryChange,
                approval: MemoryApproval) -> str:
        now = _now()
        if change.kind == 'FACT':
            # Target revisions are required, so stale human reviews never append to
            # a target whose authored details changed since review.
            if approval.target_kind == 'character':
                target = CharacterStore.get_character(self, project_id, approval.target_id)
            elif approval.target_kind == 'world':
                target = WorldCanonStore.get_entry(self, project_id, approval.target_id)
            else:
                target = EventTimelineStore.get_event(self, project_id, approval.target_id)
            if target.revision != approval.expected_target_revision:
                raise MemoryApplicationError('fact target revision changed')
            cols = {'character': (approval.target_id, None, None),
                    'world': (None, approval.target_id, None),
                    'timeline': (None, None, approval.target_id)}[approval.target_kind]
            self._db.execute('''INSERT INTO bible_memory_facts
                (change_id, project_id, episode, character_id, world_id, timeline_id, fact_text)
                VALUES (?,?,?,?,?,?,?)''',
                (change.change_id, project_id, episode, *cols, change.fields[1]))
            return change.change_id
        if change.kind == 'RELATIONSHIP':
            a, b = _pair(change.fields[0], change.fields[1])
            CharacterStore.get_character(self, project_id, a)
            CharacterStore.get_character(self, project_id, b)
            if self._db.execute('''SELECT 1 FROM bible_relationship_events WHERE
                project_id=? AND first_character_id=? AND second_character_id=? AND episode=?''',
                (project_id, a, b, episode)).fetchone():
                raise MemoryApplicationError('relationship event already authored')
            self._db.execute('''INSERT INTO bible_relationship_events VALUES
                (?,?,?,?,?,?,1,?)''', (project_id, a, b, episode,
                                     _relationship(change.fields[2]), '', now))
            return f'{a}:{b}:{episode}'
        thread_id, action, note = change.fields
        if action == 'INSTALL':
            if self._db.execute('''SELECT 1 FROM bible_foreshadow_threads
                WHERE project_id=? AND thread_id=?''', (project_id, thread_id)).fetchone():
                raise MemoryApplicationError('foreshadow thread already exists')
            self._db.execute('''INSERT INTO bible_foreshadow_threads VALUES
                (?,?,?,1,?,?)''', (project_id, thread_id, approval.new_thread_title, now, now))
            seq = 1
        else:
            thread = ForeshadowStore.get_thread(self, project_id, thread_id)
            if thread.revision != approval.expected_target_revision:
                raise MemoryApplicationError('foreshadow thread revision changed')
            row = self._db.execute('''SELECT COALESCE(MAX(sequence),0)+1 AS next
                FROM bible_foreshadow_events WHERE project_id=? AND thread_id=?''',
                (project_id, thread_id)).fetchone()
            seq = row['next']
            if seq > MAX_EVENTS:
                raise MemoryApplicationError('foreshadow event limit exceeded')
        event_id = uuid4().hex
        self._db.execute('''INSERT INTO bible_foreshadow_events VALUES
            (?,?,?,?,?,?,?,?)''', (project_id, thread_id, event_id, episode, seq, action, note, now))
        # Validate entire history including chronological backfills and terminal states.
        ForeshadowStore.audit(self, project_id)
        if action != 'INSTALL':
            self._db.execute('''UPDATE bible_foreshadow_threads
                SET revision=revision+1, updated_at=? WHERE project_id=? AND thread_id=?''',
                (now, project_id, thread_id))
        return event_id

    def apply(self, episode_store: EpisodeStore, review_store: MemoryDeltaReviewStore,
              evidence: FinalTextAttestation, approvals: tuple[MemoryApproval, ...]
              ) -> ApplicationResult:
        """Commit reviewed canon changes and idempotency records in one transaction.

        `approvals` may be a subset of the saved candidates. Replaying identical
        decisions is a no-op. Any mismatch rolls back *every new change*.
        """
        if (type(episode_store) is not EpisodeStore or
                type(review_store) is not MemoryDeltaReviewStore or
                type(approvals) is not tuple or not approvals or
                self._db.in_transaction):
            raise MemoryApplicationError('invalid memory application request')
        try:
            candidates = review_store.list_review(episode_store, evidence)
        except MemoryDeltaError:
            raise MemoryApplicationError('final manuscript review is invalid or stale') from None
        available = {c.change_id: c for c in candidates}
        if len(available) != len(candidates) or len(approvals) > len(available):
            raise MemoryApplicationError('invalid memory approval set')
        seen: set[str] = set()
        for approval in approvals:
            if type(approval) is not MemoryApproval or approval.change_id in seen:
                raise MemoryApplicationError('duplicate or invalid memory approval')
            seen.add(approval.change_id)
            change = available.get(approval.change_id)
            if change is None:
                raise MemoryApplicationError('approval not in reviewed manuscript')
            try:
                _check_approval(change, approval)
            except (NovelBibleError, MemoryApplicationError):
                raise MemoryApplicationError('invalid memory approval or target') from None
        applied = already = 0
        try:
            with self._db:
                self._db.execute('BEGIN IMMEDIATE')
                self.get_project(evidence.project_id)
                # Check again after acquiring the canon write lock. The episode and
                # review databases are separate connections; no distributed atomicity.
                if tuple(candidates) != review_store.list_review(episode_store, evidence):
                    raise MemoryApplicationError('review changed during application')
                for approval in approvals:
                    change = available[approval.change_id]
                    decision_hash = _fingerprint((change.change_id, change.kind, change.fields,
                        evidence.project_id, evidence.episode_number, evidence.episode_revision,
                        evidence.final_sha256, evidence.approval_reference,
                        approval.target_kind, approval.target_id, approval.reviewer_reference,
                        approval.expected_target_revision, approval.new_thread_title))
                    prior = self._db.execute('''SELECT * FROM bible_memory_applications
                        WHERE change_id=?''', (change.change_id,)).fetchone()
                    if prior is not None:
                        if (prior['project_id'] != evidence.project_id or
                                prior['episode'] != evidence.episode_number or
                                prior['source_sha256'] != evidence.final_sha256 or
                                prior['approval_reference'] != evidence.approval_reference or
                                prior['reviewer_reference'] != approval.reviewer_reference or
                                prior['decision_sha256'] != decision_hash or
                                prior['kind'] != change.kind or
                                prior['target_kind'] != approval.target_kind or
                                prior['target_id'] != approval.target_id or
                                (change.kind == 'FACT' and prior['canon_record_id'] != change.change_id) or
                                (change.kind == 'RELATIONSHIP' and
                                 prior['canon_record_id'] != ':'.join((*_pair(*change.fields[:2]), str(evidence.episode_number)))) or
                                (change.kind == 'FORESHADOW' and
                                 (type(prior['canon_record_id']) is not str or
                                  re.fullmatch(r'[0-9a-f]{32}', prior['canon_record_id']) is None)) or
                                prior['canon_sha256'] != _fingerprint(self._canon_snapshot(
                                    change.kind, approval.target_id, prior['canon_record_id'],
                                    evidence.project_id, evidence.episode_number, change))):
                            raise MemoryApplicationError('applied memory provenance conflict')
                        already += 1
                        continue
                    record_id = self._insert(evidence.project_id, evidence.episode_number,
                                             change, approval)
                    snap = self._canon_snapshot(change.kind, approval.target_id, record_id,
                                                evidence.project_id, evidence.episode_number, change)
                    self._db.execute('''INSERT INTO bible_memory_applications VALUES
                        (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (change.change_id, evidence.project_id, evidence.episode_number,
                         evidence.final_sha256, evidence.approval_reference,
                         approval.reviewer_reference, decision_hash, change.kind,
                         approval.target_kind, approval.target_id, record_id,
                         _fingerprint(snap), _now()))
                    self._db.execute('''UPDATE bible_projects SET revision=revision+1
                        WHERE project_id=?''', (evidence.project_id,))
                    applied += 1
        except (sqlite3.Error, NovelBibleError, MemoryDeltaError, ValueError, TypeError) as exc:
            if isinstance(exc, MemoryApplicationError):
                raise
            raise MemoryApplicationError('canon memory application failed; no new changes committed') from None
        return ApplicationResult(evidence.project_id, evidence.episode_number, applied, already)
