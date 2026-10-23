"""Independent, explicit local publication authorization for an existing work.

This module does NOT publish, upload, export, email, launch a browser, or
convert a private EPUB preview into a release. It only records or revokes the
author's *separate* authorization for an exact already-reviewed local snapshot.
The authorization is invalidated if any final chapter, QC result or human
review state changes. The author must explicitly approve again afterward.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from uuid import uuid4

from .database.episodes import EpisodeStore
from .database.novel_bible import _now
from .manual_review_gate import review_state


class PublicationReleaseError(ValueError):
    """Never include original prose, manuscript paths, or account data."""


@dataclass(frozen=True)
class PublicationReadiness:
    project_id: str
    title: str
    through_episode: int
    source_sha256: str
    incomplete_episodes: tuple[int, ...]
    status: str
    publication_approved: bool = False


def _require(store: EpisodeStore, project_id: str, count: int):
    if (not isinstance(store, EpisodeStore) or type(project_id) is not str
            or type(count) is not int or not 1 <= count <= 1000):
        raise PublicationReleaseError('기존 작품과 출판 대상 회차를 확인하세요.')


def publication_readiness(store: EpisodeStore, project_id: str, *,
                          through_episode: int) -> PublicationReadiness:
    """Read-only review of *stored* final manuscripts and QC records.

    All 10 expected categories must have a current PASS record, and the
    separate author review ledger must still match that chapter snapshot.
    Even this readiness is NOT a proof of literary quality or user consent.
    """
    _require(store, project_id, through_episode)
    project = store.get_project(project_id)
    chapters = {row.episode: row for row in store.list_episodes(project_id)}
    incomplete = []
    state_rows = []
    for number in range(1, through_episode + 1):
        ep = chapters.get(number)
        if ep is None or not ep.final_text.strip():
            incomplete.append(number)
            state_rows.append((number, 'MISSING'))
            continue
        state = review_state(store, project_id, number)
        if state.status != 'REVIEWED_QC_RECORDED_NOT_PUBLISHED':
            incomplete.append(number)
        state_rows.append((number, ep.revision,
            sha256(ep.final_text.encode('utf-8')).hexdigest(),
            state.snapshot_sha256, state.status, state.incomplete_checks))
    # Snapshot intentionally excludes a publication ledger write's project
    # revision. Authoring or QC edits change per-chapter hashes/review states.
    source = sha256(json.dumps((project_id, project.title, through_episode, state_rows),
                         ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
    return PublicationReadiness(project_id, project.title, through_episode, source,
        tuple(incomplete), 'QC_AND_HUMAN_REVIEW_RECORDED' if not incomplete
        else 'BLOCKED_INCOMPLETE_OR_STALE')


def _ledger_exists(store: EpisodeStore) -> bool:
    return store._db.execute('''SELECT 1 FROM sqlite_master
        WHERE type='table' AND name='bible_publication_authorizations' ''').fetchone() is not None


def _create_ledger(store: EpisodeStore):
    store._db.execute('''CREATE TABLE IF NOT EXISTS bible_publication_authorizations (
        event_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        through_episode INTEGER NOT NULL,
        source_sha256 TEXT NOT NULL,
        action TEXT NOT NULL CHECK(action IN ('AUTHORIZED','REVOKED')),
        created_at TEXT NOT NULL,
        FOREIGN KEY(project_id) REFERENCES bible_projects(project_id) ON DELETE CASCADE
    )''')
    store._db.execute('''CREATE INDEX IF NOT EXISTS ix_publication_authorizations
        ON bible_publication_authorizations(project_id, through_episode, created_at)''')


def publication_authorization_state(store: EpisodeStore, project_id: str, *,
                                    through_episode: int) -> PublicationReadiness:
    plan = publication_readiness(store, project_id, through_episode=through_episode)
    if not _ledger_exists(store):
        return plan
    event = store._db.execute('''SELECT action, source_sha256
        FROM bible_publication_authorizations
        WHERE project_id=? AND through_episode=? ORDER BY rowid DESC LIMIT 1''',
        (project_id, through_episode)).fetchone()
    if event is None or event['action'] != 'AUTHORIZED':
        return plan
    if event['source_sha256'] != plan.source_sha256 or plan.incomplete_episodes:
        return PublicationReadiness(project_id, plan.title, through_episode,
                                    plan.source_sha256, plan.incomplete_episodes,
                                    'STALE_OR_INCOMPLETE_AUTHORIZATION', False)
    return PublicationReadiness(project_id, plan.title, through_episode,
                                plan.source_sha256, (),
                                'AUTHOR_AUTHORIZED_LOCAL_SNAPSHOT_NOT_PUBLISHED', True)


def authorize_publication_snapshot(store: EpisodeStore, project_id: str, *,
                                   through_episode: int, expected_source_sha256: str,
                                   confirmation: str, human_checked: bool,
                                   publication_scope_understood: bool) -> PublicationReadiness:
    """Record a one-time local authorization only after two explicit consents.

    It is not an upload command and cannot bypass missing/stale QC or reviews.
    """
    _require(store, project_id, through_episode)
    if (human_checked is not True or publication_scope_understood is not True
            or type(expected_source_sha256) is not str):
        raise PublicationReleaseError('별도 출판 승인을 위해 두 항목을 직접 확인하세요.')
    with store._db:
        store._db.execute('BEGIN IMMEDIATE')
        plan = publication_readiness(store, project_id,
                                     through_episode=through_episode)
        phrase = f'출판 승인 {plan.title} {through_episode}화'
        if confirmation != phrase:
            raise PublicationReleaseError('작품명·회차가 포함된 출판 승인 문구가 다릅니다.')
        if plan.incomplete_episodes or plan.source_sha256 != expected_source_sha256:
            raise PublicationReleaseError('원고·검수·검사 기록이 미완료 또는 변경되었습니다.')
        _create_ledger(store)
        store._db.execute('''INSERT INTO bible_publication_authorizations
            (event_id,project_id,through_episode,source_sha256,action,created_at)
            VALUES (?,?,?,?, 'AUTHORIZED', ?)''',
            (uuid4().hex, project_id, through_episode, plan.source_sha256, _now()))
    return publication_authorization_state(store, project_id,
                                           through_episode=through_episode)


def revoke_publication_authorization(store: EpisodeStore, project_id: str, *,
                                     through_episode: int, confirmation: str):
    _require(store, project_id, through_episode)
    if confirmation != f'출판 승인 철회 {through_episode}화':
        raise PublicationReleaseError('출판 승인 철회 문구를 직접 입력해야 합니다.')
    with store._db:
        store._db.execute('BEGIN IMMEDIATE')
        _create_ledger(store)
        store._db.execute('''INSERT INTO bible_publication_authorizations
            (event_id,project_id,through_episode,source_sha256,action,created_at)
            VALUES (?,?,?,?, 'REVOKED', ?)''',
            (uuid4().hex, project_id, through_episode, '', _now()))
    return publication_authorization_state(store, project_id,
                                           through_episode=through_episode)
