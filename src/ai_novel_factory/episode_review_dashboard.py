"""Read-only whole-book review dashboard from the existing SQLite project.

Combines the real per-revision QC records, selected reference comparison
coverage, and separate author review ledger. A QC PASS or a checked reference
scope is never promoted to human review, publication consent or literary
quality certification. No model is invoked and no data is changed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .database.episodes import EpisodeStore
from .manual_review_gate import review_state
from .reference_coverage_report import summarize_reference_coverage
from .review_worklist import EXPECTED_CHECKS, get_review_worklist


@dataclass(frozen=True)
class ReviewDashboardChapter:
    episode: int
    revision: int | None
    manuscript: str
    qc_state: str
    qc_missing: int
    qc_stale: int
    qc_pending: int
    qc_failed: int
    reference_scope: str
    human_review: str
    requires_attention: bool = True
    publication_approved: bool = False


@dataclass(frozen=True)
class ReviewDashboard:
    project_id: str
    through_episode: int
    chapters: tuple[ReviewDashboardChapter, ...]
    missing_manuscripts: int
    unreviewed_or_stale: int
    reference_not_examined: int
    qc_incomplete: int
    publication_approved: bool = False


def build_review_dashboard(
    store: EpisodeStore, project_id: str, *, through_episode: int,
) -> ReviewDashboard:
    """Never use older revision PASS or a ledger for another project."""
    if not isinstance(store, EpisodeStore):
        raise ValueError('현재 기존 작품 SQLite를 열어야 합니다.')
    if type(project_id) is not str or not project_id:
        raise ValueError('작품을 선택해야 합니다.')
    if type(through_episode) is not int or not 1 <= through_episode <= 1000:
        raise ValueError('조회 범위는 1~1000화입니다.')
    store.get_project(project_id)
    episodes = {item.episode: item for item in store.list_episodes(project_id)}
    work = {item.episode: item for item in get_review_worklist(store, project_id).chapters}
    coverage = summarize_reference_coverage(
        store, project_id, through_episode=through_episode)
    references = {item.episode: item.status for item in coverage.chapters}
    rows = []
    for number in range(1, through_episode + 1):
        episode = episodes.get(number)
        if episode is None:
            rows.append(ReviewDashboardChapter(
                number, None, 'MISSING', 'NOT_RUN', len(EXPECTED_CHECKS),
                0, 0, 0, references[number], 'UNREVIEWED'))
            continue
        item = work[number]
        state = review_state(store, project_id, number)
        if not episode.final_text.strip():
            manuscript = 'DRAFT_ONLY' if episode.draft.strip() else 'EMPTY'
        else:
            manuscript = 'FINAL_SAVED_NOT_PUBLISHED'
        if item.failed_checks:
            qc_state = 'FAILED'
        elif item.missing_checks or item.stale_checks or item.pending_checks:
            qc_state = 'INCOMPLETE_OR_STALE'
        else:
            qc_state = 'RECORDED_SCOPE_ONLY'
        rows.append(ReviewDashboardChapter(
            number, episode.revision, manuscript, qc_state,
            len(item.missing_checks), len(item.stale_checks),
            len(item.pending_checks), len(item.failed_checks),
            references[number], state.status))
    chapters = tuple(rows)
    return ReviewDashboard(
        project_id, through_episode, chapters,
        sum(c.manuscript in {'MISSING', 'EMPTY'} for c in chapters),
        sum(not c.human_review.startswith('REVIEWED_') for c in chapters),
        sum(c.reference_scope in {'NOT_RUN', 'STALE', 'INCOMPLETE'}
            for c in chapters),
        sum(c.qc_state != 'RECORDED_SCOPE_ONLY' for c in chapters))


@dataclass(frozen=True)
class ReviewDashboardExportReceipt:
    """Local metadata-only worklist, never a publication or quality certificate."""
    file: "Path" = field(repr=False)
    chapter_count: int
    digest: str = field(repr=False)
    status: str = 'LOCAL_REVIEW_WORKLIST_ONLY'
    publication_approved: bool = False


def export_review_dashboard_csv(
    store: EpisodeStore, project_id: str, report: ReviewDashboard,
    output_directory: "str | Path", *, explicit_author_export: bool,
) -> ReviewDashboardExportReceipt:
    """별도 작가 승인으로 현재 1~N화 검수 현황만 새 로컬 CSV에 내보낸다.

    원고 본문·QC 노트·참고작 원문·경로·모델/계정 정보는 포함하지 않는다.
    저장된 QC PASS도 문학적 합격이나 출판 허가로 표시하지 않는다.
    """
    import csv
    from datetime import datetime, timezone
    from hashlib import sha256
    from io import StringIO
    import os
    from pathlib import Path
    import secrets

    if (explicit_author_export is not True or type(report) is not ReviewDashboard
            or not isinstance(store, EpisodeStore)
            or type(project_id) is not str or report.project_id != project_id
            or type(report.through_episode) is not int
            or not 1 <= report.through_episode <= 1000
            or len(report.chapters) != report.through_episode
            or report.publication_approved is not False):
        raise ValueError('현재 작품·회차 전체 검수 내보내기를 직접 승인해야 합니다.')
    directory = Path(output_directory)
    if (not directory.is_absolute() or directory.is_symlink()
            or not directory.is_dir()
            or str(directory).startswith(('\\\\', '//'))):
        raise ValueError('기존 로컬 출력 폴더를 직접 선택해야 합니다.')
    # Compare against live SQLite again: never export a stale screen snapshot.
    current = build_review_dashboard(
        store, project_id, through_episode=report.through_episode)
    if current != report:
        raise ValueError('원고·QC·참고작·작가 검수 상태가 바뀌어 다시 조회해야 합니다.')
    for number, chapter in enumerate(report.chapters, 1):
        if chapter.episode != number or chapter.publication_approved is not False:
            raise ValueError('검수 회차의 순서 또는 미승인 상태가 올바르지 않습니다.')

    buffer = StringIO(newline='')
    writer = csv.writer(buffer, lineterminator='\n')
    writer.writerow(('ANF_LOCAL_REVIEW_WORKLIST_V1', '작가 수동 검수용',
                     '문학적 품질·저작권·출판 승인 아님'))
    writer.writerow(('작품 식별 SHA256', sha256(project_id.encode('utf-8')).hexdigest()))
    writer.writerow(('조회 마지막 회차', report.through_episode))
    writer.writerow(('누락·빈 원고', report.missing_manuscripts))
    writer.writerow(('미검수·과거 검수', report.unreviewed_or_stale))
    writer.writerow(('참고작 미검사·불완전', report.reference_not_examined))
    writer.writerow(('QC 불완전', report.qc_incomplete))
    writer.writerow(())
    writer.writerow((
        '회차', '저장 revision', '원고 상태', 'QC 범위', 'QC 누락', 'QC 과거 기록',
        'QC 미완료', 'QC 실패', '참고작 검사 범위', '작가 검수',
        '수동 확인 필요', '출판 승인'))
    for chapter in report.chapters:
        writer.writerow((
            chapter.episode,
            chapter.revision if chapter.revision is not None else '',
            chapter.manuscript, chapter.qc_state,
            chapter.qc_missing, chapter.qc_stale,
            chapter.qc_pending, chapter.qc_failed,
            chapter.reference_scope, chapter.human_review,
            '필요' if chapter.requires_attention else '별도 확인',
            '아니요'))
    data = ('\ufeff' + buffer.getvalue()).encode('utf-8')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output = directory / f'anf-review-{stamp}-{secrets.token_hex(6)}.csv'
    try:
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        # Never overwrite/delete a file on the author's behalf.
        raise ValueError('새 로컬 검수 CSV를 저장하지 못했습니다.') from None
    return ReviewDashboardExportReceipt(
        output, report.through_episode, sha256(data).hexdigest())
