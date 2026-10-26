"""Bounded actual local-GGUF continuation of an unreviewed rewrite proposal.

The author approves one revision session, including at most three additional
native calls if the original saved chapter's real Korean prose length is not
reached. A short draft remains explicitly short. Never insert synthetic
template paragraphs, rewrite SQLite, or mark prose as literary-reviewed.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from .episode_crosscheck import screen_cross_episode_reuse
from .korean_draft_quality import screen_korean_draft, has_foreign_script_corruption
from .local_models import LocalExecutableProvider, LocalModelError, SceneDraftRequest, draft_scene


class RewriteContinuationError(ValueError):
    """Sanitized local candidate error."""


@dataclass(frozen=True)
class RewriteContinuationResult:
    text: str = field(repr=False)
    target_nonspace_chars: int = 0
    actual_nonspace_chars: int = 0
    remaining_nonspace_chars: int = 0
    total_model_calls: int = 1
    stop_reason: str = 'TARGET_MET'
    reviewed: bool = False
    publication_approved: bool = False


def continue_actual_rewrite(
    provider: LocalExecutableProvider, *,
    first_candidate: str, source_context: str, project_id: str,
    episode: int, characters: tuple[str, ...],
    target_nonspace_chars: int, author_direction: str = '',
    max_extra_calls: int = 3,
) -> RewriteContinuationResult:
    """Continue only from real generated draft endings, using same provider."""
    if (type(provider) is not LocalExecutableProvider
            or type(first_candidate) is not str or not first_candidate.strip()
            or len(first_candidate) > 100_000
            or type(source_context) is not str or not source_context.strip()
            or len(source_context) > 25_000
            or type(project_id) is not str or not project_id
            or type(episode) is not int or not 1 <= episode <= 1000
            or type(characters) is not tuple or not characters
            or any(type(name) is not str or not name for name in characters)
            or type(target_nonspace_chars) is not int
            or not 100 <= target_nonspace_chars <= 20_000
            or type(author_direction) is not str or len(author_direction) > 2000
            or type(max_extra_calls) is not int or not 0 <= max_extra_calls <= 3):
        raise RewriteContinuationError('로컬 초고 재작성 연결 범위가 올바르지 않습니다.')
    candidate = first_candidate.strip()
    calls = 1
    stopped = 'TARGET_MET'
    for _ in range(max_extra_calls):
        current = screen_korean_draft(candidate, target_chars=target_nonspace_chars)
        deficit = target_nonspace_chars - current.nonspace_chars
        if deficit <= 0:
            break
        if has_foreign_script_corruption(candidate):
            stopped = 'SCRIPT_REVIEW_REQUIRED'
            break
        if len(candidate) >= 97_000:
            stopped = 'DRAFT_SIZE_LIMIT'
            break
        source = (source_context
                  + '\n[지금까지 실제 생성된 미검수 AI 재작성 후보 말미]\n'
                  + candidate[-1500:]
                  + '\n[같은 사건의 다음 문장에서 이어 작성; 원문 반복 금지]')
        needed = min(10_000, max(100, deficit))
        goal = (
            f'목표 분량 {needed}자. 위 실제 재작성 후보의 마지막 행동 뒤에 '
            '독창적인 한국어 소설 후속 문장만 작성. 현재 인물, 시점, 시간선과 '
            '저장 초고의 사건을 유지. 앞 부분 재출력·임의 요약·'
            '참고작 문장 복제·검수/출판 승인 주장 금지.')
        if author_direction.strip():
            goal += '\n작가 직접 수정 방향: ' + author_direction.strip()[:1000]
        request = SceneDraftRequest(
            project_id, episode, 1, source, goal,
            '직전 실제 장면의 인과를 진행, 설명·분석·목록 형식 출력 금지.',
            '기존 저장 원고의 배경과 동일한 시간 흐름',
            characters, target_chars=needed)
        try:
            addition = draft_scene(request, provider).draft.strip()
        except LocalModelError:
            stopped = 'LOCAL_PROVIDER_INCOMPLETE'
            break
        calls += 1
        if (not addition or addition in candidate
                or has_foreign_script_corruption(addition)
                or len((candidate + '\n\n' + addition).encode('utf-8')) > 100_000):
            stopped = 'DUPLICATE_OR_INVALID_CONTINUATION'
            break
        try:
            overlap = screen_cross_episode_reuse(addition, (candidate,))
            appended = candidate.rstrip() + '\n\n' + addition
            increased = screen_korean_draft(
                appended, target_chars=target_nonspace_chars)
        except ValueError:
            stopped = 'CANDIDATE_LIMIT'
            break
        if (overlap.exact_sentence_reuses
                or increased.nonspace_chars <= current.nonspace_chars
                or increased.hangul_syllables <= current.hangul_syllables):
            stopped = 'NO_ACCEPTABLE_REAL_PROSE_ADDED'
            break
        candidate = appended
    screen = screen_korean_draft(candidate, target_chars=target_nonspace_chars)
    left = max(0, target_nonspace_chars - screen.nonspace_chars)
    if left and stopped == 'TARGET_MET':
        stopped = 'MODEL_CALL_LIMIT'
    return RewriteContinuationResult(
        candidate, target_nonspace_chars, screen.nonspace_chars,
        left, calls, stopped)
