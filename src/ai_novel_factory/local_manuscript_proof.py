"""Author-click-only private TXT/MD proofreading copy of saved final chapters.

No publisher, uploader, network, model, source-reference importer or existing
SQLite write is called. A proof copy may contain unreviewed prose and therefore
labels every chapter's real review state; it is NEVER a publication package.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import os
import secrets

from .database.episodes import EpisodeStore
from .manual_review_gate import review_state
from .review_worklist import get_review_worklist


class ManuscriptProofError(ValueError):
    """Errors never include author manuscript or private paths."""


@dataclass(frozen=True)
class ProofChapter:
    episode: int
    revision: int
    final_sha256: str = field(repr=False)
    content: str = field(repr=False)
    qc_state: str = 'NOT_RUN'
    human_state: str = 'UNREVIEWED'
    publication_approved: bool = False


@dataclass(frozen=True)
class ManuscriptProofPlan:
    project_id: str = field(repr=False)
    through_episode: int
    chapters: tuple[ProofChapter, ...] = field(repr=False)
    fingerprint: str = field(repr=False)
    unreviewed: int
    qc_incomplete: int
    status: str = 'PRIVATE_PROOF_PLAN_NOT_PUBLISHED'
    publication_approved: bool = False


@dataclass(frozen=True)
class ManuscriptProofReceipt:
    folder: Path = field(repr=False)
    manifest: Path = field(repr=False)
    chapter_count: int
    status: str = 'PRIVATE_PROOF_NOT_PUBLISHED_NOT_VERIFIED'
    publication_approved: bool = False


def _hash(value: str) -> str:
    return sha256(value.encode('utf-8', 'surrogatepass')).hexdigest()


def _fingerprint(chapters: tuple[ProofChapter, ...]) -> str:
    rows = [(row.episode, row.revision, row.final_sha256,
             row.qc_state, row.human_state) for row in chapters]
    return sha256(json.dumps(rows, separators=(',', ':')).encode('ascii')).hexdigest()


def plan_manuscript_proof(store: EpisodeStore, project_id: str, *,
                          through_episode: int) -> ManuscriptProofPlan:
    if (not isinstance(store, EpisodeStore) or type(project_id) is not str or
            not project_id or type(through_episode) is not int or
            not 1 <= through_episode <= 1000):
        raise ManuscriptProofError('기존 작품과 1~1000화 범위를 선택해야 합니다.')
    store.get_project(project_id)
    saved = {row.episode: row for row in store.list_episodes(project_id)}
    qc = {row.episode: row for row in get_review_worklist(store, project_id).chapters}
    chapters = []
    for number in range(1, through_episode + 1):
        row = saved.get(number)
        if row is None or not row.final_text.strip():
            raise ManuscriptProofError('선택한 회차 범위에 저장된 최종 원고가 누락되었습니다.')
        state = review_state(store, project_id, number)
        checks = qc[number]
        qc_state = ('QC_RECORDED_SCOPE_ONLY' if not (
            checks.missing_checks or checks.stale_checks or
            checks.pending_checks or checks.failed_checks)
            else 'QC_INCOMPLETE_OR_FAILED')
        chapters.append(ProofChapter(number, row.revision, _hash(row.final_text),
                                     row.final_text, qc_state, state.status))
    rows = tuple(chapters)
    return ManuscriptProofPlan(
        project_id, through_episode, rows, _fingerprint(rows),
        sum(not r.human_state.startswith('REVIEWED_') for r in rows),
        sum(r.qc_state != 'QC_RECORDED_SCOPE_ONLY' for r in rows))


def create_manuscript_proof(store: EpisodeStore, project_id: str,
                            plan: ManuscriptProofPlan, output_directory: str | Path,
                            *, file_format: str, explicit_author_export: bool,
                            ) -> ManuscriptProofReceipt:
    if (explicit_author_export is not True or type(plan) is not ManuscriptProofPlan
            or plan.project_id != project_id or file_format not in {'txt', 'md'}):
        raise ManuscriptProofError('현재 작품의 비공개 교정본 형식과 이번 1회 저장을 승인하세요.')
    directory = Path(output_directory)
    if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():
        raise ManuscriptProofError('기존 로컬 교정본 저장 폴더를 직접 선택해야 합니다.')
    current = plan_manuscript_proof(store, project_id,
                                    through_episode=plan.through_episode)
    if current.fingerprint != plan.fingerprint:
        raise ManuscriptProofError('최종 원고가 변경되어 이전 교정본 승인이 무효화됐습니다.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    token = secrets.token_hex(6)
    folder = directory / f'anf-private-proof-{stamp}-{token}'
    try:
        folder.mkdir(mode=0o700, exist_ok=False)
        metadata = []
        for chapter in current.chapters:
            # Each chapter is private local text; no source references are copied.
            filename = f'{chapter.episode:04d}.{file_format}'
            target = folder / filename
            header = ('# ' if file_format == 'md' else '') + (
                f'{chapter.episode}화 · 비공개 교정본 / 출판 승인 아님\n'
                f'원고 상태: {chapter.human_state} / {chapter.qc_state}\n\n')
            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8', newline='') as output:
                output.write(header)
                output.write(chapter.content)
                output.flush()
                os.fsync(output.fileno())
            metadata.append({
                'episode': chapter.episode, 'filename': filename,
                'revision': chapter.revision,
                'final_sha256': chapter.final_sha256,
                'proof_file_sha256': sha256(target.read_bytes()).hexdigest(),
                'human_review': chapter.human_state,
                'qc_state': chapter.qc_state,
                'publication_approved': False,
            })
        after = plan_manuscript_proof(store, project_id,
                                      through_episode=plan.through_episode)
        current_state = (after.fingerprint == plan.fingerprint)
        manifest = folder / 'private-proof-manifest.json'
        record = {
            'schema': 'anf-private-manuscript-proof-v1',
            'created_utc': stamp,
            'project_id_sha256': sha256(project_id.encode('utf-8')).hexdigest(),
            'through_episode': plan.through_episode,
            'manuscript_fingerprint': plan.fingerprint,
            'format': file_format,
            'chapters': metadata,
            'status': ('PRIVATE_PROOF_NOT_PUBLISHED_NOT_VERIFIED' if current_state
                       else 'SOURCE_CHANGED_PROOF_NOT_CURRENT'),
            'publication_approved': False,
            'auto_upload': False,
        }
        fd = os.open(manifest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as output:
            json.dump(record, output, ensure_ascii=False, sort_keys=True, indent=2)
            output.write('\n')
        return ManuscriptProofReceipt(folder, manifest, len(metadata), record['status'])
    except (OSError, ValueError, TypeError):
        # Incomplete private output is left untouched for the author; no
        # automatic deletion or modification of original manuscripts.
        raise ManuscriptProofError('비공개 교정본 생성이 완료되지 않았습니다.') from None
