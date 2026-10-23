"""Explicit private restore-as-new-copy from an existing ANF SQLite backup.

This feature NEVER overwrites or opens an author's current project for writing.
A verified backup becomes a NEW SQLite file in an author-selected existing
local directory only after an independent, one-shot author approval.
A copy is not a Windows compatibility test or a publication authorization.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import os
import secrets

from .project_backup_snapshot import preview_project_backup
from .sqlite_reopen_preview import preview_existing_sqlite


class ProjectRestoreError(ValueError):
    """Errors omit private paths, manuscript text and model configuration."""


def _digest(path: Path) -> str:
    result = sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def _file_identity(path: Path) -> tuple[int, int, int, str]:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ProjectRestoreError('기존 로컬 백업 파일을 직접 선택해야 합니다.')
    st = path.stat()
    if st.st_size == 0:
        raise ProjectRestoreError('빈 백업은 복사할 수 없습니다.')
    return st.st_size, st.st_mtime_ns, st.st_ino, _digest(path)


@dataclass(frozen=True)
class RestoreCopyPlan:
    backup: Path = field(repr=False)
    manifest: Path = field(repr=False)
    project_id: str = field(repr=False)
    backup_identity: tuple = field(repr=False)
    manifest_identity: tuple = field(repr=False)
    project_count: int
    status: str = 'READ_ONLY_RESTORE_AS_NEW_PLAN'
    publication_approved: bool = False


@dataclass(frozen=True)
class RestoreCopyReceipt:
    destination: Path = field(repr=False)
    receipt_path: Path = field(repr=False)
    copy_sha256: str = field(repr=False)
    project_count: int
    status: str = 'PRIVATE_COPY_NOT_OPENED_NOT_VERIFIED'
    publication_approved: bool = False


def plan_restore_copy(backup_file: str | Path, manifest_file: str | Path,
                      project_id: str) -> RestoreCopyPlan:
    if type(project_id) is not str or not project_id or len(project_id) > 200:
        raise ProjectRestoreError('백업에 포함된 작품을 선택해야 합니다.')
    backup, manifest = Path(backup_file), Path(manifest_file)
    try:
        before = _file_identity(backup)
        record_identity = _file_identity(manifest)
        if manifest.stat().st_size > 16 * 1024:
            raise ProjectRestoreError('백업 기록 파일 크기가 올바르지 않습니다.')
        record = json.loads(manifest.read_text(encoding='utf-8'))
        if record.get('source_unchanged_during_copy') is not True:
            raise ProjectRestoreError('원본 변경 중 생성된 백업은 새 사본으로 복원할 수 없습니다.')
        result = preview_project_backup(backup, manifest, project_id)
        if not result.sha256_matches_manifest or not result.contains_expected_project:
            raise ProjectRestoreError('백업 무결성 또는 작품 식별자를 확인하지 못했습니다.')
        if before != _file_identity(backup) or record_identity != _file_identity(manifest):
            raise ProjectRestoreError('백업 또는 기록이 조회 중 변경되었습니다.')
        return RestoreCopyPlan(backup, manifest, project_id, before,
                               record_identity, result.project_count)
    except ProjectRestoreError:
        raise
    except (OSError, ValueError, TypeError, KeyError):
        raise ProjectRestoreError('백업 파일과 기록을 읽기 전용으로 확인하지 못했습니다.') from None


def create_restore_copy(plan: RestoreCopyPlan, destination_directory: str | Path,
                        *, explicit_author_copy: bool) -> RestoreCopyReceipt:
    if type(plan) is not RestoreCopyPlan or explicit_author_copy is not True:
        raise ProjectRestoreError('현재 백업을 새 파일로 복사하는 이번 1회를 직접 승인하세요.')
    directory = Path(destination_directory)
    if (not directory.is_absolute() or directory.is_symlink() or
            not directory.is_dir() or directory.resolve() == plan.backup.parent.resolve()):
        raise ProjectRestoreError('백업 폴더와 다른 기존 로컬 폴더를 직접 선택하세요.')
    if (_file_identity(plan.backup) != plan.backup_identity or
            _file_identity(plan.manifest) != plan.manifest_identity):
        raise ProjectRestoreError('선택 백업이 변경되어 이전 승인이 무효화됐습니다.')
    # Revalidate the original receipt immediately before creating anything.
    preview_project_backup(plan.backup, plan.manifest, plan.project_id)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    token = secrets.token_hex(6)
    target = directory / f'anf-restored-copy-{stamp}-{token}.sqlite'
    receipt = directory / f'anf-restored-copy-{stamp}-{token}.json'
    try:
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as output, plan.backup.open('rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        if _file_identity(plan.backup) != plan.backup_identity:
            raise ProjectRestoreError('복사 중 백업이 변경되었습니다. 새 사본을 사용하지 마세요.')
        digest = _digest(target)
        if digest != plan.backup_identity[3]:
            raise ProjectRestoreError('새 사본의 SHA256이 원본 백업과 다릅니다.')
        preview = preview_existing_sqlite(target)
        if plan.project_id not in {row[0] for row in preview.projects}:
            raise ProjectRestoreError('새 사본에 선택 작품이 없습니다.')
        data = {
            'schema': 'anf-private-restore-copy-v1',
            'created_utc': stamp,
            'copy_filename': target.name,
            'copy_sha256': digest,
            'project_id_sha256': sha256(plan.project_id.encode('utf-8')).hexdigest(),
            'status': 'PRIVATE_COPY_NOT_OPENED_NOT_VERIFIED',
            'publication_approved': False,
            'auto_restore': False,
        }
        fd = os.open(receipt, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as output:
            json.dump(data, output, ensure_ascii=False, sort_keys=True, indent=2)
            output.write('\n')
        return RestoreCopyReceipt(target, receipt, digest, len(preview.projects))
    except ProjectRestoreError:
        raise
    except (OSError, ValueError, TypeError):
        # Never delete or overwrite an author's file; an incomplete new file
        # may remain and must not be treated as a usable restore.
        raise ProjectRestoreError('새 로컬 SQLite 사본 생성이 완료되지 않았습니다.') from None
