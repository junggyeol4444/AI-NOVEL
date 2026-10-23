"""Explicit, offline SQLite snapshot of an existing author-owned project.

The source database is opened read-only. SQLite's online backup API copies a
consistent view including committed WAL data into a NEW, exclusive destination.
No restore/overwrite, model execution, publication, external sync or network.
A backup is not a verification or release certificate.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import os
import secrets
import sqlite3

from .sqlite_reopen_preview import preview_existing_sqlite, require_current_sqlite


class ProjectBackupError(ValueError):
    """No private paths, manuscript text, or database content in errors."""


def _stat(path: Path) -> tuple[int, int, int] | None:
    try:
        if path.is_symlink():
            raise ProjectBackupError('SQLite 경로에 링크를 사용할 수 없습니다.')
        st = path.stat()
        return st.st_size, st.st_mtime_ns, st.st_ino
    except FileNotFoundError:
        return None


def _source_identity(path: Path) -> tuple[tuple[int, int, int] | None, ...]:
    return (_stat(path), _stat(Path(str(path) + '-wal')),
            _stat(Path(str(path) + '-shm')))


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open('rb') as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                return digest.hexdigest()
            digest.update(block)


@dataclass(frozen=True)
class ProjectBackupPlan:
    source: Path = field(repr=False)
    project_id: str = field(repr=False)
    source_identity: tuple = field(repr=False)
    projects_count: int
    status: str = 'READ_ONLY_BACKUP_PLAN'


@dataclass(frozen=True)
class ProjectBackupReceipt:
    backup_file: Path = field(repr=False)
    manifest_file: Path = field(repr=False)
    project_id: str = field(repr=False)
    backup_sha256: str = field(repr=False)
    source_current_after_backup: bool
    status: str = 'PRIVATE_SNAPSHOT_NOT_VERIFIED'
    publication_approved: bool = False


@dataclass(frozen=True)
class ProjectBackupPreview:
    backup_file: Path = field(repr=False)
    project_count: int
    sha256_matches_manifest: bool
    contains_expected_project: bool
    status: str = 'READ_ONLY_BACKUP_PREVIEW_NOT_RESTORED'


def plan_project_backup(source: str | Path, project_id: str) -> ProjectBackupPlan:
    if type(project_id) is not str or not project_id or len(project_id) > 200:
        raise ProjectBackupError('현재 작품을 먼저 선택해야 합니다.')
    path = Path(source)
    try:
        preview = preview_existing_sqlite(path)
        if project_id not in {row[0] for row in preview.projects}:
            raise ProjectBackupError('선택한 SQLite에 현재 작품이 없습니다.')
        identity = _source_identity(path)
        require_current_sqlite(preview)
    except ProjectBackupError:
        raise
    except (ValueError, OSError, sqlite3.Error):
        raise ProjectBackupError('원본 SQLite의 읽기 전용 백업 계획을 만들지 못했습니다.') from None
    return ProjectBackupPlan(path, project_id, identity, len(preview.projects))


def create_project_backup(plan: ProjectBackupPlan, output_directory: str | Path,
                          *, explicit_author_backup: bool) -> ProjectBackupReceipt:
    if explicit_author_backup is not True or type(plan) is not ProjectBackupPlan:
        raise ProjectBackupError('현재 작품의 백업 생성을 직접 승인해야 합니다.')
    directory = Path(output_directory)
    if (not directory.is_absolute() or directory.is_symlink() or
            not directory.is_dir() or directory.resolve() == plan.source.parent.resolve()):
        raise ProjectBackupError('원본과 다른 기존 로컬 백업 폴더를 직접 선택하세요.')
    if _source_identity(plan.source) != plan.source_identity:
        raise ProjectBackupError('원본 SQLite 또는 WAL 상태가 변경되어 백업 승인이 무효화됐습니다.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    token = secrets.token_hex(6)
    backup = directory / f'anf-private-{stamp}-{token}.sqlite'
    manifest = directory / f'anf-private-{stamp}-{token}.json'
    try:
        fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        # No write connection is opened to the author's original database.
        with closing(sqlite3.connect(plan.source.as_uri() + '?mode=ro', uri=True,
                                     timeout=10)) as source_db:
            source_db.execute('PRAGMA query_only=ON')
            with closing(sqlite3.connect(backup, timeout=10)) as backup_db:
                source_db.backup(backup_db, pages=100, sleep=0.05)
                backup_db.commit()
        copied = preview_existing_sqlite(backup)
        if plan.project_id not in {row[0] for row in copied.projects}:
            raise ProjectBackupError('새 백업에서 작품 식별자를 확인하지 못했습니다.')
        digest = _hash_file(backup)
        current = _source_identity(plan.source) == plan.source_identity
        data = {
            'schema': 'anf-private-sqlite-backup-v1',
            'created_utc': stamp, 'backup_filename': backup.name,
            'backup_sha256': digest,
            'project_id_sha256': sha256(plan.project_id.encode('utf-8')).hexdigest(),
            'source_unchanged_during_copy': current,
            'status': 'PRIVATE_COPY_ONLY_NOT_RESTORED_NOT_VERIFIED',
            'publication_approved': False,
        }
        fd = os.open(manifest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            json.dump(data, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write('\n')
        return ProjectBackupReceipt(backup, manifest, plan.project_id, digest,
                                    current,
                                    'PRIVATE_SNAPSHOT_SOURCE_CURRENT' if current
                                    else 'PRIVATE_SNAPSHOT_SOURCE_CHANGED')
    except ProjectBackupError:
        raise
    except (OSError, sqlite3.Error, ValueError, TypeError):
        # A newly created file may remain if the process failed. Never delete
        # or overwrite any file on behalf of the author, including this copy.
        raise ProjectBackupError('로컬 백업 생성이 완료되지 않았습니다. 출력 폴더를 확인하세요.') from None


def preview_project_backup(backup_file: str | Path, manifest_file: str | Path,
                           project_id: str) -> ProjectBackupPreview:
    backup = Path(backup_file)
    manifest = Path(manifest_file)
    if (not backup.is_absolute() or backup.is_symlink() or
            not manifest.is_absolute() or manifest.is_symlink() or
            not backup.is_file() or not manifest.is_file() or
            manifest.stat().st_size > 16 * 1024):
        raise ProjectBackupError('기존 로컬 백업 파일과 기록 파일을 직접 선택해야 합니다.')
    try:
        record = json.loads(manifest.read_text(encoding='utf-8'))
        if (record.get('schema') != 'anf-private-sqlite-backup-v1'
                or record.get('backup_filename') != backup.name
                or record.get('project_id_sha256') !=
                sha256(project_id.encode('utf-8')).hexdigest()):
            raise ProjectBackupError('백업 기록의 작품 또는 파일이 일치하지 않습니다.')
        actual = _hash_file(backup)
        if actual != record.get('backup_sha256'):
            raise ProjectBackupError('백업 파일 SHA256이 기록과 일치하지 않습니다.')
        read_only = preview_existing_sqlite(backup)
        present = project_id in {row[0] for row in read_only.projects}
        if not present:
            raise ProjectBackupError('백업에 현재 작품이 없습니다.')
    except ProjectBackupError:
        raise
    except (OSError, ValueError, TypeError, KeyError):
        raise ProjectBackupError('백업 기록을 읽기 전용으로 확인하지 못했습니다.') from None
    return ProjectBackupPreview(backup, len(read_only.projects), True, present)
