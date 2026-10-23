"""Time-bounded author fact context for an explicitly approved local writer.

This is NOT an automatic continuity quality test, approval or publication gate.
Conflicting or stale author facts are surfaced, never silently treated as true.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .database.episodes import EpisodeStore
from .author_fact_ledger import AuthorFactError, read_author_facts


@dataclass(frozen=True)
class AuthorFactContext:
    episode: int
    context: str
    included: int
    stale_source: int
    conflicting: int
    future_or_inactive: int
    retracted: int
    truncated: int
    quality_certified: bool = False
    publication_approved: bool = False


def build_author_fact_context(store: EpisodeStore, project_id: str, *,
                              next_episode: int, folder: str | Path,
                              max_chars: int = 1800) -> AuthorFactContext:
    if not isinstance(store, EpisodeStore) or type(project_id) is not str or not project_id:
        raise AuthorFactError('기존 작품 SQLite를 먼저 선택해야 합니다.')
    if type(next_episode) is not int or not 1 <= next_episode <= 1000:
        raise AuthorFactError('집필 회차 범위가 올바르지 않습니다.')
    if type(max_chars) is not int or not 300 <= max_chars <= 5000:
        raise AuthorFactError('작가 사실 문맥 길이 제한이 올바르지 않습니다.')
    store.get_project(project_id)
    saved = {e.episode: e for e in store.list_episodes(project_id)}
    active, stale, ignored, revoked = [], 0, 0, 0
    for fact in read_author_facts(folder, project_id):
        if fact.retracted:
            revoked += 1
            continue
        source = saved.get(fact.source_episode)
        if (source is None or not source.final_text.strip()
                or source.revision != fact.source_revision
                or sha256(source.final_text.encode('utf-8')).hexdigest()
                   != fact.source_sha256):
            stale += 1
            continue
        if (fact.source_episode >= next_episode
                or not fact.valid_from <= next_episode <= fact.valid_until):
            ignored += 1
            continue
        active.append(fact)
    keys: dict[tuple[str, str, str], set[str]] = {}
    for fact in active:
        key = (fact.kind, fact.subject.casefold(), fact.predicate.casefold())
        keys.setdefault(key, set()).add(fact.value)
    conflicts = sum(len(values) > 1 for values in keys.values())
    header = '작가가 직접 등록한 과거 저장 최종본 기반 구조화 사실 (자동 검수 아님):\n'
    lines = []
    used = len(header)
    truncated = 0
    included = 0
    for fact in sorted(active, key=lambda f: (f.source_episode, f.fact_id)):
        line = (f'{fact.kind} | {fact.subject} | {fact.predicate}: {fact.value} '
                f'(근거 {fact.source_episode}화, 유효 {fact.valid_from}~{fact.valid_until}화)\n')
        if used + len(line) > max_chars:
            truncated += 1
            continue
        lines.append(line)
        included += 1
        used += len(line)
    if truncated:
        # Do not misrepresent a truncated set as complete continuity coverage.
        warning = f'\n[문맥 길이 제한으로 구조화 사실 {truncated}건 미포함]'
        if used + len(warning) <= max_chars:
            lines.append(warning)
    context = header + ''.join(lines) if lines else ''
    return AuthorFactContext(next_episode, context, included, stale,
                             conflicts, ignored, revoked, truncated)
