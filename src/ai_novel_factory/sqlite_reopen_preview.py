"""Read-only preview of a user-selected existing SQLite project file.

Never opens a writable SQLite connection, creates a database, or changes
project selection without the author's separate explicit Open action.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import closing
from pathlib import Path
import sqlite3


class SqliteReopenError(ValueError):
    """No private database paths or manuscript text in error messages."""


@dataclass(frozen=True)
class SqliteReopenPreview:
    path: Path = field(repr=False)
    identity: tuple[int, int] = field(repr=False)
    projects: tuple[tuple[str, str], ...] = field(repr=False)
    status: str = 'READ_ONLY_PREVIEW_NOT_OPENED'


def preview_existing_sqlite(path_value: str | Path) -> SqliteReopenPreview:
    path = Path(path_value)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise SqliteReopenError('기존 로컬 SQLite 파일을 직접 선택해야 합니다.')
    try:
        before = path.stat()
        if before.st_size < 100 or before.st_size > 10 * 1024 ** 3:
            raise SqliteReopenError('SQLite 파일 크기를 확인할 수 없습니다.')
        with path.open('rb') as handle:
            if handle.read(16) != b'SQLite format 3\x00':
                raise SqliteReopenError('SQLite 형식이 아닙니다.')
        # as_uri yields a file URI on both Windows and POSIX. mode=ro is
        # essential: no schema initialization or user DB mutation here.
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=3)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA busy_timeout=3000')
            rows = db.execute('''SELECT project_id, title FROM bible_projects
                                 ORDER BY rowid LIMIT 1001''').fetchall()
        after = path.stat()
    except SqliteReopenError:
        raise
    except (sqlite3.Error, OSError, ValueError):
        raise SqliteReopenError('기존 작품 SQLite를 읽기 전용으로 열 수 없습니다.') from None
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise SqliteReopenError('미리보기 도중 SQLite가 변경되었습니다.')
    if not rows or len(rows) > 1000:
        raise SqliteReopenError('작품 정보가 없거나 조회 한도를 초과했습니다.')
    projects = tuple((str(pid), str(title)[:80]) for pid, title in rows)
    return SqliteReopenPreview(path, (after.st_size, after.st_mtime_ns), projects)


def require_current_sqlite(preview: SqliteReopenPreview) -> None:
    if type(preview) is not SqliteReopenPreview:
        raise SqliteReopenError('작품 SQLite를 다시 선택하세요.')
    try:
        state = preview.path.stat()
        if (state.st_size, state.st_mtime_ns) != preview.identity:
            raise SqliteReopenError('선택한 작품 SQLite가 변경되었습니다.')
    except OSError:
        raise SqliteReopenError('작품 SQLite 파일을 확인할 수 없습니다.') from None
