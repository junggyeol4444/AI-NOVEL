"""작가 직접 기록한 인물·복선·시간선 사실과 저장 최종본의 읽기 전용 대조.

정확한 문자열 출현만 집계한다. 출현/미출현은 진위·모순·품질·저작권·
QC PASS·출판 승인 판정이 아니며 원고·작가 기록·모델 파일을 수정하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from .author_arc_ledger import canon_fingerprint
from .author_fact_ledger import (
    AuthorFactError, ledger_fingerprint, read_author_facts,
)
from .database.episodes import EpisodeStore


class AuthorFactFinalAlignmentError(ValueError):
    """작품 내용과 파일 경로를 포함하지 않는 사용자 안내 오류."""


@dataclass(frozen=True)
class AuthorFactFinalRow:
    episode: int
    revision: int | None
    final_chars: int
    active_facts: int
    stale_sources: int
    value_found: int
    value_not_found: int
    conflicting_keys: int
    status: str = 'AUTHOR_REVIEW_REQUIRED_NOT_CERTIFIED'


@dataclass(frozen=True)
class AuthorFactFinalSnapshot:
    project_id: str = field(repr=False)
    folder: str = field(repr=False)
    through_episode: int = 1
    source_sha256: str = field(default='', repr=False)
    rows: tuple[AuthorFactFinalRow, ...] = ()
    missing_final: int = 0
    stale_source_rows: int = 0
    review_candidate_rows: int = 0
    status: str = 'READ_ONLY_NOT_VERIFIED'
    quality_certified: bool = False
    publication_approved: bool = False


@dataclass(frozen=True)
class AuthorFactEpisodeEvidenceRow:
    source_episode: int
    kind: str
    subject: str
    predicate: str
    value: str = field(repr=False)
    source_current: bool = False
    value_found: bool = False
    competing_values: bool = False


@dataclass(frozen=True)
class AuthorFactEpisodeEvidence:
    project_id: str = field(repr=False)
    episode: int = 0
    revision: int = 0
    final_sha256: str = field(default='', repr=False)
    final_text: str = field(default='', repr=False)
    facts: tuple[AuthorFactEpisodeEvidenceRow, ...] = ()
    status: str = 'AUTHOR_REVIEW_REQUIRED_NOT_CERTIFIED'
    publication_approved: bool = False


def _source_state(store: EpisodeStore, project_id: str, folder: str | Path,
                  through_episode: int):
    if (not isinstance(store, EpisodeStore) or type(project_id) is not str
            or not project_id or store.get_project(project_id) is None):
        raise AuthorFactFinalAlignmentError('기존 작품을 먼저 선택하세요.')
    if type(through_episode) is not int or not 1 <= through_episode <= 1000:
        raise AuthorFactFinalAlignmentError('조회 범위는 1~1000화입니다.')
    directory = Path(folder)
    if (not directory.is_absolute() or directory.is_symlink()
            or not directory.is_dir() or str(directory).startswith(('\\\\', '//'))):
        raise AuthorFactFinalAlignmentError('작가가 기존 사실 기록 폴더를 직접 선택하세요.')
    try:
        facts = tuple(f for f in read_author_facts(directory, project_id)
                      if not f.retracted)
        ledger_sha = ledger_fingerprint(directory)
        canon_sha = canon_fingerprint(store, project_id)
        saved = {row.episode: row for row in store.list_episodes(project_id)}
    except (AuthorFactError, ValueError, OSError, UnicodeError, TypeError):
        raise AuthorFactFinalAlignmentError('기존 사실 기록 또는 저장 원고를 읽지 못했습니다.') from None
    digest = sha256()
    for item in (project_id, str(directory.resolve()), str(through_episode),
                 ledger_sha, canon_sha):
        data = item.encode('utf-8')
        digest.update(len(data).to_bytes(8, 'big'))
        digest.update(data)
    # 사실의 근거 회차가 선택 범위 밖에 있어도 변경을 놓치지 않도록 모든 저장 회차를 결합한다.
    for number, row in sorted(saved.items()):
        digest.update(str(number).encode('ascii') + b'\0')
        digest.update(str(row.revision).encode('ascii') + b'\0')
        for attr in ('plot', 'draft', 'final_text', 'summary'):
            raw = getattr(row, attr, '')
            if type(raw) is not str:
                raise AuthorFactFinalAlignmentError('저장 원고 형식이 올바르지 않습니다.')
            encoded = raw.encode('utf-8')
            digest.update(len(encoded).to_bytes(8, 'big'))
            digest.update(sha256(encoded).digest())
    return str(directory.resolve()), facts, saved, digest.hexdigest()


def build_author_fact_final_alignment(
    store: EpisodeStore, project_id: str, *, folder: str | Path,
    through_episode: int,
) -> AuthorFactFinalSnapshot:
    """1~선택 회차의 최종본 전체 문자열과 작가 사실 유효 범위를 실제 대조."""
    directory, facts, saved, digest = _source_state(
        store, project_id, folder, through_episode)
    source_stale = {}
    for fact in facts:
        source = saved.get(fact.source_episode)
        source_stale[fact.fact_id] = (
            source is None or source.revision != fact.source_revision
            or sha256(source.final_text.encode('utf-8')).hexdigest() != fact.source_sha256)
    rows = []
    for number in range(1, through_episode + 1):
        chapter = saved.get(number)
        final = chapter.final_text if chapter is not None else ''
        active = [f for f in facts if f.valid_from <= number <= f.valid_until]
        keys: dict[tuple[str, str, str], set[str]] = {}
        for fact in active:
            keys.setdefault((fact.kind, fact.subject, fact.predicate), set()).add(fact.value)
        rows.append(AuthorFactFinalRow(
            episode=number,
            revision=chapter.revision if chapter is not None else None,
            final_chars=len(''.join(final.split())),
            active_facts=len(active),
            stale_sources=sum(source_stale[f.fact_id] for f in active),
            value_found=sum(bool(final) and f.value in final for f in active),
            value_not_found=sum(not final or f.value not in final for f in active),
            conflicting_keys=sum(len(values) > 1 for values in keys.values()),
        ))
    return AuthorFactFinalSnapshot(
        project_id=project_id, folder=directory,
        through_episode=through_episode, source_sha256=digest,
        rows=tuple(rows),
        missing_final=sum(row.final_chars == 0 for row in rows),
        stale_source_rows=sum(row.stale_sources > 0 for row in rows),
        review_candidate_rows=sum(row.value_not_found > 0 or row.conflicting_keys > 0
                                  or row.stale_sources > 0 for row in rows),
    )


def require_current_author_fact_final_alignment(
    snapshot: AuthorFactFinalSnapshot, store: EpisodeStore, project_id: str,
) -> None:
    """별도 직접 클릭 직전에 기존 기록·원고 지문을 재확인한다."""
    if (not isinstance(snapshot, AuthorFactFinalSnapshot)
            or snapshot.project_id != project_id):
        raise AuthorFactFinalAlignmentError('작품이 변경됐습니다. 다시 조회하세요.')
    current = build_author_fact_final_alignment(
        store, project_id, folder=snapshot.folder,
        through_episode=snapshot.through_episode)
    if current.source_sha256 != snapshot.source_sha256 or current.rows != snapshot.rows:
        raise AuthorFactFinalAlignmentError('원고 또는 사실 기록이 변경됐습니다. 다시 조회하세요.')


def read_author_fact_episode_evidence(
    snapshot: AuthorFactFinalSnapshot, store: EpisodeStore, project_id: str, *,
    episode: int,
) -> AuthorFactEpisodeEvidence:
    """작가가 고른 저장 회차 원문과 사실 근거를 별도 읽기 전용 클릭에서 표시한다.

    조회 시점과 반환 직전의 원고·사실 원장 지문을 재확인한다. 문자열
    출현/충돌 후보는 작가 검토 대상일 뿐 진위나 QC 합격이 아니다.
    """
    if (type(snapshot) is not AuthorFactFinalSnapshot
            or type(episode) is not int
            or not 1 <= episode <= snapshot.through_episode
            or snapshot.project_id != project_id):
        raise AuthorFactFinalAlignmentError('작품·조회 범위·선택 회차가 변경됐습니다.')
    require_current_author_fact_final_alignment(snapshot, store, project_id)
    directory, facts, saved, digest = _source_state(
        store, project_id, snapshot.folder, snapshot.through_episode)
    if directory != snapshot.folder or digest != snapshot.source_sha256:
        raise AuthorFactFinalAlignmentError('작가 사실·저장 원고가 변경됐습니다. 다시 조회하세요.')
    chapter = saved.get(episode)
    expected = snapshot.rows[episode - 1]
    if (expected.episode != episode or chapter is None
            or chapter.revision != expected.revision
            or not chapter.final_text.strip()):
        raise AuthorFactFinalAlignmentError('선택 회차의 저장 최종본을 다시 확인하세요.')
    text = chapter.final_text
    active = tuple(f for f in facts if f.valid_from <= episode <= f.valid_until)
    keys: dict[tuple[str, str, str], set[str]] = {}
    for fact in active:
        keys.setdefault((fact.kind, fact.subject, fact.predicate), set()).add(fact.value)
    evidence = []
    for fact in sorted(active, key=lambda f: (
            f.kind, f.subject, f.predicate, f.source_episode, f.fact_id)):
        source = saved.get(fact.source_episode)
        current = bool(
            source is not None and source.revision == fact.source_revision
            and sha256(source.final_text.encode('utf-8')).hexdigest() == fact.source_sha256)
        evidence.append(AuthorFactEpisodeEvidenceRow(
            source_episode=fact.source_episode, kind=fact.kind,
            subject=fact.subject, predicate=fact.predicate, value=fact.value,
            source_current=current, value_found=fact.value in text,
            competing_values=len(keys[(fact.kind, fact.subject, fact.predicate)]) > 1))
    if (expected.active_facts != len(evidence)
            or expected.stale_sources != sum(not f.source_current for f in evidence)
            or expected.value_found != sum(f.value_found for f in evidence)
            or expected.value_not_found != sum(not f.value_found for f in evidence)
            or expected.conflicting_keys != sum(len(values) > 1 for values in keys.values())
            or expected.final_chars != len(''.join(text.split()))):
        raise AuthorFactFinalAlignmentError('회차 사실 대조 근거가 변경됐습니다. 다시 조회하세요.')
    require_current_author_fact_final_alignment(snapshot, store, project_id)
    return AuthorFactEpisodeEvidence(
        project_id=project_id, episode=episode, revision=chapter.revision,
        final_sha256=sha256(text.encode('utf-8')).hexdigest(),
        final_text=text, facts=tuple(evidence))
