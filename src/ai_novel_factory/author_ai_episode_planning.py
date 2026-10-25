"""기존 작가 설정과 승인한 실제 로컬 모델을 이용한 회차별 AI 기획 후보.

1회에 연속 최대 250화(30·100·250화 지원). 원본 Novel Bible/인물은 읽기만 하며
참고작 원문·실제 회차 원고·SQLite·출판을 자동으로 수정하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .author_ai_planning import AuthorAiPlanningSource, AuthorAiPlanningError
from .local_models import (
    LocalExecutableProvider, SceneDraftRequest, draft_scene,
)


MAX_AUTHOR_PLAN_BATCH_EPISODES = 250


def _bounded_episode_history(drafts: list[tuple[int, str]]) -> str:
    """실제 AI가 만든 미검수 기획만 축약해 1화·장기 체크포인트·최근 회차를 이어준다.

    원본 기획 후보 메모리는 수정하지 않으며, 장편 앞부분 앵커와 최근
    회차를 함께 전달한다. 참고작 문장은 이 경로로 들어오지 않는다.
    """
    if not drafts:
        return ''
    anchors = [drafts[0]]
    checkpoints = [row for row in drafts[1:-2] if row[0] % 25 == 0]
    selected = anchors + checkpoints[-4:] + drafts[max(1, len(drafts)-2):]
    dedup = {}
    for number, body in selected:
        dedup[number] = body
    excerpts = []
    for number, body in sorted(dedup.items()):
        budget = 120 if number == drafts[0][0] else (
            250 if number == drafts[-1][0] else 150)
        excerpts.append(
            f'{number}화 실제 AI 기획 후보(미검수·검토 전) 말미: '
            + body[-budget:])
    # This is bounded model-only *AI-generated* excerpts, never source canon.
    context = '\n'.join(excerpts)
    if len(context) > 2100:
        context = (
            excerpts[0][:150] +
            '\n[중간 체크포인트 일부 생략 · 전체 후보는 메모리에 보존]\n'
            + '\n'.join(excerpts[-5:])[-1900:])
    return '\n[기획 장기 연속성 · 사용자 승인 사실 아님]\n' + context



@dataclass(frozen=True)
class AuthorAiEpisodePlan:
    source_fingerprint: str = field(repr=False)
    first_episode: int
    last_episode: int
    episode_drafts: tuple[tuple[int, str], ...] = field(repr=False)
    interrupted: bool = False
    persisted: bool = False
    publication_approved: bool = False

    def private_text(self) -> str:
        if not self.episode_drafts:
            raise AuthorAiPlanningError('보관할 AI 회차별 기획 후보가 없습니다.')
        lines = [
            'AI NOVEL FACTORY · 작가 미검수 로컬 AI 회차별 기획 후보',
            f'요청 회차: {self.first_episode}~{self.last_episode}화',
            '중단 · 일부 회차만 생성' if self.interrupted
            else '요청 회차 호출 완료 · 품질 미검증',
            '원고 저장·아크 저장·검수 승인·출판 승인 없음',
        ]
        for number, body in self.episode_drafts:
            lines.extend(('', f'{number}화 · AI 회차 기획 후보', body))
        return '\n'.join(lines) + '\n'


def _require_episode_scope(
    source: AuthorAiPlanningSource, first: int, last: int,
) -> None:
    if (type(source) is not AuthorAiPlanningSource
            or type(first) is not int or type(last) is not int
            or not 1 <= first <= last <= source.planning.through_episode
            or last - first + 1 > MAX_AUTHOR_PLAN_BATCH_EPISODES
            or len(source.planning.episodes) != source.planning.through_episode):
        raise AuthorAiPlanningError(
            '저장 작품에서 연속 1~250화만 선택하세요. '
            '251~1000화 구간은 분리하여 별도로 승인해야 합니다.')
    if any(source.planning.episodes[number - 1].episode_number != number
           for number in range(first, last + 1)):
        raise AuthorAiPlanningError('기존 회차 뼈대가 변경되었습니다.')


def generate_author_ai_episode_plans(
    source: AuthorAiPlanningSource,
    provider: LocalExecutableProvider,
    first: int, last: int, *,
    should_stop: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
    resume_from: AuthorAiEpisodePlan | None = None,
) -> AuthorAiEpisodePlan:
    """실제 로컬 모델을 1회차당 한 번 호출하고 연속 후보를 메모리에만 보관."""
    _require_episode_scope(source, first, last)
    if type(provider) is not LocalExecutableProvider:
        raise AuthorAiPlanningError('사용자가 승인한 기존 로컬 실행기가 필요합니다.')
    previous: list[tuple[int, str]] = []
    if resume_from is not None:
        if (type(resume_from) is not AuthorAiEpisodePlan
                or resume_from.source_fingerprint != source.fingerprint
                or (resume_from.first_episode, resume_from.last_episode) != (first, last)
                or not resume_from.interrupted
                or resume_from.persisted or resume_from.publication_approved
                or len(resume_from.episode_drafts) >= last - first + 1
                or tuple(n for n, _ in resume_from.episode_drafts)
                   != tuple(range(first, first + len(resume_from.episode_drafts)))
                or any(type(body) is not str or not body.strip()
                       for _, body in resume_from.episode_drafts)):
            raise AuthorAiPlanningError(
                '같은 작품·같은 연속 회차에서 중단된 후보만 재개할 수 있습니다.')
        previous = list(resume_from.episode_drafts)
    if should_stop is not None and should_stop():
        return AuthorAiEpisodePlan(
            source.fingerprint, first, last, tuple(previous), True)
    for number in range(first + len(previous), last + 1):
        if should_stop is not None and should_stop():
            return AuthorAiEpisodePlan(
                source.fingerprint, first, last, tuple(previous), True)
        slot = source.planning.episodes[number - 1]
        arc = next((arc for arc in source.planning.arcs
                    if arc.number == slot.arc_number
                    and arc.start_episode <= number <= arc.end_episode), None)
        if arc is None:
            raise AuthorAiPlanningError('회차에 대응하는 장편 아크가 없습니다.')
        prior_episode_context = _bounded_episode_history(previous)
        canon = (
            source.canon
            + f'\n[현재 장편 구간] 아크 {arc.number}, '
              f'{arc.start_episode}~{arc.end_episode}화. '
              f'전체 목표 {source.planning.total_episodes}화.'
            + prior_episode_context)
        if len(canon) > 24000:
            raise AuthorAiPlanningError(
                '저장된 설정과 회차 문맥이 로컬 모델 한도를 초과했습니다.')
        goal = (
            f'작가 설정에만 근거하여 {number}화의 독창적 상세 기획을 한국어로 작성. '
            f'전체 {source.planning.total_episodes}화, '
            f'아크 {arc.number}({arc.start_episode}~{arc.end_episode}화) 중 '
            f'현재 {number}화의 목표·핵심 사건 3~6개·인물 동기·감정 변화·'
            '복선 설치와 회수·앞뒤 회차 인과·마지막 후킹을 구분하여 제안. '
            '기존 저장 원고를 자동으로 변경하지 말고 참고작 고유 문장을 복제하지 말 것. '
            '실제 집필이 아닌 작가 검토 전 회차 기획 후보만 작성.')
        request = SceneDraftRequest(
            source.project_id, number, 1, canon, goal,
            '장편 인물 목표에 기반한 회차 내 사건의 원인·행동·결과',
            '작가가 저장한 세계관 내 장소', source.characters,
            target_chars=1400)
        if progress is not None:
            progress(number, last)
        candidate = draft_scene(request, provider)
        previous.append((number, candidate.draft))
    return AuthorAiEpisodePlan(
        source.fingerprint, first, last, tuple(previous))
