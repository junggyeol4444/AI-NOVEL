"""Read-only evidence-bound memory deltas, from prior saved final chapters.

No auto summarizer, no quality clearance, no implied manuscript or model consent.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from .database.episodes import EpisodeStore
from .author_memory_delta import (AuthorMemoryDeltaError, list_author_memory_deltas,
                                  memory_delta_fingerprint)


@dataclass(frozen=True)
class AuthorMemoryContext:
    episode: int
    content: str = field(repr=False)
    included: int = 0
    stale: int = 0
    retracted: int = 0
    ledger_sha256: str = ''
    quality_certified: bool = False
    publication_approved: bool = False


@dataclass(frozen=True)
class MemoryScopeRow:
    episode: int
    status: str
    item_count: int


def build_author_memory_context(store: EpisodeStore, project_id: str, *,
                                folder: str | Path, episode: int,
                                expected_ledger_sha256: str = '',
                                max_chars: int = 4200) -> AuthorMemoryContext:
    if (not isinstance(store, EpisodeStore) or type(episode) is not int
            or not 1 <= episode <= 1000 or type(max_chars) is not int
            or not 300 <= max_chars <= 7000):
        raise AuthorMemoryDeltaError('작가 기억 문맥 범위를 다시 선택해야 합니다.')
    store.get_project(project_id)
    stamp = memory_delta_fingerprint(folder)
    if expected_ledger_sha256 and stamp != expected_ledger_sha256:
        raise AuthorMemoryDeltaError('기억 변화 기록이 바뀌어 이번 사용 승인이 무효화되었습니다.')
    saved = {e.episode: e for e in store.list_episodes(project_id)}
    active = []
    stale = revoked = 0
    for item in list_author_memory_deltas(folder, project_id):
        if item.retracted:
            revoked += 1
            continue
        if not item.valid_from <= episode <= item.valid_through:
            continue
        source = saved.get(item.source_episode)
        if (source is None or source.episode >= episode
                or source.revision != item.source_revision
                or not source.final_text.strip()
                or sha256(source.final_text.encode('utf-8')).hexdigest()
                   != item.source_sha256):
            stale += 1
            continue
        active.append(item)
    if stale:
        raise AuthorMemoryDeltaError('변경된 근거 회차가 있어 기억 문맥을 사용할 수 없습니다.')
    if not active:
        raise AuthorMemoryDeltaError('이 회차에 적용할 작가 검토 기억 변경 기록이 없습니다.')
    header = '[작가가 직접 기록한 과거 회차 기억 변화 / 자동 검증·출판 승인 아님]\n'
    lines = [header]
    total = len(header)
    for item in sorted(active, key=lambda x: (x.source_episode, x.delta_id)):
        line = (f'{item.category} | {item.subject}: {item.change} '
                f'(근거 {item.source_episode}화 / 적용 {item.valid_from}~{item.valid_through}화)\n')
        if total + len(line) > max_chars:
            raise AuthorMemoryDeltaError('작가 기억 문맥이 설정 한도를 초과했습니다. 임의로 축약하지 않습니다.')
        lines.append(line)
        total += len(line)
    if memory_delta_fingerprint(folder) != stamp:
        raise AuthorMemoryDeltaError('읽는 중 작가 기억 기록이 변경되었습니다.')
    return AuthorMemoryContext(episode, ''.join(lines), len(active), 0, revoked, stamp)


def plan_author_memory_scope(store: EpisodeStore, project_id: str, *,
                             folder: str | Path, through_episode: int,
                             expected_ledger_sha256: str = '') -> tuple[MemoryScopeRow, ...]:
    if type(through_episode) is not int or not 1 <= through_episode <= 1000:
        raise AuthorMemoryDeltaError('회차 계획 범위가 올바르지 않습니다.')
    stamp = memory_delta_fingerprint(folder)
    if expected_ledger_sha256 and stamp != expected_ledger_sha256:
        raise AuthorMemoryDeltaError('기억 기록 변경으로 범위 조회를 취소했습니다.')
    saved = {e.episode: e for e in store.list_episodes(project_id)}
    events = list_author_memory_deltas(folder, project_id)
    results = []
    for episode in range(1, through_episode + 1):
        if episode in saved:
            results.append(MemoryScopeRow(episode, 'EXISTING', 0))
            continue
        candidates = tuple(v for v in events if not v.retracted
                           and v.valid_from <= episode <= v.valid_through)
        if not candidates:
            results.append(MemoryScopeRow(episode, 'AUTHOR_MEMORY_MISSING', 0))
            continue
        current = all((v.source_episode in saved
                       and v.source_episode < episode
                       and saved[v.source_episode].revision == v.source_revision
                       and saved[v.source_episode].final_text.strip()
                       and sha256(saved[v.source_episode].final_text.encode('utf-8')).hexdigest()
                           == v.source_sha256) for v in candidates)
        results.append(MemoryScopeRow(episode, 'MEMORY_READY' if current
                                      else 'MEMORY_STALE', len(candidates)))
    if memory_delta_fingerprint(folder) != stamp:
        raise AuthorMemoryDeltaError('조회하는 동안 기록이 변경되었습니다.')
    return tuple(results)
