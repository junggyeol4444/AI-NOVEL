"""Author-triggered, strictly read-only local SQLite chapter search.

Work entirely against the existing project/database; no EpisodeStore
initialization (which could create tables), FTS trigger/schema changes,
temporary persistent files, reference work reads, API calls or logs.
Results/short extracts only live in GUI memory; never mark QC PASS.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from urllib.parse import quote
import sqlite3
import re

_FIELDS = frozenset({'final_text', 'draft', 'plot', 'summary'})
_PROJECT = re.compile(r'^[0-9a-f]{32}$')


class ManuscriptSearchError(ValueError):
    """Errors deliberately exclude prose and private local paths."""


@dataclass(frozen=True)
class ManuscriptHit:
    episode: int
    revision: int
    field: str
    column_start: int
    excerpt: str = field(repr=False)
    source_sha256: str = field(repr=False)


@dataclass(frozen=True)
class ManuscriptSearchReport:
    query: str = field(repr=False)
    field_name: str = 'final_text'
    through_episode: int = 0
    checked_episodes: int = 0
    total_occurrences: int = 0
    truncated: bool = False
    hits: tuple[ManuscriptHit, ...] = ()
    status: str = 'OFFLINE_READ_ONLY_NOT_QC'


def _path(value: str | Path) -> Path:
    result = Path(value)
    if (not result.is_absolute() or result.is_symlink() or
            not result.is_file() or result.suffix.lower() not in ('.db', '.sqlite', '.sqlite3')):
        raise ManuscriptSearchError('기존 로컬 SQLite 파일을 직접 선택해야 합니다.')
    return result


def _term(query: str) -> str:
    if (type(query) is not str or not 2 <= len(query) <= 100
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in query)
            or not query.strip()):
        raise ManuscriptSearchError('검색어는 2~100자의 일반 텍스트여야 합니다.')
    return query.strip()


def search_saved_manuscript(database_path: str | Path, project_id: str,
                            query: str, *, field_name: str = 'final_text',
                            through_episode: int = 1000,
                            max_results: int = 200) -> ManuscriptSearchReport:
    """Scan one explicitly chosen manuscript column, no implicit synonyms.

    Uses SQLite URI mode=ro, query_only, a project-scoped prepared SELECT
    and a consistent read transaction. Never opens a writable connection.
    The first 200 occurrences are displayed; the full occurrence count is
    still collected without retaining all matching prose in memory.
    """
    path = _path(database_path)
    term = _term(query)
    if (type(project_id) is not str or not _PROJECT.fullmatch(project_id)
            or field_name not in _FIELDS
            or type(through_episode) is not int or not 1 <= through_episode <= 1000
            or type(max_results) is not int or not 1 <= max_results <= 200):
        raise ManuscriptSearchError('작품·원고 종류·검색 회차 범위가 올바르지 않습니다.')
    uri = 'file:' + quote(str(path), safe='/') + '?mode=ro'
    matches: list[ManuscriptHit] = []
    total = checked = 0
    try:
        with sqlite3.connect(uri, uri=True, timeout=5) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            if db.execute('SELECT 1 FROM bible_projects WHERE project_id=?',
                          (project_id,)).fetchone() is None:
                raise ManuscriptSearchError('선택한 SQLite에 해당 작품이 없습니다.')
            # field_name is a fixed literal allowlist, not user SQL.
            cursor = db.execute(
                f'SELECT episode,revision,{field_name} FROM bible_episodes '
                'WHERE project_id=? AND episode BETWEEN 1 AND ? ORDER BY episode',
                (project_id, through_episode))
            folded = term.casefold()
            for number, revision, prose in cursor:
                checked += 1
                if not isinstance(prose, str):
                    raise ManuscriptSearchError('저장된 원고 형식이 올바르지 않습니다.')
                # Casefold offsets can shift under some Unicode case mappings.
                # Search original text by case-insensitive regex instead so
                # the excerpt indexes always refer to the source itself.
                expression = re.compile(re.escape(term), re.IGNORECASE)
                for found in expression.finditer(prose):
                    total += 1
                    if len(matches) < max_results:
                        a, b = found.span()
                        left, right = max(0, a-65), min(len(prose), b+65)
                        excerpt = prose[left:right].replace('\r', ' ')
                        excerpt = excerpt.replace('\n', ' ')
                        matches.append(ManuscriptHit(
                            number, revision, field_name, a, excerpt,
                            sha256(prose.encode('utf-8', 'surrogatepass')).hexdigest()))
            db.execute('ROLLBACK')
    except sqlite3.Error:
        raise ManuscriptSearchError('읽기 전용 SQLite 검색을 완료하지 못했습니다.') from None
    return ManuscriptSearchReport(term, field_name, through_episode, checked,
                                  total, total > len(matches), tuple(matches))


def revalidate_manuscript_hit(database_path: str | Path, project_id: str,
                              hit: ManuscriptHit) -> bool:
    """Reject navigation to changed content, without modifying any state."""
    if type(hit) is not ManuscriptHit or hit.field not in _FIELDS:
        return False
    path = _path(database_path)
    uri = 'file:' + quote(str(path), safe='/') + '?mode=ro'
    try:
        with sqlite3.connect(uri, uri=True, timeout=5) as db:
            db.execute('PRAGMA query_only=ON')
            row = db.execute(
                f'SELECT revision,{hit.field} FROM bible_episodes '
                'WHERE project_id=? AND episode=?',
                (project_id, hit.episode)).fetchone()
            return bool(row and row[0] == hit.revision and
                        sha256(row[1].encode('utf-8', 'surrogatepass')).hexdigest()
                        == hit.source_sha256)
    except (sqlite3.Error, ValueError, UnicodeError):
        return False


@dataclass(frozen=True)
class ManuscriptExactMatch:
    """저장된 회차의 정확한 검색 일치 위치와 원문. 화면 메모리 전용."""

    episode: int
    revision: int
    field_name: str
    match_start: int
    match_end: int
    text: str = field(repr=False)
    source_sha256: str = field(repr=False)
    status: str = 'LOCAL_SAVED_MANUSCRIPT_READ_ONLY_NOT_REVIEWED'


def read_saved_manuscript_exact_match(
    database_path: str | Path, project_id: str,
    hit: ManuscriptHit, query: str,
) -> ManuscriptExactMatch:
    """작가가 직접 고른 검색 결과의 저장 원문을 읽기 전용으로 재조회.

    검색 당시 회차 revision·원문 SHA256·정확한 일치 위치를 모두 재확인한다.
    원문은 파일·로그·모델 문맥에 기록하지 않으며, QC/출판 승인이 아니다.
    """
    if (type(hit) is not ManuscriptHit or hit.field not in _FIELDS
            or type(hit.episode) is not int or not 1 <= hit.episode <= 1000
            or type(hit.revision) is not int
            or type(hit.column_start) is not int or hit.column_start < 0
            or type(project_id) is not str or not _PROJECT.fullmatch(project_id)):
        raise ManuscriptSearchError('저장 원고 검색 결과를 다시 직접 선택하세요.')
    term = _term(query)
    path = _path(database_path)
    uri = 'file:' + quote(str(path), safe='/') + '?mode=ro'
    try:
        with sqlite3.connect(uri, uri=True, timeout=5) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            # SQL 열 이름은 _FIELDS 고정 허용 목록만 사용한다.
            row = db.execute(
                f'SELECT revision,{hit.field} FROM bible_episodes '
                'WHERE project_id=? AND episode=?',
                (project_id, hit.episode)).fetchone()
            if row is None or row[0] != hit.revision or type(row[1]) is not str:
                raise ManuscriptSearchError('저장 원고가 변경됐습니다. 다시 검색하세요.')
            prose = row[1]
            digest = sha256(prose.encode('utf-8', 'surrogatepass')).hexdigest()
            if digest != hit.source_sha256 or hit.column_start >= len(prose):
                raise ManuscriptSearchError('검색 당시 원고 지문이 변경됐습니다.')
            found = re.compile(re.escape(term), re.IGNORECASE).match(
                prose, hit.column_start)
            if found is None or found.start() != hit.column_start:
                raise ManuscriptSearchError('검색된 본문 위치가 변경됐습니다.')
            result = ManuscriptExactMatch(
                hit.episode, hit.revision, hit.field, found.start(), found.end(),
                prose, digest)
            db.execute('ROLLBACK')
            return result
    except sqlite3.Error:
        raise ManuscriptSearchError(
            '읽기 전용 SQLite 원문 위치 조회를 완료하지 못했습니다.') from None
