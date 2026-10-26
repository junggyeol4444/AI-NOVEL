"""Rewrite only a passage explicitly selected by the author in a saved draft.

This is a real offline local-GGUF request, not a test fixture or deterministic
rewrite. It preserves every character OUTSIDE the selected span, including
chapters too long for the existing whole-draft rewrite's 12k input limit.
No SQLite write, final-text update, quality certification or publication.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from .database.episodes import EpisodeStore
from .database.characters import CharacterStore
from .local_models import (
    LocalExecutableProvider, LocalModelError, SceneDraftRequest, draft_scene,
)
from .local_rewrite_canon_bridge import (
    SavedRewriteCanon, build_saved_rewrite_canon,
)
from .local_rewrite_comparison import (
    RewriteCandidateEvidence, compare_actual_rewrite,
)
from .manual_rewrite_workspace import (
    RewriteLease, ManualRewritePreview, begin_manual_rewrite,
    preview_manual_rewrite, require_current_manual_rewrite_preview,
)


class SelectedRewriteError(ValueError):
    """Never echo author manuscript, executable arguments or private paths."""


@dataclass(frozen=True)
class SelectedRewriteProposal:
    lease: RewriteLease
    selected_start: int
    selected_end: int
    selected_original_sha256: str
    proposed_text: str = field(repr=False)
    preview: ManualRewritePreview = field(repr=False)
    numeric_evidence: RewriteCandidateEvidence = field(repr=False)
    saved_canon: SavedRewriteCanon = field(repr=False)
    actual_model_calls: int = 1
    status: str = 'LOCAL_GGUF_SELECTED_PASSAGE_UNREVIEWED'
    sqlite_saved: bool = False
    final_manuscript_changed: bool = False
    publication_approved: bool = False


def propose_selected_rewrite(
    database_path: str | Path, project_id: str, episode: int,
    provider: LocalExecutableProvider, *,
    expected_lease: RewriteLease,
    selection_start: int, selection_end: int,
    explicit_author_model_run: bool,
    author_direction: str = '',
) -> SelectedRewriteProposal:
    """Return an unsaved full draft with ONLY the selected passage replaced.

    Indices are Python Unicode codepoint offsets into the EXACT saved draft.
    Qt UTF-16 cursor indices must be converted by the GUI before this call.
    This path deliberately refuses edited/unsaved drafts and any existing
    final text, and keeps the original SQLite completely unchanged.
    """
    if (explicit_author_model_run is not True
            or type(provider) is not LocalExecutableProvider
            or type(expected_lease) is not RewriteLease
            or type(project_id) is not str
            or project_id != expected_lease.project_id
            or type(episode) is not int
            or episode != expected_lease.episode
            or not 1 <= episode <= 1000
            or type(selection_start) is not int
            or type(selection_end) is not int
            or selection_start < 0 or selection_end <= selection_start
            or type(author_direction) is not str
            or len(author_direction) > 2000 or '\x00' in author_direction
            or any(ord(ch) < 32 and ch not in '\n\r\t'
                   for ch in author_direction)):
        raise SelectedRewriteError(
            '현재 저장 초고의 선택 구간과 이번 1회 로컬 모델 승인이 필요합니다.')
    path = Path(database_path)
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise SelectedRewriteError('기존 작가 로컬 SQLite 파일만 사용할 수 있습니다.')
    with EpisodeStore(path) as store:
        lease, original = begin_manual_rewrite(store, project_id, episode)
        if lease != expected_lease:
            raise SelectedRewriteError(
                '작가 저장 원고가 바뀌어 선택 구간을 재확인해야 합니다.')
        row = store.get_episode(project_id, episode)
        if row.final_text.strip():
            raise SelectedRewriteError(
                '이미 저장된 최종 원고가 있어 AI가 덮어쓸 수 없습니다.')
        if selection_end > len(original) or len(original) > 100000:
            raise SelectedRewriteError(
                '선택 구간이 저장 원고 범위 또는 장편 비교 한도를 벗어났습니다.')
        selected = original[selection_start:selection_end]
        if not selected.strip() or not 100 <= len(selected) <= 6000:
            raise SelectedRewriteError(
                '실제 저장 원고에서 100~6000자 구간을 직접 선택하세요.')
        # The author selected this exact substring; there is no silent
        # extraction of other manuscript passages for the rewrite target.
        before = original[max(0, selection_start - 700):selection_start]
        after = original[selection_end:selection_end + 700]
        canon = build_saved_rewrite_canon(store, path, project_id, episode)
        with CharacterStore(path) as chars:
            people = chars.list_characters(project_id)
        focused = tuple(p.name for p in people
                        if p.name in selected or p.name in before or p.name in after)
        cast = focused[:20] or tuple(p.name for p in people[:8])
        if not cast:
            cast = ('작가가 저장한 원고 등장인물',)
        plot = row.plot or ''
        if len(plot) > 1800:
            plot = plot[:880] + '\n[저장 플롯 중간 발췌 생략]\n' + plot[-880:]
        direction = ('\n[작가가 이번 1회 직접 지정한 수정 방향]\n'
                     + author_direction if author_direction.strip() else '')
        prompt = (
            '[실제 저장 초고에서 작가가 선택한 교체 대상 원문 전체]\n'
            + selected
            + '\n[선택 구간 원문 끝]\n'
            + '[선택 구간 직전 저장 원고 문맥 - 수정하지 말 것]\n'
            + before
            + '\n[선택 구간 직후 저장 원고 문맥 - 수정하지 말 것]\n'
            + after
            + '\n[현재 저장 회차 플롯 발췌]\n' + plot
            + '\n' + canon.text + direction
            + '\n[교체 구간만 새로 작성. 구간 밖 원문은 그대로 유지. '
              '이전/다음 문맥을 출력에 반복하지 말 것.]')
        if len(prompt) > 20000:
            raise SelectedRewriteError(
                '작가 선택 구간과 저장 설정이 모델 문맥 한도를 넘습니다.')
        goal = (
            f'목표 분량 {max(100, len("".join(selected.split())))}자. '
            '작가가 선택한 구간만 같은 장면·시점·인과·인물 말투로 '
            '한국어 소설 본문으로 다시 써라. 원고 앞뒤는 출력하지 말고 '
            '교체 구간의 새 본문만 출력. 편집 설명·QC 합격 주장 금지.'
        )
        request = SceneDraftRequest(
            project_id, episode, 1, prompt, goal,
            '현재 선택 구간의 저장된 사건과 앞뒤 연속성 유지',
            '작가가 저장한 현재 장면의 장소',
            cast, target_chars=max(100, len(''.join(selected.split()))),
        )
        try:
            replacement = draft_scene(request, provider).draft
        except LocalModelError:
            raise SelectedRewriteError(
                '승인된 로컬 모델이 선택 구간 수정 후보를 생성하지 못했습니다.') from None
        if (type(replacement) is not str or not replacement.strip()
                or replacement == selected):
            raise SelectedRewriteError(
                '기존 선택 구간과 다른 실제 수정 후보가 없어 원문을 유지했습니다.')
        # Critical invariant: not one byte outside the author's selection
        # is model-rewritten, even when the full chapter exceeds 12k chars.
        combined = original[:selection_start] + replacement + original[selection_end:]
        try:
            preview = preview_manual_rewrite(store, lease, combined)
            require_current_manual_rewrite_preview(
                preview, store, lease, combined)
            evidence = compare_actual_rewrite(
                store, project_id, episode, original, combined)
        except (ValueError, OSError, UnicodeError):
            raise SelectedRewriteError(
                '원본 변경 또는 저장 가능한 분량 초과로 AI 후보를 폐기했습니다.') from None
        if evidence.source_revision != lease.revision:
            raise SelectedRewriteError(
                '원고 버전이 변경되어 선택 구간 후보를 폐기했습니다.')
        # SQLite is still untouched; author must compare and click Save.
        return SelectedRewriteProposal(
            lease, selection_start, selection_end,
            sha256(selected.encode('utf-8')).hexdigest(),
            combined, preview, evidence, canon)
