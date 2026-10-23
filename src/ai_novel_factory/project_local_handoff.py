"""작가가 직접 누른 백업→새 사본→기존 재열기 인계의 읽기 전용 계약.

이 계약은 승인이나 모델 실행을 전달하지 않는다. 원고·원본 DB를 수정하지
않고, 선택한 로컬 파일의 무결성과 현재 작품/미저장 상태만 재확인한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
import json

from .project_backup_snapshot import ProjectBackupReceipt, preview_project_backup
from .project_restore_copy import RestoreCopyReceipt
from .sqlite_reopen_preview import preview_existing_sqlite, require_current_sqlite


class LocalHandoffError(ValueError):
    """원고·사용자 경로를 메시지에 포함하지 않는다."""


def _identity(path: Path) -> tuple[int, int, int, str]:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise LocalHandoffError('기존 로컬 파일을 다시 선택하세요.')
    stat = path.stat()
    if not 1 <= stat.st_size <= 10 * 1024 ** 3:
        raise LocalHandoffError('로컬 파일 크기를 확인할 수 없습니다.')
    digest = sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return stat.st_size, stat.st_mtime_ns, stat.st_ino, digest.hexdigest()


def require_idle_authoring(authoring, project_id: str) -> None:
    session = authoring.session
    if (session.store is None or session.path is None or session.project_id is None
            or str(session.project_id) != project_id):
        raise LocalHandoffError('현재 작품이 변경되었습니다. 다시 조회하세요.')
    if authoring.is_generating() or authoring.auto_panel.is_running():
        raise LocalHandoffError('진행 중인 집필·배치가 끝나야 이동할 수 있습니다.')
    if session.pending_draft is not None:
        raise LocalHandoffError('미저장 AI 초고를 먼저 직접 정리하세요.')
    if session.episode_number is not None:
        try:
            saved = session.episode()
            if any(authoring._text(key) != value for key, value in (
                    ('plot', saved.plot), ('draft', saved.draft),
                    ('final_text', saved.final_text))):
                raise LocalHandoffError('미저장 원고를 먼저 직접 정리하세요.')
            if session.scene_id is not None and authoring._text('scene') != session.scene().text:
                raise LocalHandoffError('미저장 장면을 먼저 직접 정리하세요.')
        except (ValueError, LookupError, OSError) as exc:
            if isinstance(exc, LocalHandoffError):
                raise
            raise LocalHandoffError('현재 원고 상태를 확인하지 못했습니다.') from None


@dataclass(frozen=True)
class BackupHandoff:
    backup: Path = field(repr=False)
    manifest: Path = field(repr=False)
    project_id: str = field(repr=False)
    identity: tuple = field(repr=False)


def prepare_backup_handoff(receipt: ProjectBackupReceipt, project_id: str) -> BackupHandoff:
    if (type(receipt) is not ProjectBackupReceipt or receipt.project_id != project_id
            or receipt.source_current_after_backup is not True):
        raise LocalHandoffError('현재 작품에서 정상 생성한 백업만 인계할 수 있습니다.')
    preview = preview_project_backup(receipt.backup_file, receipt.manifest_file, project_id)
    if not preview.sha256_matches_manifest or not preview.contains_expected_project:
        raise LocalHandoffError('백업 기록과 작품이 일치하지 않습니다.')
    identity = (_identity(receipt.backup_file), _identity(receipt.manifest_file))
    if identity[0][3] != receipt.backup_sha256:
        raise LocalHandoffError('백업 SHA256이 생성 기록과 다릅니다.')
    return BackupHandoff(receipt.backup_file, receipt.manifest_file, project_id, identity)


def require_backup_handoff(handoff: BackupHandoff) -> None:
    if (type(handoff) is not BackupHandoff or
            (_identity(handoff.backup), _identity(handoff.manifest)) != handoff.identity):
        raise LocalHandoffError('백업 파일이 변경됐습니다. 다시 인계하세요.')
    preview_project_backup(handoff.backup, handoff.manifest, handoff.project_id)


@dataclass(frozen=True)
class NewCopyHandoff:
    copy: Path = field(repr=False)
    receipt: Path = field(repr=False)
    project_id: str = field(repr=False)
    identity: tuple = field(repr=False)


def prepare_new_copy_handoff(receipt: RestoreCopyReceipt, project_id: str) -> NewCopyHandoff:
    if type(receipt) is not RestoreCopyReceipt:
        raise LocalHandoffError('이 화면에서 만든 새 SQLite 사본만 인계하세요.')
    copy, record_path = receipt.destination, receipt.receipt_path
    if record_path.stat().st_size > 16 * 1024:
        raise LocalHandoffError('사본 기록의 크기가 올바르지 않습니다.')
    identity = (_identity(copy), _identity(record_path))
    record = json.loads(record_path.read_text(encoding='utf-8'))
    if (record.get('schema') != 'anf-private-restore-copy-v1'
            or record.get('copy_filename') != copy.name
            or record.get('copy_sha256') != receipt.copy_sha256
            or identity[0][3] != receipt.copy_sha256
            or record.get('project_id_sha256') != sha256(project_id.encode('utf-8')).hexdigest()
            or record.get('publication_approved') is not False
            or record.get('auto_restore') is not False):
        raise LocalHandoffError('새 사본 기록과 현재 작품이 일치하지 않습니다.')
    preview = preview_existing_sqlite(copy)
    require_current_sqlite(preview)
    if len(preview.projects) != 1 or preview.projects[0][0] != project_id:
        raise LocalHandoffError('여러 작품이 포함된 사본은 기존 재열기에서 직접 선택하세요.')
    if (_identity(copy), _identity(record_path)) != identity:
        raise LocalHandoffError('새 사본이 조회 중 변경되었습니다.')
    return NewCopyHandoff(copy, record_path, project_id, identity)


def require_new_copy_handoff(handoff: NewCopyHandoff) -> None:
    if (type(handoff) is not NewCopyHandoff or
            (_identity(handoff.copy), _identity(handoff.receipt)) != handoff.identity):
        raise LocalHandoffError('새 사본이 변경되었습니다. 다시 선택하세요.')
    preview = preview_existing_sqlite(handoff.copy)
    require_current_sqlite(preview)
    if len(preview.projects) != 1 or preview.projects[0][0] != handoff.project_id:
        raise LocalHandoffError('현재 작품이 아닌 SQLite 사본입니다.')
