"""Extend a real saved Korean chapter with actual author-approved local GGUF prose.

This is a missing long-form authoring operation: continue an underlength
SAVED chapter without rewriting any of its original characters. The author
chooses a chapter target and a bounded number of real model invocations.
Each invocation sees saved Novel Bible, prior/next actual chapters, the
current ending and previous accepted new paragraphs. All model-written
prose stays an UNREVIEWED in-memory proposal until separate manual Save.

No remote model, reference-novel prose, database writes, final text writes,
automatic QC approval, synthetic filler or publication side effects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .database.episodes import EpisodeStore, MAX_FIELD_BYTES
from .database.characters import CharacterStore
from .korean_draft_quality import (
    has_foreign_script_corruption, screen_korean_draft,
)
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


class DraftExpansionError(ValueError):
    """Never exposes private author prose, paths, or local model stderr."""


@dataclass(frozen=True)
class DraftExpansionProposal:
    lease: RewriteLease
    proposed_text: str = field(repr=False)
    preview: ManualRewritePreview = field(repr=False)
    numeric_evidence: RewriteCandidateEvidence = field(repr=False)
    saved_canon: SavedRewriteCanon = field(repr=False)
    requested_target_nonspace_chars: int = 5000
    actual_model_calls: int = 0
    accepted_new_passages: int = 0
    resulting_nonspace_chars: int = 0
    remaining_nonspace_chars: int = 0
    stopped_by_author: bool = False
    status: str = 'UNREVIEWED_APPEND_ONLY_GGUF_DRAFT'
    sqlite_saved: bool = False
    final_manuscript_changed: bool = False
    publication_approved: bool = False


def propose_saved_draft_expansion(
    database_path: str | Path, project_id: str, episode: int,
    provider: LocalExecutableProvider, *,
    expected_lease: RewriteLease,
    target_nonspace_chars: int,
    max_model_calls: int = 8,
    explicit_author_model_run: bool,
    author_direction: str = '',
    should_stop: Callable[[], bool] | None = None,
) -> DraftExpansionProposal:
    """Append only genuinely generated paragraphs to the EXACT saved draft.

    No change to the original prefix, including its line endings and spaces.
    Stops between blocking model invocations. An early stop with some accepted
    text yields an UNSAVED partial candidate, never a QC PASS or silent save.
    """
    if (explicit_author_model_run is not True
            or type(provider) is not LocalExecutableProvider
            or type(expected_lease) is not RewriteLease
            or type(project_id) is not str
            or project_id != expected_lease.project_id
            or type(episode) is not int
            or episode != expected_lease.episode
            or not 1 <= episode <= 1000
            or type(target_nonspace_chars) is not int
            or not 1000 <= target_nonspace_chars <= 50000
            or type(max_model_calls) is not int
            or not 1 <= max_model_calls <= 12
            or type(author_direction) is not str
            or len(author_direction) > 2000 or '\x00' in author_direction
            or any(ord(ch) < 32 and ch not in '\n\r\t'
                   for ch in author_direction)
            or (should_stop is not None and not callable(should_stop))):
        raise DraftExpansionError(
            '현재 저장 초고와 목표 분량·모델 호출 횟수에 대한 별도 승인이 필요합니다.')
    path = Path(database_path)
    if (not path.is_absolute() or not path.is_file()
            or path.is_symlink()):
        raise DraftExpansionError('기존 작가의 로컬 SQLite만 선택할 수 있습니다.')

    with EpisodeStore(path) as store:
        lease, original = begin_manual_rewrite(store, project_id, episode)
        if lease != expected_lease:
            raise DraftExpansionError('저장 초고가 변경되었습니다. 다시 불러오세요.')
        row = store.get_episode(project_id, episode)
        if row.final_text.strip():
            raise DraftExpansionError('이미 저장된 최종 원고는 AI로 대체하지 않습니다.')
        if len(original) > 100000:
            raise DraftExpansionError('저장된 회차가 현재 장편 문맥 한도를 넘습니다.')
        original_count = screen_korean_draft(
            original, target_chars=target_nonspace_chars).nonspace_chars
        if original_count >= target_nonspace_chars:
            raise DraftExpansionError('저장 원고가 이미 지정한 분량에 도달했습니다.')

        canon = build_saved_rewrite_canon(
            store, path, project_id, episode)
        with CharacterStore(path) as characters:
            people = characters.list_characters(project_id)
        # Only character names that appear in the actual saved prose/plot
        # are selected, without leaking character secrets into a blind POV.
        selected_names = tuple(
            person.name for person in people
            if person.name in original[-5000:] or person.name in row.plot)
        cast = selected_names[:16] or tuple(p.name for p in people[:8])
        if not cast:
            cast = ('작가가 저장한 현재 회차의 등장인물',)

        plot = row.plot or ''
        if len(plot) > 1800:
            plot = (plot[:850] + '\n[작가 저장 플롯 중간 생략]\n'
                    + plot[-850:])
        new_parts: list[str] = []
        current = original
        calls = 0
        stopped = False
        for call_number in range(1, max_model_calls + 1):
            if should_stop is not None and should_stop():
                stopped = True
                break
            count = screen_korean_draft(
                current, target_chars=target_nonspace_chars).nonspace_chars
            remaining = target_nonspace_chars - count
            if remaining <= 0:
                break
            # Keep the actual last paragraphs and the newly generated
            # passage boundary. The model must NOT repeat those paragraphs.
            latest = current[-2400:]
            earlier = (original[:700] if len(original) > 3500 else '')
            previous = (new_parts[-1][-900:] if new_parts else '')
            prompt = (
                '[작가가 실제 저장한 Novel Bible 및 회차 연결 자료]\n'
                + canon.text
                + '\n[현재 저장 회차의 실제 플롯 발췌]\n' + plot
                + '\n[기존 회차의 실제 첫 부분 — 다시 출력 금지]\n'
                + earlier
                + '\n[지금까지의 실제 원고 마지막 부분 — 바로 다음 문장부터]\n'
                + latest
                + '\n[직전 모델이 새로 쓴 부분의 끝 — 중복 금지]\n'
                + previous
                + ('\n[작가가 이번 실행에 직접 지정한 집필 방향]\n'
                   + author_direction if author_direction.strip() else '')
                + '\n[기존 원고·작가 설정을 보존하며 다음 사건만 이어쓰기. '
                  '기존 문장 재출력, 요약, 제목, 검수 주장 금지.]')
            if len(prompt) > 24000:
                raise DraftExpansionError(
                    '실제 저장 원고 문맥이 로컬 모델의 안전한 입력 범위를 넘습니다.')
            requested = min(10000, max(100, remaining))
            request = SceneDraftRequest(
                project_id, episode, call_number, prompt,
                f'목표 분량 {requested}자. 실제 저장 원고 바로 뒤에 붙일 '
                '새로운 독창적인 한국어 소설 본문만 작성하라. '
                '현재 인물의 시점·시간선·말투·인과를 유지하고 '
                '이미 작성된 문장은 절대 다시 출력하지 말 것.',
                '앞 사건의 결과를 다음 행동·갈등으로 자연스럽게 연결',
                '현재 저장된 회차 플롯의 장소와 시간',
                cast, target_chars=requested,
            )
            try:
                part = draft_scene(request, provider).draft
            except LocalModelError:
                if not new_parts:
                    raise DraftExpansionError(
                        '승인한 로컬 GGUF가 실제 이어쓰기 본문을 생성하지 못했습니다.'
                    ) from None
                break
            calls += 1
            if (type(part) is not str or not part.strip()
                    or has_foreign_script_corruption(part)
                    or len(part) > 30000):
                break
            part = part.strip()
            # Reject verbatim echo of the original ending, not merely a
            # numeric length increase from repeating an existing paragraph.
            if (part in current[-6000:]
                    or (len(current.strip()) >= 120
                        and current.strip()[-120:] in part[:500])
                    or any(part == older for older in new_parts)):
                break
            candidate = current + '\n\n' + part
            if (len(candidate) > 100000
                    or len(candidate.encode('utf-8')) > MAX_FIELD_BYTES['draft']):
                break
            candidate_count = screen_korean_draft(
                candidate, target_chars=target_nonspace_chars).nonspace_chars
            if candidate_count <= count:
                break
            current = candidate
            new_parts.append(part)

        if not new_parts:
            raise DraftExpansionError(
                '원문에 추가할 실제 새 소설 본문이 없어 원고를 유지했습니다.')
        # Invariant: no existing author-written character may be removed,
        # replaced, reordered or normalized by this append-only operation.
        if not current.startswith(original):
            raise DraftExpansionError('원문 보존을 확인하지 못했습니다.')
        try:
            preview = preview_manual_rewrite(store, lease, current)
            require_current_manual_rewrite_preview(
                preview, store, lease, current)
            evidence = compare_actual_rewrite(
                store, project_id, episode, original, current,
                target_chars=target_nonspace_chars)
        except (ValueError, OSError, UnicodeError):
            raise DraftExpansionError(
                '원본 변경 또는 저장 가능한 분량 초과로 수정 후보를 폐기했습니다.'
            ) from None
        # Never writes the candidate, approves a final text, or changes QC.
        final_count = screen_korean_draft(
            current, target_chars=target_nonspace_chars).nonspace_chars
        return DraftExpansionProposal(
            lease, current, preview, evidence, canon,
            target_nonspace_chars, calls, len(new_parts), final_count,
            max(0, target_nonspace_chars - final_count), stopped)
