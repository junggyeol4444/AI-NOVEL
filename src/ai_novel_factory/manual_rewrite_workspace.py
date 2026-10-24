"""Human-directed draft rewrite workspace for the existing episode store.

A proposed rewrite lives only in memory until the author explicitly commits
it as a *draft*. It NEVER replaces a final manuscript or approves publishing.
"""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from difflib import SequenceMatcher
from .database.episodes import EpisodeStore, MAX_FIELD_BYTES


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


@dataclass(frozen=True)
class ManualRewritePreview:
    """작가가 직접 수정한 초고의 저장 전 차이 기록. 검수·출판 승인이 아님."""
    lease: RewriteLease
    proposed_sha256: str
    before_characters: int
    after_characters: int
    changed_blocks: tuple[tuple[str, int, int, int, int], ...]
    details_available: bool
    publication_approved: bool = False


def preview_manual_rewrite(store: EpisodeStore, lease: RewriteLease,
                           revised_draft: str) -> ManualRewritePreview:
    """현재 SQLite 초고와 미저장 편집 내용을 읽기 전용으로 비교한다."""
    if not isinstance(store, EpisodeStore) or type(lease) is not RewriteLease:
        raise ManualRewriteError('현재 저장 초고를 다시 불러오세요.')
    if type(revised_draft) is not str or not revised_draft.strip():
        raise ManualRewriteError('비교할 수정 초고를 먼저 입력하세요.')
    try:
        encoded = revised_draft.encode('utf-8')
    except UnicodeError:
        raise ManualRewriteError('초고의 문자 인코딩을 확인하세요.') from None
    if (len(encoded) > MAX_FIELD_BYTES['draft'] or '\x00' in revised_draft
            or any((ord(c) < 32 and c not in '\n\t\r') or ord(c) == 127
                   for c in revised_draft)):
        raise ManualRewriteError('저장 가능한 초고 형식 또는 크기를 초과했습니다.')
    current, original = begin_manual_rewrite(store, lease.project_id, lease.episode)
    if current != lease:
        raise ManualRewriteError('원고 또는 작품이 변경됐습니다. 다시 불러오세요.')
    if revised_draft == original:
        raise ManualRewriteError('변경된 초고가 없어 비교할 내용이 없습니다.')
    old_lines, new_lines = original.splitlines(keepends=True), revised_draft.splitlines(keepends=True)
    detailed = max(len(old_lines), len(new_lines)) <= 2000
    blocks = ()
    if detailed:
        blocks = tuple(
            (kind, start_old + 1, end_old, start_new + 1, end_new)
            for kind, start_old, end_old, start_new, end_new
            in SequenceMatcher(None, old_lines, new_lines, autojunk=True).get_opcodes()
            if kind != 'equal'
        )
    return ManualRewritePreview(
        lease=lease, proposed_sha256=sha256(encoded).hexdigest(),
        before_characters=len(original), after_characters=len(revised_draft),
        changed_blocks=blocks, details_available=detailed,
    )


def require_current_manual_rewrite_preview(
        snapshot: ManualRewritePreview, store: EpisodeStore,
        lease: RewriteLease, revised_draft: str) -> None:
    """비교 이후 입력·원고·작품 변경 시 이전 비교 결과를 폐기한다."""
    if type(snapshot) is not ManualRewritePreview or snapshot.lease != lease:
        raise ManualRewriteError('현재 수정 초고를 다시 비교하세요.')
    current = preview_manual_rewrite(store, lease, revised_draft)
    if current != snapshot:
        raise ManualRewriteError('수정 초고 또는 원본이 변경됐습니다. 다시 비교하세요.')


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
