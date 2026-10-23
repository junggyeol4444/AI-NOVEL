"""Bind explicit author arc beats to a single local drafting episode.

No auto-inference, QC certification, model launch, manuscript update or upload.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from .database.episodes import EpisodeStore
from .author_arc_ledger import (AuthorArcError, read_author_arcs,
                                canon_fingerprint, arc_ledger_fingerprint)


@dataclass(frozen=True)
class AuthorArcContext:
    episode: int
    context: str
    ledger_sha256: str
    arc_id: str | None
    stale_canon: bool
    scope_missing: bool
    publication_approved: bool = False
    quality_certified: bool = False


def build_author_arc_context(store: EpisodeStore, project_id: str, *,
                             next_episode: int, folder: str | Path,
                             expected_ledger_sha256: str | None = None,
                             max_context_chars: int = 2000) -> AuthorArcContext:
    if (type(next_episode) is not int or not 1 <= next_episode <= 1000
            or type(max_context_chars) is not int
            or not 800 <= max_context_chars <= 10000):
        raise AuthorArcError('집필 아크의 회차 또는 문맥 길이가 올바르지 않습니다.')
    stamp = arc_ledger_fingerprint(folder)
    if expected_ledger_sha256 is not None and stamp != expected_ledger_sha256:
        raise AuthorArcError('작가 아크 계획이 변경되었습니다. 새 실행 승인이 필요합니다.')
    selected = [a for a in read_author_arcs(folder, project_id)
                if not a.withdrawn and a.start <= next_episode <= a.end]
    if not selected:
        return AuthorArcContext(next_episode, '', stamp, None, False, True)
    if len(selected) != 1:
        raise AuthorArcError('집필 아크 범위가 중복되었습니다.')
    arc = selected[0]
    stale = arc.canon_sha256 != canon_fingerprint(store, project_id)
    if stale:
        return AuthorArcContext(next_episode, '', stamp, arc.arc_id, True, False)
    context = ('[작가가 직접 작성한 장편 아크 계획: 집필 참고용/미검수]\n'
        + f'해당 회차: {next_episode}화 / 아크 범위: {arc.start}~{arc.end}화\n'
        + '아크 제목: ' + arc.title + '\n'
        + '목표: ' + arc.objective + '\n'
        + '갈등: ' + arc.conflict + '\n'
        + '복선: ' + arc.foreshadow + '\n'
        + '해소 계획: ' + arc.resolution)
    if len(context) > max_context_chars:
        raise AuthorArcError('아크 계획이 승인된 문맥 길이를 초과했습니다. 임의 절단하지 않습니다.')
    return AuthorArcContext(next_episode, context, stamp, arc.arc_id, False, False)


def require_author_arc_for_model(context: AuthorArcContext) -> str:
    """Explicit opt-in must never silently ignore a stale/missing arc."""
    if not isinstance(context, AuthorArcContext) or context.stale_canon or context.scope_missing:
        raise AuthorArcError('해당 회차의 최신 작가 아크 계획이 없어 집필을 보류했습니다.')
    if not context.context:
        raise AuthorArcError('해당 아크의 집필 문맥을 확인할 수 없습니다.')
    return context.context
