"""Read-only 1..1000-chapter *actual saved prose* evidence screening.

This fills the gap between the existing status-only review dashboard and
a repeatable local scan of the user's currently stored text. Findings are
quantitative evidence, NEVER semantic continuity or literary QC approval.
No LLM, HTTP, publishing, database writes or manuscript rewriting.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Mapping
import csv
import io
import os
import secrets

from .database.episodes import EpisodeStore
from .episode_crosscheck import _sentences
from .korean_draft_quality import screen_korean_draft


class FullManuscriptScreenError(ValueError):
    """Private manuscript text is never embedded in error messages."""


@dataclass(frozen=True)
class FullScreenChapter:
    episode: int
    revision: int | None
    source: str
    nonspace_chars: int
    hangul_share: float
    local_format_gate: bool
    exact_prior_reuse: int
    prior_affected: int
    prior_examined: int
    prior_missing: int
    status: str
    human_review_required: bool = True
    literary_quality_approved: bool = False


@dataclass(frozen=True)
class FullScreenReport:
    project_id: str
    through_episode: int
    target_chars: int
    source_sha256: str
    chapters: tuple[FullScreenChapter, ...]
    missing_saved_text: int
    format_warnings: int
    exact_reuse_warnings: int
    checked_scope_only: bool = True
    literary_quality_approved: bool = False
    publication_approved: bool = False


def scan_saved_full_manuscript(
    store: EpisodeStore, project_id: str, *,
    through_episode: int, target_chars: int = 5000,
) -> FullScreenReport:
    """Incremental bounded 250-chapter lexical memory, all 1..N chapters.

    Unlike calling pairwise repeated-text comparisons N×250 times, maintain
    a sliding 250-chapter index of exact normalized sentences. The full source
    stays only in the existing local SQLite; no text leaves this process.
    """
    if (not isinstance(store, EpisodeStore) or type(project_id) is not str
            or not project_id
            or type(through_episode) is not int or
            not 1 <= through_episode <= 1000
            or type(target_chars) is not int or
            not 100 <= target_chars <= 50000):
        raise FullManuscriptScreenError('전체 원고 검사 범위가 올바르지 않습니다.')
    store.get_project(project_id)
    existing = {row.episode: row for row in store.list_episodes(project_id)}
    owners: dict[str, set[int]] = defaultdict(set)
    previous: deque[tuple[int, set[str]]] = deque()
    source_digest = sha256()
    rows: list[FullScreenChapter] = []
    for number in range(1, through_episode + 1):
        while previous and previous[0][0] < number - 250:
            old_number, tokens = previous.popleft()
            for token in tokens:
                seen = owners.get(token)
                if seen is not None:
                    seen.discard(old_number)
                    if not seen:
                        del owners[token]
        saved = existing.get(number)
        revision = saved.revision if saved else None
        final = getattr(saved, 'final_text', '') or ''
        draft = getattr(saved, 'draft', '') or ''
        if type(final) is str and final.strip():
            body, kind = final, 'SAVED_FINAL_SEPARATE_APPROVAL'
        elif type(draft) is str and draft.strip():
            body, kind = draft, 'UNREVIEWED_DRAFT'
        else:
            body, kind = '', 'MISSING_TEXT'
        source_digest.update(f'{number}:{revision or 0}:{kind}:'.encode('utf-8'))
        source_digest.update(sha256(body.encode('utf-8')).digest())
        scanned_prior = len(previous)
        prior_missing = max(0, min(250, number - 1) - scanned_prior)
        if not body:
            rows.append(FullScreenChapter(
                number, revision, kind, 0, 0.0, False, 0, 0,
                scanned_prior, prior_missing, 'MISSING_TEXT'))
            continue
        if len(body) > 100000:
            rows.append(FullScreenChapter(
                number, revision, kind, len(''.join(body.split())), 0.0,
                False, 0, 0, scanned_prior, prior_missing,
                'BOUNDED_SCREEN_EXCEEDED'))
            continue
        screen = screen_korean_draft(body, target_chars=target_chars)
        current_sentences = _sentences(body)
        matched = {sentence for sentence in current_sentences if sentence in owners}
        prior_affected: set[int] = set()
        for sentence in matched:
            prior_affected.update(owners[sentence])
        # Do not add hypothetical text or draft summaries. Save these only
        # in this local in-memory index (never to original SQLite).
        previous.append((number, current_sentences))
        for sentence in current_sentences:
            owners[sentence].add(number)
        if not screen.format_gate_pass and matched:
            status = 'FORMAT_AND_EXACT_REUSE_REVIEW'
        elif not screen.format_gate_pass:
            status = 'KOREAN_PROSE_FORMAT_REVIEW'
        elif matched:
            status = 'EXACT_SENTENCE_REUSE_REVIEW'
        else:
            status = 'NO_FLAGS_IN_BOUNDED_SCREEN'
        rows.append(FullScreenChapter(
            number, revision, kind, screen.nonspace_chars,
            screen.hangul_share, screen.format_gate_pass,
            len(matched), len(prior_affected),
            scanned_prior, prior_missing, status))
    chapters = tuple(rows)
    return FullScreenReport(
        project_id, through_episode, target_chars, source_digest.hexdigest(),
        chapters,
        sum(row.source == 'MISSING_TEXT' for row in chapters),
        sum(not row.local_format_gate for row in chapters),
        sum(row.exact_prior_reuse > 0 for row in chapters))


@dataclass(frozen=True)
class FullScreenExportReceipt:
    path: Path
    chapter_count: int
    sha256: str
    status: str = 'LOCAL_QUANTITATIVE_EVIDENCE_ONLY'
    publication_approved: bool = False


def export_full_manuscript_screen_csv(
    store: EpisodeStore, report: FullScreenReport,
    output_directory: str | Path, *,
    explicit_author_export: bool,
) -> FullScreenExportReceipt:
    """Author-click-only new CSV, no private prose and no silent overwrite."""
    if (explicit_author_export is not True
            or not isinstance(report, FullScreenReport)):
        raise FullManuscriptScreenError('검사 현황과 직접 저장 승인이 필요합니다.')
    current = scan_saved_full_manuscript(
        store, report.project_id, through_episode=report.through_episode,
        target_chars=report.target_chars)
    if current != report:
        raise FullManuscriptScreenError('저장 원고가 변경되었습니다. 먼저 다시 검사하세요.')
    folder = Path(output_directory)
    if (not folder.is_absolute() or folder.is_symlink()
            or not folder.is_dir()
            or str(folder).startswith(('\\\\', '//'))):
        raise FullManuscriptScreenError('기존 로컬 CSV 저장 폴더를 직접 선택해야 합니다.')
    content = io.StringIO(newline='')
    writer = csv.writer(content, lineterminator='\n')
    writer.writerow(('ANF_OFFLINE_SAVED_TEXT_SCOPE_V1',
                     '문학적 품질/저작권/인과/시점/출판 승인 아님'))
    writer.writerow(('화수', '저장 개정', '저장 본문 출처', '공백 제외 글자',
                     '한글 비율', '형식 스크린', '이전 회차 정확한 동일 문장 종류',
                     '관련 이전 회차 수', '이전 실제 본문 검사 수',
                     '이전 본문 누락 수', '한정 검사 상태',
                     '작가 직접 검수'))
    for item in report.chapters:
        writer.writerow((item.episode, item.revision or '',
                         item.source, item.nonspace_chars,
                         item.hangul_share,
                         '범위 내 형식 OK' if item.local_format_gate else '검토 필요',
                         item.exact_prior_reuse, item.prior_affected,
                         item.prior_examined, item.prior_missing, item.status,
                         '필수'))
    data = ('\ufeff' + content.getvalue()).encode('utf-8')
    name = 'anf-full-text-screen-' + datetime.now(
        timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + secrets.token_hex(5) + '.csv'
    path = folder / name
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
    except OSError:
        raise FullManuscriptScreenError('검수 CSV 새 파일 저장에 실패했습니다.') from None
    return FullScreenExportReceipt(path, len(report.chapters), sha256(data).hexdigest())
