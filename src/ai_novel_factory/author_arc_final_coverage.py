"""작가 장편 아크의 복선·해소 계획과 저장 최종본을 읽기 전용으로 대조한다.

문자열 출현은 문학적 복선 회수·논리적 시간 순서·QC 합격·출판 승인을
증명하지 않는다. SQLite, 작가 JSON, 모델 및 원고를 변경하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from .author_arc_ledger import (
    AuthorArcError, arc_ledger_fingerprint, canon_fingerprint,
    read_author_arcs,
)
from .database.episodes import EpisodeStore


class AuthorArcFinalCoverageError(ValueError):
    """원고·개인 파일 경로를 오류 메시지에 노출하지 않는다."""


@dataclass(frozen=True)
class AuthorArcCoverageRow:
    arc_id: str = field(repr=False)
    start: int = 1
    end: int = 1
    title: str = ''
    stored_final: int = 0
    missing_final: int = 0
    foreshadow_hits: int = 0
    resolution_hits: int = 0
    first_foreshadow: int | None = None
    first_resolution: int | None = None
    canon_changed: bool = False
    order_candidate: bool = False
    review_required: bool = True
    publication_approved: bool = False


@dataclass(frozen=True)
class AuthorArcCoverageSnapshot:
    project_id: str = field(repr=False)
    folder: str = field(repr=False)
    through_episode: int = 1
    source_sha256: str = field(default='', repr=False)
    rows: tuple[AuthorArcCoverageRow, ...] = ()
    review_candidate_count: int = 0
    status: str = 'AUTHOR_REVIEW_REQUIRED_NOT_VERIFIED'
    quality_certified: bool = False
    publication_approved: bool = False


def build_author_arc_final_coverage(
    store: EpisodeStore, project_id: str, *, folder: str | Path,
    through_episode: int,
) -> AuthorArcCoverageSnapshot:
    """아크 범위 내 저장 최종본 전체를 대조하고 변경 감지 지문을 묶는다."""
    if (not isinstance(store, EpisodeStore) or type(project_id) is not str
            or not project_id or type(through_episode) is not int
            or not 1 <= through_episode <= 1000):
        raise AuthorArcFinalCoverageError('기존 작품과 1~1000화 범위를 직접 선택하세요.')
    directory = Path(folder)
    if (not directory.is_absolute() or directory.is_symlink()
            or not directory.is_dir() or str(directory).startswith(('\\', '//'))):
        raise AuthorArcFinalCoverageError('기존 로컬 아크 기록 폴더를 직접 선택하세요.')
    try:
        if store.get_project(project_id) is None:
            raise AuthorArcFinalCoverageError('현재 작품을 찾을 수 없습니다.')
        before = arc_ledger_fingerprint(directory)
        arcs = tuple(arc for arc in read_author_arcs(directory, project_id)
                     if not arc.withdrawn)
        canon = canon_fingerprint(store, project_id)
        episodes = {ep.episode: ep for ep in store.list_episodes(project_id)}
        digest = sha256()
        for item in (project_id, str(directory.resolve()), str(through_episode),
                     before, canon):
            raw = item.encode('utf-8')
            digest.update(len(raw).to_bytes(8, 'big') + raw)
        for number, ep in sorted(episodes.items()):
            digest.update(str(number).encode('ascii') + b'\0')
            digest.update(str(ep.revision).encode('ascii') + b'\0')
            for key in ('plot', 'draft', 'final_text', 'summary'):
                value = getattr(ep, key)
                if type(value) is not str:
                    raise AuthorArcFinalCoverageError('저장 원고 형식이 올바르지 않습니다.')
                raw = value.encode('utf-8')
                digest.update(len(raw).to_bytes(8, 'big') + sha256(raw).digest())
        rows = []
        for arc in arcs:
            if arc.start > through_episode:
                continue
            last = min(arc.end, through_episode)
            numbers = range(arc.start, last + 1)
            final = {n: episodes[n].final_text for n in numbers
                     if n in episodes and episodes[n].final_text.strip()}
            foreshadow = tuple(n for n, text in final.items()
                                if arc.foreshadow in text)
            resolution = tuple(n for n, text in final.items()
                                if arc.resolution in text)
            order_candidate = bool(foreshadow and resolution
                                   and min(resolution) < min(foreshadow))
            missing = (last - arc.start + 1) - len(final)
            changed = arc.canon_sha256 != canon
            review = bool(missing or not foreshadow or not resolution
                          or order_candidate or changed)
            rows.append(AuthorArcCoverageRow(
                arc_id=arc.arc_id, start=arc.start, end=arc.end,
                title=arc.title, stored_final=len(final), missing_final=missing,
                foreshadow_hits=len(foreshadow), resolution_hits=len(resolution),
                first_foreshadow=min(foreshadow) if foreshadow else None,
                first_resolution=min(resolution) if resolution else None,
                canon_changed=changed, order_candidate=order_candidate,
                review_required=review))
        if arc_ledger_fingerprint(directory) != before:
            raise AuthorArcFinalCoverageError('조회 중 아크 기록이 변경됐습니다.')
    except (AuthorArcError, OSError, UnicodeError, TypeError, LookupError):
        raise AuthorArcFinalCoverageError('현재 아크 기록과 저장 원고를 읽지 못했습니다.') from None
    return AuthorArcCoverageSnapshot(
        project_id=project_id, folder=str(directory.resolve()),
        through_episode=through_episode, source_sha256=digest.hexdigest(),
        rows=tuple(rows),
        review_candidate_count=sum(row.review_required for row in rows))


def require_current_author_arc_final_coverage(
    snapshot: AuthorArcCoverageSnapshot, store: EpisodeStore, project_id: str,
) -> None:
    """작가가 두 번째로 클릭할 때 기록·원고 변경을 전부 재확인한다."""
    if (not isinstance(snapshot, AuthorArcCoverageSnapshot)
            or snapshot.project_id != project_id):
        raise AuthorArcFinalCoverageError('작품이 변경됐습니다. 다시 직접 조회하세요.')
    current = build_author_arc_final_coverage(
        store, project_id, folder=snapshot.folder,
        through_episode=snapshot.through_episode)
    if (current.source_sha256 != snapshot.source_sha256
            or current.rows != snapshot.rows):
        raise AuthorArcFinalCoverageError('아크·작품 설정·원고가 변경됐습니다. 다시 조회하세요.')
