"""기존 SQLite 원본과 별도 복원 사본의 1~1000화 실제 저장 항목 차이 조회.

원고 본문·검수 메모는 외부 전송하거나 결과 화면에 노출하지 않는다.
이 조회는 사본 복원 성공·문학 품질·QC PASS·출판 승인을 뜻하지 않는다.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, field
from hashlib import sha256
import json
import sqlite3

from .author_sqlite_copy_comparison import (
    AuthorCopyComparison, AuthorCopyComparisonError,
    require_current_author_copy_comparison, _hash_field,
)


class AuthorSqliteChapterDeltaError(ValueError):
    """원고와 개인 파일 경로를 노출하지 않는 읽기 전용 비교 오류."""


@dataclass(frozen=True)
class ChapterCopyDelta:
    episode: int
    source_revision: int | None
    copy_revision: int | None
    plot_changed: bool
    draft_changed: bool
    final_changed: bool
    summary_changed: bool
    scene_changed: bool
    check_changed: bool
    source_scene_count: int
    copy_scene_count: int
    source_check_count: int
    copy_check_count: int
    status: str = 'AUTHOR_COMPARISON_ONLY'
    publication_approved: bool = False


@dataclass(frozen=True)
class AuthorSqliteChapterDelta:
    comparison: AuthorCopyComparison = field(repr=False)
    through_episode: int = 0
    rows: tuple[ChapterCopyDelta, ...] = ()
    missing_source: int = 0
    missing_copy: int = 0
    changed_final: int = 0
    changed_scenes: int = 0
    changed_checks: int = 0
    fingerprint: str = field(default='', repr=False)
    status: str = 'READ_ONLY_EPISODE_DIFFERENCES_NOT_VERIFIED'
    publication_approved: bool = False


def _read_episode_fingerprints(path, project_id: str, through: int) -> dict[int, tuple]:
    """SQLite 읽기 전용 연결에서 본문 전체를 SHA로 비교하되 본문은 반환하지 않는다."""
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=8)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA busy_timeout=8000')
        records: dict[int, list] = {}
        for row in db.execute('''SELECT episode, revision, plot, draft, final_text, summary
            FROM bible_episodes WHERE project_id=? AND episode BETWEEN 1 AND ?
            ORDER BY episode''', (project_id, through)):
            number, revision, *texts = row
            if (type(number) is not int or not 1 <= number <= through
                    or type(revision) is not int or revision < 1
                    or any(type(value) is not str for value in texts)
                    or number in records):
                raise AuthorSqliteChapterDeltaError('저장된 회차 형식을 확인할 수 없습니다.')
            records[number] = [revision, *(sha256(value.encode('utf-8')).hexdigest()
                                         for value in texts), 0, '', 0, '']
        # 고정 SQL과 프로젝트 매개변수만 사용하며 데이터베이스 쓰기는 하지 않는다.
        groups = (
            ('bible_episode_scenes', 'scene_id, position, text, created_at, updated_at',
             'episode, position, scene_id', 5, 6),
            ('bible_episode_checks',
             'check_id, category, outcome, note, content_revision, created_at',
             'episode, created_at, check_id', 7, 8),
        )
        for table, columns, order, count_index, hash_index in groups:
            digests = {number: sha256() for number in records}
            sql = (f'SELECT episode, {columns} FROM {table} '
                   f'WHERE project_id=? AND episode BETWEEN 1 AND ? ORDER BY {order}')
            for row in db.execute(sql, (project_id, through)):
                number = row[0]
                if number not in records:
                    raise AuthorSqliteChapterDeltaError('저장된 장면·검수의 회차 연결을 확인하세요.')
                records[number][count_index] += 1
                if records[number][count_index] > (200 if count_index == 5 else 500):
                    raise AuthorSqliteChapterDeltaError('회차별 기록 개수 한도를 초과했습니다.')
                digest = digests[number]
                digest.update(b'R')
                for value in row[1:]:
                    _hash_field(digest, value)
            for number, digest in digests.items():
                records[number][hash_index] = digest.hexdigest()
        return {number: tuple(value) for number, value in records.items()}


def build_author_sqlite_chapter_delta(
    comparison: AuthorCopyComparison, *, through_episode: int,
) -> AuthorSqliteChapterDelta:
    """작가가 이미 승인 없이 대조한 원본·사본에서 회차별 실제 차이만 산출."""
    if (type(comparison) is not AuthorCopyComparison
            or type(through_episode) is not int
            or not 1 <= through_episode <= 1000):
        raise AuthorSqliteChapterDeltaError('현재 SQLite 사본과 1~1000화 범위를 선택하세요.')
    try:
        require_current_author_copy_comparison(comparison)
        source = _read_episode_fingerprints(
            comparison.source, comparison.project_id, through_episode)
        copied = _read_episode_fingerprints(
            comparison.copy, comparison.project_id, through_episode)
        require_current_author_copy_comparison(comparison)
        rows = []
        for number in range(1, through_episode + 1):
            left, right = source.get(number), copied.get(number)
            if left is None and right is None:
                continue
            rows.append(ChapterCopyDelta(
                number, left[0] if left else None, right[0] if right else None,
                *tuple((left[i] if left else None) != (right[i] if right else None)
                       for i in (1, 2, 3, 4, 6, 8)),
                left[5] if left else 0, right[5] if right else 0,
                left[7] if left else 0, right[7] if right else 0,
                'SOURCE_ONLY' if right is None else
                'COPY_ONLY' if left is None else
                'DIFFERENT' if left != right else 'SAME'))
        fingerprint = sha256(json.dumps((
            comparison.fingerprint, through_episode,
            tuple((number, source.get(number), copied.get(number))
                  for number in range(1, through_episode + 1))),
            ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
        return AuthorSqliteChapterDelta(
            comparison, through_episode, tuple(rows),
            sum(row.source_revision is None for row in rows),
            sum(row.copy_revision is None for row in rows),
            sum(row.final_changed for row in rows),
            sum(row.scene_changed for row in rows),
            sum(row.check_changed for row in rows), fingerprint)
    except AuthorSqliteChapterDeltaError:
        raise
    except (AuthorCopyComparisonError, OSError, ValueError, TypeError,
            sqlite3.Error, UnicodeError, OverflowError):
        raise AuthorSqliteChapterDeltaError(
            '원본·사본의 저장 회차를 읽기 전용으로 대조하지 못했습니다.') from None


def require_current_author_sqlite_chapter_delta(snapshot: AuthorSqliteChapterDelta) -> None:
    """편집기 이동 직전에 원본·사본·기록·회차 지문 변경 여부 재확인."""
    if type(snapshot) is not AuthorSqliteChapterDelta:
        raise AuthorSqliteChapterDeltaError('원본·사본의 회차별 차이를 다시 조회하세요.')
    latest = build_author_sqlite_chapter_delta(
        snapshot.comparison, through_episode=snapshot.through_episode)
    if latest.fingerprint != snapshot.fingerprint:
        raise AuthorSqliteChapterDeltaError('원본·사본·검수 기록이 변경됐습니다. 다시 조회하세요.')
