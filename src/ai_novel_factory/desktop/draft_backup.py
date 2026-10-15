"""Explicit, private TXT safety copy of a live unsaved GUI manuscript.

Only user-chosen new local files; no SQLite edits, publishing, or overwrite.
"""
from __future__ import annotations
import os
from pathlib import Path


class DraftBackupError(ValueError):
    """Unsafe backup location or empty draft."""


def write_draft_copy(destination: str | Path, prose: str) -> Path:
    if type(prose) is not str or not prose.strip():
        raise DraftBackupError('별도로 보관할 원고가 없습니다.')
    if type(destination) not in (str, Path):
        raise DraftBackupError('로컬 TXT 저장 경로가 올바르지 않습니다.')
    dest = Path(destination)
    if (not dest.is_absolute() or dest.suffix.lower() != '.txt'
            or not dest.parent.is_dir() or dest.parent.is_symlink()
            or dest.is_symlink() or dest.exists()):
        raise DraftBackupError('기존 파일이 없는 로컬 TXT 경로를 선택하세요.')
    data = prose.encode('utf-8')
    try:
        fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise DraftBackupError('기존 TXT 파일은 덮어쓸 수 없습니다.') from None
    identity = os.fstat(fd)
    try:
        try:
            with os.fdopen(fd, 'wb') as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
        except BaseException:
            try:
                st = dest.lstat()
                if (st.st_dev, st.st_ino) == (identity.st_dev, identity.st_ino):
                    dest.unlink()
            except FileNotFoundError:
                pass
            raise
    finally:
        # os.fdopen() closes the descriptor normally. Close is idempotent
        # here only when its constructor failed.
        try:
            os.close(fd)
        except OSError:
            pass
    return dest
