"""Human-directed draft rewrite workspace for the existing episode store.

A proposed rewrite lives only in memory until the author explicitly commits
it as a *draft*. It NEVER replaces a final manuscript or approves publishing.
"""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from .database.episodes import EpisodeStore


class ManualRewriteError(ValueError):
    pass


@dataclass(frozen=True)
class RewriteLease:
    project_id: str
    episode: int
    revision: int
    original_draft_sha256: str
    final_sha256: str
    project_revision: int
    publication_approved: bool = False


def begin_manual_rewrite(store: EpisodeStore, project_id: str, episode: int) -> tuple[RewriteLease, str]:
    if not isinstance(store, EpisodeStore) or type(episode) is not int or not 1 <= episode <= 1_000_000:
        raise ManualRewriteError('기존 작품과 회차를 선택해야 합니다.')
    row = store.get_episode(project_id, episode)
    if not row.draft.strip():
        raise ManualRewriteError('수정할 저장 초고가 없습니다.')
    lease = RewriteLease(project_id, episode, row.revision,
        sha256(row.draft.encode('utf-8')).hexdigest(),
        sha256(row.final_text.encode('utf-8')).hexdigest(),
        store.get_project(project_id).revision)
    return lease, row.draft


def commit_manual_rewrite(store: EpisodeStore, lease: RewriteLease,
                          revised_draft: str, *, explicit_author_save: bool) -> int:
    if (not isinstance(store, EpisodeStore) or type(lease) is not RewriteLease
            or explicit_author_save is not True or type(revised_draft) is not str
            or not revised_draft.strip()):
        raise ManualRewriteError('작가가 수정한 초고의 명시적 저장 승인이 필요합니다.')
    row = store.get_episode(lease.project_id, lease.episode)
    if (row.revision != lease.revision
            or store.get_project(lease.project_id).revision != lease.project_revision
            or sha256(row.draft.encode('utf-8')).hexdigest() != lease.original_draft_sha256
            or sha256(row.final_text.encode('utf-8')).hexdigest() != lease.final_sha256):
        raise ManualRewriteError('다른 저장 작업으로 원고가 바뀌었습니다. 다시 열어 주세요.')
    if revised_draft == row.draft:
        raise ManualRewriteError('수정 내용이 없어 기존 초고를 유지합니다.')
    saved = store.update_episode(lease.project_id, lease.episode,
                                expected_revision=lease.revision, draft=revised_draft)
    # Any old QC records are now stale by episode revision; never promote them.
    return saved.revision
