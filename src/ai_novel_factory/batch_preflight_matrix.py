"""Read-only existing-SQLite launch inventory, not a model test or QC pass.

This report does not create tables, open EpisodeStore (which may initialize
schema), run any executable, save a manuscript, or approve publication.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from urllib.parse import quote
import sqlite3

from .local_model_integrity import LocalModelIdentity, verify_local_model_identity
from .reference_intake_plan import plan_reference_intake


class BatchPreflightError(ValueError):
    """Errors intentionally omit paths and manuscript text."""


@dataclass(frozen=True)
class BatchPreflightChapter:
    episode: int
    revision: int | None
    status: str
    qc_records_current: int
    qc_records_stale: int
    model_generated: bool = False
    publication_approved: bool = False
    saved_source_sha256: str = field(default='', repr=False)
    qc_source_sha256: str = field(default='', repr=False)


@dataclass(frozen=True)
class BatchPreflightReport:
    project_id: str
    through_episode: int
    chapters: tuple[BatchPreflightChapter, ...]
    final_saved: int
    draft_only: int
    missing: int
    current_qc_records: int
    stale_qc_records: int
    selected_references: int
    reference_formats: tuple[tuple[str, int], ...]
    reference_fingerprint: str
    model_identity_checked: bool
    status: str = 'READ_ONLY_PREFLIGHT_NOT_VERIFIED'
    model_invocations: int = 0
    publication_approved: bool = False


def _readonly_database(raw_path: str):
    if type(raw_path) is not str or not raw_path:
        raise BatchPreflightError('기존 SQLite 파일을 먼저 선택해야 합니다.')
    path = Path(raw_path)
    if (not path.is_absolute() or path.is_symlink() or not path.is_file()
            or raw_path.startswith(('\\\\', '//', 'file:'))):
        raise BatchPreflightError('기존 로컬 SQLite 파일을 확인할 수 없습니다.')
    # mode=ro refuses nonexistent DB and avoids implicit file creation.
    uri = 'file:' + quote(str(path.resolve()), safe='/:') + '?mode=ro'
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA query_only=ON')
    except sqlite3.Error:
        raise BatchPreflightError('기존 SQLite를 읽기 전용으로 열 수 없습니다.') from None
    return connection


def build_batch_preflight(database_path: str, project_id: str, *,
                          through_episode: int, reference_paths: tuple[str, ...],
                          model_identity: LocalModelIdentity | None = None,
                          executable: str = '', arguments: str = '',
                          ) -> BatchPreflightReport:
    if type(project_id) is not str or not project_id:
        raise BatchPreflightError('기존 작품을 먼저 선택해야 합니다.')
    if type(through_episode) is not int or not 1 <= through_episode <= 1000:
        raise BatchPreflightError('회차는 1~1000화에서 선택해야 합니다.')
    if type(reference_paths) is not tuple or len(reference_paths) > 100:
        raise BatchPreflightError('선택한 참고작 범위가 올바르지 않습니다.')
    if model_identity is not None:
        verify_local_model_identity(model_identity, executable, arguments)
    if reference_paths:
        # Five file types, actual bytes, 1~100 selected files; never persist prose.
        reference = plan_reference_intake(reference_paths)
        selected_count = len(reference.entries)
        formats = reference.formats
        reference_stamp = reference.fingerprint
    else:
        selected_count = 0
        formats = ()
        reference_stamp = 'NOT_SELECTED_NOT_CHECKED'
    try:
        with _readonly_database(database_path) as db:
            project = db.execute(
                'SELECT 1 FROM bible_projects WHERE project_id=?',
                (project_id,)).fetchone()
            if project is None:
                raise BatchPreflightError('선택한 작품을 SQLite에서 찾을 수 없습니다.')
            records = db.execute("""SELECT episode, revision, plot, draft, final_text, summary
                FROM bible_episodes WHERE project_id=? AND episode BETWEEN 1 AND ?
                ORDER BY episode""", (project_id, through_episode)).fetchall()
            checks = db.execute("""SELECT episode, content_revision, category, outcome, note
                FROM bible_episode_checks WHERE project_id=?
                AND episode BETWEEN 1 AND ?""", (project_id, through_episode)).fetchall()
    except sqlite3.Error:
        raise BatchPreflightError('기존 작품의 회차 또는 QC 기록을 읽을 수 없습니다.') from None
    existing = {int(row['episode']): row for row in records}
    current, stale = {}, {}
    checked_evidence: dict[int, list[tuple[int, str, str, str]]] = {}
    for item in checks:
        episode = int(item['episode'])
        record = existing.get(episode)
        checked_evidence.setdefault(episode, []).append((
            int(item['content_revision']), str(item['category']),
            str(item['outcome']), str(item['note'])))
        if record is None:
            continue
        target = current if int(item['content_revision']) == int(record['revision']) else stale
        target[episode] = target.get(episode, 0) + 1
    chapters = []
    for number in range(1, through_episode + 1):
        item = existing.get(number)
        if item is None:
            chapters.append(BatchPreflightChapter(number, None, 'MISSING', 0, 0))
        else:
            status = ('FINAL_SAVED_NOT_PUBLISHED' if item['final_text'].strip()
                      else 'DRAFT_ONLY' if item['draft'].strip() else 'EMPTY')
            chapters.append(BatchPreflightChapter(
                number, int(item['revision']), status,
                current.get(number, 0), stale.get(number, 0),
                saved_source_sha256=sha256(repr((
                    item['plot'], item['draft'], item['final_text'],
                    item['summary'], int(item['revision']))).encode('utf-8')).hexdigest(),
                qc_source_sha256=sha256(repr(sorted(
                    checked_evidence.get(number, ()))).encode('utf-8')).hexdigest()))
    chapters = tuple(chapters)
    return BatchPreflightReport(
        project_id, through_episode, chapters,
        sum(c.status == 'FINAL_SAVED_NOT_PUBLISHED' for c in chapters),
        sum(c.status == 'DRAFT_ONLY' for c in chapters),
        sum(c.status in ('MISSING', 'EMPTY') for c in chapters),
        sum(c.qc_records_current for c in chapters),
        sum(c.qc_records_stale for c in chapters),
        selected_count, formats, reference_stamp, model_identity is not None)


def require_current_batch_preflight(
    snapshot: BatchPreflightReport, database_path: str, project_id: str, *,
    through_episode: int, reference_paths: tuple[str, ...],
    model_identity: LocalModelIdentity | None = None,
    executable: str = '', arguments: str = '',
) -> None:
    """기존 편집기 이동 전 원고·QC·참고작 5종·로컬 GGUF 지문 재확인."""
    if type(snapshot) is not BatchPreflightReport or snapshot.project_id != project_id:
        raise BatchPreflightError('작품이 변경됐습니다. 다시 조회하세요.')
    current = build_batch_preflight(
        database_path, project_id, through_episode=through_episode,
        reference_paths=reference_paths, model_identity=model_identity,
        executable=executable, arguments=arguments)
    if current != snapshot:
        raise BatchPreflightError('원고·QC·참고작·모델/회차 상태가 바뀌었습니다. 다시 조회하세요.')
