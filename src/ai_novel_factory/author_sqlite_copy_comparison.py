"""작가가 선택한 기존 SQLite와 별도 복원 사본의 읽기 전용 내용 대조.

기존 `bible_` 테이블의 실제 행 전체를 스트리밍 지문으로 대조한다.
데이터베이스 무결성 인증, Windows 재열기 실사용 검증, 출판 승인과 무관하다.
원본·사본·WAL·참고작·원고·모델을 수정하거나 외부 전송하지 않는다.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
import json
import sqlite3

from .sqlite_reopen_preview import preview_existing_sqlite


class AuthorCopyComparisonError(ValueError):
    """개인 경로와 원고를 출력하지 않는 로컬 조회 오류."""


def _file_state(path: Path) -> tuple[int, int, int] | None:
    if path.is_symlink():
        raise AuthorCopyComparisonError('링크 파일은 사용할 수 없습니다.')
    try:
        state = path.stat()
    except FileNotFoundError:
        return None
    if not path.is_file():
        raise AuthorCopyComparisonError('기존 로컬 파일을 직접 선택하세요.')
    return state.st_size, state.st_mtime_ns, state.st_ino


def _sqlite_state(path: Path) -> tuple:
    return (_file_state(path), _file_state(Path(str(path) + '-wal')),
            _file_state(Path(str(path) + '-shm')))


def _digest_file(path: Path) -> str:
    digest = sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _hash_field(digest, value) -> None:
    if value is None:
        prefix, content = b'N', b''
    elif isinstance(value, bytes):
        prefix, content = b'B', value
    elif isinstance(value, str):
        prefix, content = b'T', value.encode('utf-8')
    elif isinstance(value, int):
        prefix, content = b'I', str(value).encode('ascii')
    elif isinstance(value, float):
        prefix, content = b'F', repr(value).encode('ascii')
    else:
        raise AuthorCopyComparisonError('SQLite 값 형식을 읽을 수 없습니다.')
    digest.update(prefix)
    digest.update(len(content).to_bytes(8, 'big'))
    digest.update(content)


def _table_fingerprints(path: Path, project_id: str) -> tuple[tuple[str, int, str], ...]:
    """로컬 SQLite의 bible_ 테이블을 읽기 전용으로 전체 순회한다."""
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=8)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA busy_timeout=8000')
        project = db.execute(
            'SELECT 1 FROM bible_projects WHERE project_id=?', (project_id,)).fetchone()
        if project is None:
            raise AuthorCopyComparisonError('선택한 작품이 두 SQLite 중 하나에 없습니다.')
        tables = db.execute('''SELECT name, sql FROM sqlite_master
            WHERE type='table' AND substr(name,1,6)='bible_' ORDER BY name''').fetchall()
        if not tables or len(tables) > 100:
            raise AuthorCopyComparisonError('기존 작품 테이블 목록을 확인하지 못했습니다.')
        results = []
        for name, ddl in tables:
            if type(name) is not str or type(ddl) is not str:
                raise AuthorCopyComparisonError('SQLite 테이블 형식이 올바르지 않습니다.')
            quoted = _identifier(name)
            columns = db.execute('PRAGMA table_info(' + quoted + ')').fetchall()
            primary = [column for column in sorted(columns, key=lambda x: x[5]) if column[5]]
            order = ', '.join(_identifier(col[1]) for col in primary) if primary else 'rowid'
            digest = sha256()
            _hash_field(digest, ddl)
            count = 0
            for row in db.execute('SELECT * FROM ' + quoted + ' ORDER BY ' + order):
                digest.update(b'R')
                digest.update(len(row).to_bytes(4, 'big'))
                for value in row:
                    _hash_field(digest, value)
                count += 1
                if count > 2_000_000:
                    raise AuthorCopyComparisonError('작품 테이블 조회 한도를 초과했습니다.')
            results.append((name, count, digest.hexdigest()))
        return tuple(results)


@dataclass(frozen=True)
class AuthorCopyComparison:
    source: Path = field(repr=False)
    copy: Path = field(repr=False)
    receipt: Path = field(repr=False)
    project_id: str = field(repr=False)
    source_identity: tuple = field(repr=False)
    copy_identity: tuple = field(repr=False)
    receipt_identity: tuple = field(repr=False)
    copy_sha256: str = field(repr=False)
    receipt_sha256: str = field(repr=False)
    source_tables: int = 0
    copy_tables: int = 0
    matched_tables: int = 0
    differing_tables: tuple[str, ...] = ()
    source_episode_rows: int = 0
    copy_episode_rows: int = 0
    fingerprint: str = field(default='', repr=False)
    status: str = 'READ_ONLY_CONTENT_COMPARISON_NOT_VERIFIED'
    publication_approved: bool = False


def compare_author_sqlite_copy(source_file: str | Path, copy_file: str | Path,
                               receipt_file: str | Path, project_id: str) -> AuthorCopyComparison:
    """원본/사본의 모든 bible_ 행 대조. 실제 복원·재열기는 별도 단계."""
    if type(project_id) is not str or not project_id or len(project_id) > 200:
        raise AuthorCopyComparisonError('현재 작품을 먼저 직접 선택하세요.')
    source, copy, receipt = map(Path, (source_file, copy_file, receipt_file))
    if (any(not path.is_absolute() or path.is_symlink() or not path.is_file()
            for path in (source, copy, receipt))
            or len({path.resolve() for path in (source, copy, receipt)}) != 3):
        raise AuthorCopyComparisonError('원본과 다른 기존 SQLite 사본·기록 파일을 선택하세요.')
    try:
        before_source = _sqlite_state(source)
        before_copy = _sqlite_state(copy)
        before_receipt = _file_state(receipt)
        if (before_copy[0] is None or before_source[0] is None
                or before_receipt is None or before_receipt[0] > 16 * 1024):
            raise AuthorCopyComparisonError('기존 SQLite·사본 기록을 확인하지 못했습니다.')
        receipt_sha = _digest_file(receipt)
        record = json.loads(receipt.read_text(encoding='utf-8'))
        copy_sha = _digest_file(copy)
        if (type(record) is not dict or record.get('schema') != 'anf-private-restore-copy-v1'
                or record.get('copy_filename') != copy.name
                or record.get('copy_sha256') != copy_sha
                or record.get('project_id_sha256') != sha256(project_id.encode('utf-8')).hexdigest()
                or record.get('publication_approved') is not False
                or record.get('auto_restore') is not False):
            raise AuthorCopyComparisonError('새 사본 SHA 기록 또는 작품이 일치하지 않습니다.')
        for path in (source, copy):
            preview = preview_existing_sqlite(path)
            if project_id not in {pid for pid, _ in preview.projects}:
                raise AuthorCopyComparisonError('선택한 작품이 SQLite에 없습니다.')
        original = _table_fingerprints(source, project_id)
        copied = _table_fingerprints(copy, project_id)
        if (_sqlite_state(source) != before_source or _sqlite_state(copy) != before_copy
                or _file_state(receipt) != before_receipt
                or _digest_file(copy) != copy_sha or _digest_file(receipt) != receipt_sha):
            raise AuthorCopyComparisonError('조회 중 원본·사본·기록이 변경됐습니다.')
        left, right = {x[0]: x for x in original}, {x[0]: x for x in copied}
        differences = tuple(name for name in sorted(left.keys() | right.keys())
                            if left.get(name) != right.get(name))
        fingerprint = sha256(json.dumps((project_id, before_source, before_copy,
            before_receipt, copy_sha, receipt_sha, original, copied),
            ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
        return AuthorCopyComparison(source, copy, receipt, project_id, before_source,
            before_copy, before_receipt, copy_sha, receipt_sha, len(original),
            len(copied), len(set(left) & set(right)) - len(set(differences) & set(left) & set(right)),
            differences, left.get('bible_episodes', ('', 0, ''))[1],
            right.get('bible_episodes', ('', 0, ''))[1], fingerprint)
    except AuthorCopyComparisonError:
        raise
    except (OSError, ValueError, TypeError, sqlite3.Error, UnicodeError, OverflowError):
        raise AuthorCopyComparisonError('기존 SQLite와 사본을 읽기 전용으로 대조하지 못했습니다.') from None


def require_current_author_copy_comparison(snapshot: AuthorCopyComparison) -> None:
    """인계 직전 다시 전체 내용을 읽어 변경된 선택·기록의 재사용을 차단."""
    if type(snapshot) is not AuthorCopyComparison:
        raise AuthorCopyComparisonError('원본과 사본을 다시 직접 조회하세요.')
    latest = compare_author_sqlite_copy(
        snapshot.source, snapshot.copy, snapshot.receipt, snapshot.project_id)
    if latest.fingerprint != snapshot.fingerprint:
        raise AuthorCopyComparisonError('SQLite 원본·사본·기록이 변경됐습니다. 다시 조회하세요.')
