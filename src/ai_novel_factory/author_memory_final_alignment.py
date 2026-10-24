"""작가 기억 변화 원장과 SQLite 저장 최종본 1~1000화의 읽기 전용 대조.

작가가 직접 입력한 기억 문구의 *정확한 문자열* 출현만 센다.
출현 여부는 이야기의 기억 반영, 자연스러운 한국어, QC, 출판 승인 또는
모델 실행 동의를 증명하지 않는다. 원고/원장/DB에 쓰지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from .author_arc_ledger import canon_fingerprint
from .author_memory_delta import (
    AuthorMemoryDeltaError, list_author_memory_deltas, memory_delta_fingerprint,
)
from .database.episodes import EpisodeStore


class AuthorMemoryFinalAlignmentError(ValueError):
    """작가 원문과 개인 경로를 표시하지 않는 오류."""


@dataclass(frozen=True)
class AuthorMemoryFinalRow:
    episode: int
    revision: int | None
    final_characters: int
    applicable_memories: int
    stale_sources: int
    subject_found: int
    change_found: int
    change_not_found: int
    missing_final: bool
    status: str = 'AUTHOR_REVIEW_REQUIRED_NOT_CERTIFIED'


@dataclass(frozen=True)
class AuthorMemoryFinalSnapshot:
    project_id: str = field(repr=False)
    folder: str = field(repr=False)
    through_episode: int = 1
    source_sha256: str = field(default='', repr=False)
    rows: tuple[AuthorMemoryFinalRow, ...] = ()
    missing_final_chapters: int = 0
    stale_source_chapters: int = 0
    candidate_chapters: int = 0
    status: str = 'READ_ONLY_NOT_VERIFIED'
    quality_certified: bool = False
    publication_approved: bool = False


def _read_state(store: EpisodeStore, project_id: str, folder: str | Path,
                through_episode: int):
    if (not isinstance(store, EpisodeStore) or type(project_id) is not str
            or not project_id or type(through_episode) is not int
            or not 1 <= through_episode <= 1000):
        raise AuthorMemoryFinalAlignmentError('기존 작품과 1~1000화 조회 범위를 선택하세요.')
    directory = Path(folder)
    if (not directory.is_absolute() or directory.is_symlink()
            or not directory.is_dir() or str(directory).startswith(('\\\\', '//'))):
        raise AuthorMemoryFinalAlignmentError('기존 로컬 작가 기억 폴더를 직접 선택하세요.')
    try:
        if store.get_project(project_id) is None:
            raise AuthorMemoryFinalAlignmentError('현재 작품이 없습니다.')
        before = memory_delta_fingerprint(directory)
        memories = tuple(m for m in list_author_memory_deltas(directory, project_id)
                         if not m.retracted)
        canon = canon_fingerprint(store, project_id)
        saved = {ep.episode: ep for ep in store.list_episodes(project_id)}
        digest = sha256()
        for value in (project_id, str(directory.resolve()), str(through_episode),
                      before, canon):
            data = value.encode('utf-8')
            digest.update(len(data).to_bytes(8, 'big') + data)
        # 조회 범위 밖의 근거 최종본 수정도 놓치지 않도록 저장된 전 회차를 결합한다.
        for number, episode in sorted(saved.items()):
            digest.update(number.to_bytes(4, 'big'))
            digest.update(str(episode.revision).encode('ascii') + b'\x00')
            for attr in ('plot', 'draft', 'final_text', 'summary'):
                value = getattr(episode, attr)
                if type(value) is not str:
                    raise AuthorMemoryFinalAlignmentError('저장 원고 형식이 올바르지 않습니다.')
                raw = value.encode('utf-8')
                digest.update(len(raw).to_bytes(8, 'big') + sha256(raw).digest())
        if memory_delta_fingerprint(directory) != before:
            raise AuthorMemoryFinalAlignmentError('조회 도중 기억 원장이 변경됐습니다.')
        return str(directory.resolve()), memories, saved, digest.hexdigest()
    except (AuthorMemoryDeltaError, OSError, UnicodeError, LookupError, TypeError):
        raise AuthorMemoryFinalAlignmentError('기존 기억 기록 또는 저장 원고를 읽지 못했습니다.') from None


def build_author_memory_final_alignment(
    store: EpisodeStore, project_id: str, *, folder: str | Path,
    through_episode: int,
) -> AuthorMemoryFinalSnapshot:
    """적용 회차별 기억 대상/변화 문자열과 저장 최종본 전체를 직접 대조한다."""
    directory, memories, saved, stamp = _read_state(
        store, project_id, folder, through_episode)
    stale = {}
    for memory in memories:
        source = saved.get(memory.source_episode)
        stale[memory.delta_id] = bool(
            source is None or source.revision != memory.source_revision
            or not source.final_text.strip()
            or sha256(source.final_text.encode('utf-8')).hexdigest()
               != memory.source_sha256)
    rows = []
    for number in range(1, through_episode + 1):
        episode = saved.get(number)
        final = episode.final_text if episode is not None else ''
        applicable = tuple(m for m in memories
                           if m.valid_from <= number <= m.valid_through)
        fresh = tuple(m for m in applicable if not stale[m.delta_id])
        has_final = bool(final.strip())
        rows.append(AuthorMemoryFinalRow(
            episode=number,
            revision=episode.revision if episode is not None else None,
            final_characters=len(''.join(final.split())),
            applicable_memories=len(applicable),
            stale_sources=sum(stale[m.delta_id] for m in applicable),
            subject_found=sum(m.subject in final for m in fresh) if has_final else 0,
            change_found=sum(m.change in final for m in fresh) if has_final else 0,
            change_not_found=sum(m.change not in final for m in fresh) if has_final
                             else len(fresh),
            missing_final=not has_final,
        ))
    # SQLite/작가 파일이 조회 중 바뀌었다면 이전 표를 반환하지 않는다.
    if _read_state(store, project_id, directory, through_episode)[3] != stamp:
        raise AuthorMemoryFinalAlignmentError('기억 원장 또는 원고가 변경되어 다시 조회해야 합니다.')
    return AuthorMemoryFinalSnapshot(
        project_id=project_id, folder=directory, through_episode=through_episode,
        source_sha256=stamp, rows=tuple(rows),
        missing_final_chapters=sum(r.missing_final for r in rows),
        stale_source_chapters=sum(r.stale_sources > 0 for r in rows),
        candidate_chapters=sum(bool(r.change_not_found or r.stale_sources
                                    or r.missing_final or not r.applicable_memories)
                               for r in rows),
    )


def require_current_author_memory_final_alignment(
    snapshot: AuthorMemoryFinalSnapshot, store: EpisodeStore, project_id: str,
) -> None:
    """별도 두 번째 GUI 클릭에서 원장·원고·작품을 전부 재확인한다."""
    if (not isinstance(snapshot, AuthorMemoryFinalSnapshot)
            or snapshot.project_id != project_id):
        raise AuthorMemoryFinalAlignmentError('작품이 변경됐습니다. 다시 직접 조회하세요.')
    current = build_author_memory_final_alignment(
        store, project_id, folder=snapshot.folder,
        through_episode=snapshot.through_episode)
    if (current.source_sha256 != snapshot.source_sha256
            or current.rows != snapshot.rows):
        raise AuthorMemoryFinalAlignmentError('기억 원장·저장 원고 변경으로 이전 조회가 무효화됐습니다.')


@dataclass(frozen=True)
class AuthorMemoryEpisodeEvidenceRow:
    """작가가 기록한 적용 기억 한 건과 현재 최종본의 문자 일치 근거."""
    category: str
    subject: str = field(repr=False)
    change: str = field(repr=False)
    source_episode: int = 0
    source_revision: int = 0
    source_current: bool = False
    subject_present: bool = False
    change_present: bool = False


@dataclass(frozen=True)
class AuthorMemoryEpisodeEvidence:
    """읽기 전용 전체 저장 최종본 및 선택 회차에 적용되는 기억 기록."""
    episode: int
    revision: int
    final_sha256: str = field(repr=False)
    final_text: str = field(repr=False)
    memories: tuple[AuthorMemoryEpisodeEvidenceRow, ...] = ()
    status: str = 'AUTHOR_REVIEW_REQUIRED_NOT_QC'


def read_author_memory_episode_evidence(
    snapshot: AuthorMemoryFinalSnapshot, store: EpisodeStore,
    project_id: str, *, episode: int,
) -> AuthorMemoryEpisodeEvidence:
    """전수 대조 이후 작가가 직접 선택한 회차의 원문·기억 근거를 재조회한다.

    SQLite·기억 원장은 읽기 전용이며, 문구의 포함 여부는 문학적
    연속성이나 QC 합격을 뜻하지 않는다.
    """
    if (type(episode) is not int or not isinstance(snapshot, AuthorMemoryFinalSnapshot)
            or not 1 <= episode <= snapshot.through_episode):
        raise AuthorMemoryFinalAlignmentError('전수 대조한 회차를 직접 선택하세요.')
    require_current_author_memory_final_alignment(snapshot, store, project_id)
    directory, memories, saved, stamp = _read_state(
        store, project_id, snapshot.folder, snapshot.through_episode)
    if stamp != snapshot.source_sha256 or directory != snapshot.folder:
        raise AuthorMemoryFinalAlignmentError('기억 원장 또는 원고가 변경됐습니다.')
    current = saved.get(episode)
    if current is None or not current.final_text.strip():
        raise AuthorMemoryFinalAlignmentError('선택한 회차의 저장 최종본이 없습니다.')
    final = current.final_text
    rows = []
    for memory in memories:
        if not memory.valid_from <= episode <= memory.valid_through:
            continue
        source = saved.get(memory.source_episode)
        source_current = bool(
            source is not None
            and source.revision == memory.source_revision
            and source.final_text.strip()
            and sha256(source.final_text.encode('utf-8')).hexdigest()
                == memory.source_sha256)
        rows.append(AuthorMemoryEpisodeEvidenceRow(
            category=memory.category,
            subject=memory.subject, change=memory.change,
            source_episode=memory.source_episode,
            source_revision=memory.source_revision,
            source_current=source_current,
            subject_present=bool(source_current and memory.subject in final),
            change_present=bool(source_current and memory.change in final),
        ))
    if _read_state(store, project_id, directory, snapshot.through_episode)[3] != stamp:
        raise AuthorMemoryFinalAlignmentError('조회 중 기억 원장 또는 원고가 변경됐습니다.')
    return AuthorMemoryEpisodeEvidence(
        episode=episode, revision=current.revision,
        final_sha256=sha256(final.encode('utf-8')).hexdigest(),
        final_text=final, memories=tuple(rows),
    )
