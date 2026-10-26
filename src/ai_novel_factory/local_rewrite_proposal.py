"""Local GGUF proposal for revising ACTUALLY saved manuscript drafts.

The model is called only on explicit author request. Its response is
ephemeral, not saved SQLite prose and NOT a reviewed final manuscript.
Real, current-revision QC outcome categories (never untrusted check
notes) can guide the proposal without claiming incomplete tests passed.
The already-existing ManualRewriteLease/diff/save pathway remains the
only way the author can explicitly save an edited draft.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .database.episodes import EpisodeStore
from .database.characters import CharacterStore
from .local_models import (
    LocalExecutableProvider, LocalModelError, SceneDraftRequest, draft_scene,
)
from .local_rewrite_continuation import (
    RewriteContinuationResult, continue_actual_rewrite,
)
from .local_rewrite_comparison import (
    RewriteCandidateEvidence, compare_actual_rewrite,
)
from .manual_rewrite_workspace import (
    RewriteLease, ManualRewritePreview, begin_manual_rewrite,
    preview_manual_rewrite, require_current_manual_rewrite_preview,
)


class LocalRewriteProposalError(ValueError):
    """Sanitized: no manuscript, model arguments, or filesystem paths."""


@dataclass(frozen=True)
class LocalRewriteProposal:
    lease: RewriteLease
    proposed_text: str = field(repr=False)
    preview: ManualRewritePreview = field(repr=False)
    source_qc_findings: tuple[str, ...] = ()
    numeric_evidence: RewriteCandidateEvidence = field(repr=False, default=None)
    continuation: RewriteContinuationResult = field(repr=False, default=None)
    author_direction_applied: bool = False
    status: str = 'LOCAL_AI_UNREVIEWED_DRAFT_PROPOSAL'
    sqlite_saved: bool = False
    literary_quality_approved: bool = False
    publication_approved: bool = False


def propose_rewrite_of_saved_draft(
    database_path: str | Path, project_id: str, episode: int,
    provider: LocalExecutableProvider, *,
    expected_lease: RewriteLease,
    explicit_author_model_run: bool,
    author_direction: str = '',
) -> LocalRewriteProposal:
    """One model call, with full saved draft and content-revision lease.

    Never accepts network adapters, silently excerpts author draft, writes
    SQLite, saves a final manuscript, or approves literature/publication.
    A changed original or other saved author state invalidates the proposal.
    """
    if (explicit_author_model_run is not True
            or type(provider) is not LocalExecutableProvider
            or type(expected_lease) is not RewriteLease
            or type(project_id) is not str
            or project_id != expected_lease.project_id
            or type(episode) is not int or episode != expected_lease.episode
            or not 1 <= episode <= 1000
            or type(author_direction) is not str
            or len(author_direction) > 2000
            or '\x00' in author_direction
            or any(ord(ch) < 32 and ch not in '\n\r\t'
                   for ch in author_direction)):
        raise LocalRewriteProposalError('원고·로컬 실행 파일의 이번 1회 별도 승인이 필요합니다.')
    path = Path(database_path)
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise LocalRewriteProposalError('기존 로컬 SQLite 저장 파일을 직접 선택하세요.')

    with EpisodeStore(path) as store:
        lease, original = begin_manual_rewrite(store, project_id, episode)
        if lease != expected_lease:
            raise LocalRewriteProposalError('승인 후 저장 원고가 변경됐습니다. 다시 불러오세요.')
        row = store.get_episode(project_id, episode)
        if row.final_text.strip():
            raise LocalRewriteProposalError(
                '이미 저장된 최종본이 있습니다. AI가 기존 최종본을 대체하지 않습니다.')
        if len(original) > 12000:
            raise LocalRewriteProposalError(
                '한 회차 초고가 모델의 안전한 전체 입력 범위를 초과했습니다. '
                '원문 일부를 임의 누락한 재작성은 하지 않습니다.')
        if not original.strip():
            raise LocalRewriteProposalError('저장된 초고를 먼저 선택하세요.')

        # Current-revision findings only. An old QC PASS / stale annotation
        # never tells a new model that an edited draft is already verified.
        categories = ('length', 'repetition', 'korean_format',
                      'cross_episode_sentence_reuse', 'continuity', 'logic',
                      'timeline', 'foreshadowing', 'reader_simulation',
                      'reference_similarity', 'style_scope')
        recorded = {}
        for check in store.list_checks(project_id, episode):
            if check.category in categories and check.content_revision == row.revision:
                recorded[check.category] = check.outcome
        flagged = tuple(
            f'{name}:{recorded[name]}' for name in categories
            if recorded.get(name) in ('WARN', 'FAIL', 'NOT_RUN'))
        missing = tuple(name for name in categories if name not in recorded)
        # The author owns the manuscript and the approved GGUF. None of the
        # reference novels' source passages are fed into this model call.
        plot = row.plot or ''
        if len(plot) > 6500:
            raise LocalRewriteProposalError(
                '저장된 회차 플롯이 재작성 문맥 한도를 넘습니다. 임의 절단하지 않습니다.')
        with CharacterStore(path) as chars:
            people = chars.list_characters(project_id)
        cast = tuple(person.name for person in people
                     if person.name and person.name in original)
        if not cast:
            cast = tuple(person.name for person in people[:8])
        if not cast:
            cast = ('작가가 저장한 원문 등장인물',)
        if len(cast) > 40:
            raise LocalRewriteProposalError(
                '원고의 등장인물이 많아 단일 모델 요청에 담을 수 없습니다.')
        check_note = ('실제 저장 현재 revision의 검토 필요 검사 종류: '
                      + (', '.join(flagged) if flagged else '기록 없음')
                      + '\n이번 revision에 누락된 검사: '
                      + (', '.join(missing) if missing else '표시 없음')
                      + '\n검사 누락은 합격을 의미하지 않음. '
                      '추측한 참고작 문장/미래 사건/가짜 인물 사실 생성 금지.')
        source = (
            f'[기존 {episode}화 미검수 저장 초고 — 내용 전체 / '
            '회차 수정 제안에만 이용, 원문 보존]\n'
            + original + '\n[초고 끝]\n'
            + (('[작가 저장 회차 플롯 원문]\n' + plot + '\n')
               if plot.strip() else '')
            + check_note
            + ('\n[작가가 이번 재작성에 직접 입력한 수정 방향]\n'
               + author_direction + '\n' if author_direction.strip() else ''))
        if len(source) > 24500:
            raise LocalRewriteProposalError('초고·플롯 전체가 모델 입력 제한을 초과했습니다.')
        scene_goal = (
            f'목표 분량 {min(99999,max(100,len("".join(original.split()))))}자 '
            '정도의 독창적인 한국어 소설 본문만 새로 써라. '
            '위 원본 초고와 작가 회차 플롯의 사건·인물·시점·인과를 '
            '보존하면서 문제 표현과 중복을 교정하는 미검수 수정 후보를 '
            '작성하라. 설명·표지·검사 통과 주장·편집 노트 금지. '
            '원본 내용을 임의로 생략/요약하지 말 것.'
            + ('\n작가 직접 수정 방향: ' + author_direction.strip()[:1000]
               if author_direction.strip() else ''))
        request = SceneDraftRequest(
            project_id, episode, 1, source,
            scene_goal, '저장된 원문과 실제 검토 필요 검사만 적용. '
                        '검사 누락·작가 지시를 합격 또는 사실로 날조하지 말 것.',
            '기존 초고와 동일한 장소·시계열 유지',
            cast, target_chars=min(99999, max(100, len(''.join(original.split())))))
        try:
            proposed = draft_scene(request, provider).draft
        except LocalModelError:
            raise LocalRewriteProposalError(
                '로컬 모델 재작성에 실패했습니다. 원본·최종본은 유지됩니다.') from None
        if type(proposed) is not str or not proposed.strip() or proposed == original:
            raise LocalRewriteProposalError(
                '새로운 수정 후보를 받지 못했습니다. 기존 원고는 유지됩니다.')
        # One explicitly approved revision session: up to three further
        # ACTUAL native calls if 5k-ish chapter prose is still underfilled.
        # Every accepted byte is model-written, never padded or published.
        try:
            expanded = continue_actual_rewrite(
                provider, first_candidate=proposed, source_context=source,
                project_id=project_id, episode=episode, characters=cast,
                target_nonspace_chars=min(
                    20000, max(100, len(''.join(original.split())))),
                author_direction=author_direction, max_extra_calls=3)
            proposed = expanded.text
        except (ValueError, OSError, UnicodeError):
            raise LocalRewriteProposalError(
                '실제 모델 이어쓰기 문맥 생성에 실패했습니다. '
                '원본과 최종본은 변경되지 않았습니다.') from None
        # The original saved row, project and checks can change while the
        # trusted offline process runs. Do not present a stale result as current.
        try:
            preview = preview_manual_rewrite(store, lease, proposed)
            require_current_manual_rewrite_preview(preview, store, lease, proposed)
        except (ValueError, OSError, UnicodeError):
            raise LocalRewriteProposalError(
                '모델 실행 중 저장 원고가 변경됐습니다. 후보를 폐기했습니다.') from None
        # Compare the original and GGUF candidate against the SAME saved
        # previous 250 chapters. This never confers review/QC/approval.
        try:
            evidence = compare_actual_rewrite(
                store, project_id, episode, original, proposed)
        except (ValueError, OSError, UnicodeError):
            raise LocalRewriteProposalError(
                '수정 후보의 실제 저장 회차 비교가 완료되지 않았습니다. '
                '초고와 최종본은 그대로 유지됩니다.') from None
        if evidence.source_revision != lease.revision:
            raise LocalRewriteProposalError(
                '비교 중 원고가 변경되어 후보를 폐기했습니다.')
        return LocalRewriteProposal(
            lease, proposed, preview, flagged, evidence,
            expanded, bool(author_direction.strip()))
