"""Offline, author-triggered review acknowledgments for *current* final drafts.

A review acknowledgment is not a QC pass, a publication authorization, or
identity authentication. Nothing runs automatically and no manuscript text,
paths, secrets or source passages are persisted in this ledger.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from uuid import uuid4

from .database.episodes import EpisodeStore
from .database.novel_bible import _now
from .review_worklist import EXPECTED_CHECKS


class ManualReviewError(ValueError):
    """Deliberately omit the author's manuscript and private file paths."""


@dataclass(frozen=True)
class ReviewState:
    episode: int
    revision: int
    snapshot_sha256: str
    status: str
    incomplete_checks: tuple[str, ...]
    publication_approved: bool = False


@dataclass(frozen=True)
class ReviewReadiness:
    project_id: str
    total: int
    reviewed_current: int
    qc_complete: int
    pending_episodes: tuple[int, ...]
    publication_approved: bool = False


def _require_store(store: EpisodeStore) -> EpisodeStore:
    if not isinstance(store, EpisodeStore):
        raise ManualReviewError('현재 작품의 기존 로컬 회차 저장소가 필요합니다.')
    return store


def _snapshot(store: EpisodeStore, project_id: str, number: int):
    snap = store.snapshot(project_id, number)
    ep = snap.episode
    latest = {}
    for check in snap.checks:
        if check.category in EXPECTED_CHECKS and check.content_revision == ep.revision:
            latest[check.category] = (check.outcome, check.check_id)
    incomplete = tuple(category for category in EXPECTED_CHECKS
                       if category not in latest or latest[category][0] != 'PASS')
    digest = sha256(json.dumps({
        'project': project_id, 'episode': ep.episode, 'revision': ep.revision,
        'final_sha256': sha256(ep.final_text.encode('utf-8')).hexdigest(),
        'checks': [(c.category, c.check_id, c.content_revision, c.outcome)
                   for c in snap.checks if c.category in EXPECTED_CHECKS],
    }, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    return ep, digest, incomplete


def _has_ledger(store: EpisodeStore) -> bool:
    return store._db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                             "AND name='bible_human_review_events'").fetchone() is not None


def _latest_action(store: EpisodeStore, project_id: str, number: int):
    if not _has_ledger(store):
        return None
    return store._db.execute('''SELECT action, revision, snapshot_sha256
        FROM bible_human_review_events WHERE project_id=? AND episode=?
        ORDER BY rowid DESC LIMIT 1''', (project_id, number)).fetchone()


def review_state(store: EpisodeStore, project_id: str, number: int) -> ReviewState:
    store = _require_store(store)
    ep, digest, incomplete = _snapshot(store, project_id, number)
    action = _latest_action(store, project_id, number)
    if not ep.final_text.strip():
        status = 'NO_FINAL_MANUSCRIPT'
    elif action is None:
        status = 'UNREVIEWED'
    elif action['action'] == 'REVOKED':
        status = 'REVOKED'
    elif action['revision'] != ep.revision or action['snapshot_sha256'] != digest:
        status = 'STALE_REVIEW'
    elif incomplete:
        status = 'REVIEWED_QC_INCOMPLETE'
    else:
        status = 'REVIEWED_QC_RECORDED_NOT_PUBLISHED'
    return ReviewState(number, ep.revision, digest, status, incomplete)


def _create_ledger(store: EpisodeStore) -> None:
    store._db.execute('''CREATE TABLE IF NOT EXISTS bible_human_review_events (
        event_id TEXT PRIMARY KEY CHECK(length(event_id)=32),
        project_id TEXT NOT NULL REFERENCES bible_projects(project_id) ON DELETE CASCADE,
        episode INTEGER NOT NULL CHECK(episode BETWEEN 1 AND 1000000),
        revision INTEGER NOT NULL,
        snapshot_sha256 TEXT NOT NULL CHECK(length(snapshot_sha256)=64),
        action TEXT NOT NULL CHECK(action IN ('REVIEWED','REVOKED')),
        created_at TEXT NOT NULL,
        FOREIGN KEY(project_id, episode) REFERENCES bible_episodes(project_id, episode)
            ON DELETE CASCADE
    )''')
    store._db.execute('''CREATE INDEX IF NOT EXISTS ix_human_review_episode
        ON bible_human_review_events(project_id, episode, created_at)''')


def acknowledge_review(store: EpisodeStore, project_id: str, number: int, *,
                       expected_revision: int, expected_snapshot_sha256: str,
                       human_read: bool, incomplete_qc_understood: bool) -> ReviewState:
    """Append only after two deliberate human checks bound to this exact snapshot."""
    store = _require_store(store)
    if human_read is not True or incomplete_qc_understood is not True:
        raise ManualReviewError('직접 열람과 미완료 검사 확인을 모두 선택해야 합니다.')
    if type(expected_revision) is not int or type(expected_snapshot_sha256) is not str:
        raise ManualReviewError('원고 검수 대상 정보가 올바르지 않습니다.')
    with store._db:
        store._db.execute('BEGIN IMMEDIATE')
        ep, digest, _incomplete = _snapshot(store, project_id, number)
        if not ep.final_text.strip():
            raise ManualReviewError('저장된 최종 원고가 없어 검수 확인을 기록하지 않았습니다.')
        if ep.revision != expected_revision or digest != expected_snapshot_sha256:
            raise ManualReviewError('원고 또는 검사 기록이 변경되었습니다. 다시 읽고 확인하세요.')
        _create_ledger(store)
        store._db.execute('''INSERT INTO bible_human_review_events
            (event_id,project_id,episode,revision,snapshot_sha256,action,created_at)
            VALUES (?,?,?,?,?,'REVIEWED',?)''',
            (uuid4().hex, project_id, number, ep.revision, digest, _now()))
        store._bump_project(project_id)
    return review_state(store, project_id, number)


def revoke_review(store: EpisodeStore, project_id: str, number: int, *,
                  confirmation: str) -> ReviewState:
    store = _require_store(store)
    if type(confirmation) is not str or confirmation != f'REVOKE_REVIEW {number}':
        raise ManualReviewError('해당 회차의 검수 확인 철회를 명시해야 합니다.')
    with store._db:
        store._db.execute('BEGIN IMMEDIATE')
        ep, digest, _incomplete = _snapshot(store, project_id, number)
        _create_ledger(store)
        store._db.execute('''INSERT INTO bible_human_review_events
            (event_id,project_id,episode,revision,snapshot_sha256,action,created_at)
            VALUES (?,?,?,?,?,'REVOKED',?)''',
            (uuid4().hex, project_id, number, ep.revision, digest, _now()))
        store._bump_project(project_id)
    return review_state(store, project_id, number)


def project_review_readiness(store: EpisodeStore, project_id: str, *,
                             through_episode: int) -> ReviewReadiness:
    """Read-only local preflight, NEVER a publication permission or QC shortcut."""
    store = _require_store(store)
    if type(through_episode) is not int or not 1 <= through_episode <= 1000:
        raise ManualReviewError('검수할 마지막 회차가 올바르지 않습니다.')
    existing = {ep.episode for ep in store.list_episodes(project_id)}
    pending = []
    reviewed = qc_complete = 0
    for number in range(1, through_episode + 1):
        if number not in existing:
            pending.append(number)
            continue
        state = review_state(store, project_id, number)
        if state.status.startswith('REVIEWED_'):
            reviewed += 1
        if state.status == 'REVIEWED_QC_RECORDED_NOT_PUBLISHED':
            qc_complete += 1
        else:
            pending.append(number)
    return ReviewReadiness(project_id, through_episode, reviewed, qc_complete,
                           tuple(pending))
