"""Stage 83: local, append-only manuscript snapshots for draft/revision/final.

FINAL means a local manuscript candidate, never authenticated publication approval.
All writes are explicit; older EpisodeStore callers are not silently intercepted.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import sqlite3
from uuid import uuid4

from ai_novel_factory.database.episodes import (
    EpisodeStore, EpisodeError, _content, _number, MAX_FIELD_BYTES)
from ai_novel_factory.database.novel_bible import _id, _now, _revision


class ManuscriptVersionError(EpisodeError):
    """Error strings intentionally contain no manuscript or local file paths."""


KINDS = frozenset({'BASELINE', 'DRAFT', 'REVISION', 'FINAL'})
MAX_VERSIONS = 5000


@dataclass(frozen=True)
class ManuscriptVersion:
    project_id: str
    episode: int
    version_id: str
    ordinal: int
    kind: str
    episode_revision: int
    draft: str
    final_text: str
    note: str
    created_at: str
    fingerprint: str
    publication_approved: bool = False

    def as_dict(self, *, reveal: bool = False) -> dict:
        return {
            'project_id': self.project_id, 'episode': self.episode,
            'version_id': self.version_id, 'ordinal': self.ordinal,
            'kind': self.kind, 'episode_revision': self.episode_revision,
            'draft': self.draft if reveal else '[redacted]',
            'final_text': self.final_text if reveal else '[redacted]',
            'note': self.note if reveal else '[redacted]',
            'created_at': self.created_at, 'fingerprint': self.fingerprint,
            'publication_approved': False,
        }


def _validated_content(value: object, *, limit: int) -> str:
    try:
        return _content(value, limit=limit)
    except EpisodeError:
        raise ManuscriptVersionError('원고 버전 입력 형식 또는 길이가 올바르지 않습니다.') from None


def _digest(fields: dict) -> str:
    raw = json.dumps(fields, ensure_ascii=False, sort_keys=True,
                     separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _record(row: sqlite3.Row) -> ManuscriptVersion:
    try:
        fields = {k: row[k] for k in (
            'project_id', 'episode', 'version_id', 'ordinal', 'kind',
            'episode_revision', 'draft', 'final_text', 'note', 'created_at')}
        _id(fields['project_id']); _id(fields['version_id'])
        _number(fields['episode']); _number(fields['ordinal'], maximum=MAX_VERSIONS)
        _revision(fields['episode_revision'])
        if fields['kind'] not in KINDS:
            raise ValueError
        _content(fields['draft'], limit=MAX_FIELD_BYTES['draft'])
        _content(fields['final_text'], limit=MAX_FIELD_BYTES['final_text'])
        _content(fields['note'], limit=2048)
        stamp = datetime.fromisoformat(fields['created_at'])
        if stamp.utcoffset() is None:
            raise ValueError
        digest = row['fingerprint']
        if type(digest) is not str or digest != _digest(fields):
            raise ValueError
        return ManuscriptVersion(**fields, fingerprint=digest)
    except (ValueError, KeyError, TypeError, IndexError, OverflowError, UnicodeError):
        raise ManuscriptVersionError('저장된 원고 버전 정보가 손상되었습니다.') from None


class ManuscriptVersionStore(EpisodeStore):
    """Snapshots and episode changes commit together in the same SQLite DB.

    Versioning applies to writes through this API only. Untracked EpisodeStore
    writes are detected on subsequent version operations (not auto-repaired).
    """

    def __init__(self, database_path=':memory:'):
        super().__init__(database_path)
        with self._db:
            self._db.execute('''CREATE TABLE IF NOT EXISTS bible_manuscript_versions (
                project_id TEXT NOT NULL, episode INTEGER NOT NULL,
                version_id TEXT NOT NULL CHECK(length(version_id)=32),
                ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 5000),
                kind TEXT NOT NULL CHECK(kind IN ('BASELINE','DRAFT','REVISION','FINAL')),
                episode_revision INTEGER NOT NULL CHECK(episode_revision>=1),
                draft TEXT NOT NULL, final_text TEXT NOT NULL,
                note TEXT NOT NULL, created_at TEXT NOT NULL,
                fingerprint TEXT NOT NULL CHECK(length(fingerprint)=64),
                PRIMARY KEY(project_id, episode, version_id),
                UNIQUE(project_id, episode, ordinal),
                FOREIGN KEY(project_id, episode) REFERENCES bible_episodes(project_id, episode)
                    ON DELETE CASCADE
            )''')
            self._db.execute('''CREATE INDEX IF NOT EXISTS ix_manuscript_versions
                ON bible_manuscript_versions(project_id, episode, ordinal)''')

    def _history(self, project_id: str, episode: int) -> tuple[ManuscriptVersion, ...]:
        rows = self._db.execute('''SELECT * FROM bible_manuscript_versions
            WHERE project_id=? AND episode=? ORDER BY ordinal''',
            (project_id, episode)).fetchall()
        if len(rows) > MAX_VERSIONS:
            raise ManuscriptVersionError('원고 버전 개수 제한을 초과했습니다.')
        versions = tuple(_record(r) for r in rows)
        for i, version in enumerate(versions, 1):
            if version.ordinal != i or (i > 1 and version.episode_revision <= versions[i-2].episode_revision):
                raise ManuscriptVersionError('저장된 원고 버전 순서가 손상되었습니다.')
        return versions

    def list_versions(self, project_id: str, episode: int) -> tuple[ManuscriptVersion, ...]:
        project_id, episode = _id(project_id), _number(episode)
        self.get_episode(project_id, episode)
        return self._history(project_id, episode)

    def get_version(self, project_id: str, episode: int, version_id: str) -> ManuscriptVersion:
        version_id = _id(version_id)
        for version in self.list_versions(project_id, episode):
            if version.version_id == version_id:
                return version
        raise ManuscriptVersionError('원고 버전을 찾을 수 없습니다.')

    def _insert(self, project_id: str, episode: int, kind: str, revision: int,
                draft: str, final_text: str, note: str, ordinal: int) -> ManuscriptVersion:
        fields = dict(project_id=project_id, episode=episode, version_id=uuid4().hex,
                      ordinal=ordinal, kind=kind, episode_revision=revision,
                      draft=draft, final_text=final_text, note=note, created_at=_now())
        digest = _digest(fields)
        self._db.execute('''INSERT INTO bible_manuscript_versions
            (project_id, episode, version_id, ordinal, kind, episode_revision,
             draft, final_text, note, created_at, fingerprint)
            VALUES (:project_id, :episode, :version_id, :ordinal, :kind, :episode_revision,
                    :draft, :final_text, :note, :created_at, :fingerprint)''',
            dict(fields, fingerprint=digest))
        return ManuscriptVersion(**fields, fingerprint=digest)

    def capture_current(self, project_id: str, episode: int, *, expected_revision: int,
                        note: str = '') -> ManuscriptVersion:
        """Explicitly preserve an existing manuscript before the first versioned edit."""
        project_id, episode, expected_revision = _id(project_id), _number(episode), _revision(expected_revision)
        note = _validated_content(note, limit=2048)
        with self._db:
            self._db.execute('BEGIN IMMEDIATE')
            current = self.get_episode(project_id, episode)
            if current.revision != expected_revision:
                raise ManuscriptVersionError('회차가 다른 작업에서 수정되었습니다.')
            if self._history(project_id, episode):
                raise ManuscriptVersionError('이미 원고 버전 이력이 있습니다.')
            if not current.draft and not current.final_text:
                raise ManuscriptVersionError('보존할 원고가 없습니다.')
            result = self._insert(project_id, episode, 'BASELINE', current.revision,
                                  current.draft, current.final_text, note, 1)
        return result

    def save_version(self, project_id: str, episode: int, text: str, *,
                     kind: str, expected_revision: int, note: str = '') -> ManuscriptVersion:
        project_id, episode, expected_revision = _id(project_id), _number(episode), _revision(expected_revision)
        if type(kind) is not str or kind not in KINDS - {'BASELINE'}:
            raise ManuscriptVersionError('원고 버전 유형이 올바르지 않습니다.')
        text = _validated_content(text, limit=MAX_FIELD_BYTES['draft' if kind != 'FINAL' else 'final_text'])
        if not text.strip():
            raise ManuscriptVersionError('빈 원고를 버전으로 저장할 수 없습니다.')
        note = _validated_content(note, limit=2048)
        with self._db:
            self._db.execute('BEGIN IMMEDIATE')
            current = self.get_episode(project_id, episode)
            if current.revision != expected_revision or current.revision >= 2**31 - 1:
                raise ManuscriptVersionError('회차가 다른 작업에서 수정되었습니다.')
            history = self._history(project_id, episode)
            if len(history) >= MAX_VERSIONS:
                raise ManuscriptVersionError('원고 버전 개수 제한을 초과했습니다.')
            if history:
                if history[-1].episode_revision != current.revision:
                    raise ManuscriptVersionError('버전 관리 밖에서 회차가 수정되었습니다.')
                if (history[-1].draft, history[-1].final_text) != (current.draft, current.final_text):
                    raise ManuscriptVersionError('현재 원고와 마지막 버전이 다릅니다.')
            elif current.draft or current.final_text:
                raise ManuscriptVersionError('기존 원고를 먼저 보존해야 합니다.')
            if kind == 'FINAL':
                draft, final_text = current.draft, text
            else:
                draft, final_text = text, ''  # previous final is invalidated by edits
            if (draft, final_text) == (current.draft, current.final_text):
                raise ManuscriptVersionError('동일한 원고를 중복 저장할 수 없습니다.')
            stamp = _now()
            self._db.execute('''UPDATE bible_episodes SET draft=?, final_text=?,
                revision=revision+1, updated_at=? WHERE project_id=? AND episode=?
                AND revision=?''', (draft, final_text, stamp, project_id, episode, expected_revision))
            self._bump_project(project_id)
            result = self._insert(project_id, episode, kind, expected_revision+1,
                                  draft, final_text, note, len(history)+1)
        return result

    def restore_as_revision(self, project_id: str, episode: int, version_id: str, *,
                            expected_revision: int, note: str = '') -> ManuscriptVersion:
        """Restore historical content as a NEW revision, never as an approved final."""
        target = self.get_version(project_id, episode, version_id)
        content = target.draft or target.final_text
        if not content:
            raise ManuscriptVersionError('복원할 원고가 없습니다.')
        return self.save_version(project_id, episode, content, kind='REVISION',
                                 expected_revision=expected_revision, note=note)

    def delete_episode(self, project_id: str, episode: int, *, expected_revision: int) -> None:
        if self.list_versions(project_id, episode):
            raise ManuscriptVersionError('버전 이력이 있는 회차는 삭제할 수 없습니다.')
        super().delete_episode(project_id, episode, expected_revision=expected_revision)
