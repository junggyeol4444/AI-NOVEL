"""작가가 선택한 실제 AI 회차 기획을 실제 장편 본문 집필에 연결.

AI 기획은 검수 전 참고자료이고, 사용자가 저장한 Novel Bible/인물/관계/
복선보다 우선하지 않는다. 이 모듈은 SQLite 저장·출판·모델 호출이 없다.
선택과 실행 승인은 다른 단계이며, 회차 기획 후보는 오직 작가가 동의한
기존 로컬 AI 집필 실행의 장면 문맥으로만 전달된다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path

from .author_ai_planning import (
    AuthorAiPlanningError, AuthorAiPlanningSource,
    require_current_author_ai_planning_source,
)
from .author_ai_episode_planning import AuthorAiEpisodePlan
from .database.episodes import EpisodeStore


class AuthorAiNovelGuidanceError(ValueError):
    """모델 출력·작품 경로·개인 원고를 오류 메시지에 표시하지 않는다."""


@dataclass(frozen=True)
class AuthorAiNovelGuidance:
    project_id: str = field(repr=False)
    source: AuthorAiPlanningSource = field(repr=False)
    plans: AuthorAiEpisodePlan = field(repr=False)
    through_episode: int = 0
    fingerprint: str = field(default='', repr=False)
    publication_approved: bool = False
    persisted: bool = False


def _fingerprint(source: AuthorAiPlanningSource,
                 plans: AuthorAiEpisodePlan, through: int) -> str:
    """Selected full AI plan text participates; no plan bytes are logged."""
    data = (source.project_id, source.fingerprint,
            plans.source_fingerprint, plans.first_episode,
            plans.last_episode, through, plans.episode_drafts)
    return sha256(json.dumps(
        data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def prepare_author_ai_novel_guidance(
    source: AuthorAiPlanningSource, plans: AuthorAiEpisodePlan,
    *, project_id: str, through_episode: int,
) -> AuthorAiNovelGuidance:
    """Reject interrupted, incomplete, mismatched, or overly large AI plans."""
    if (type(source) is not AuthorAiPlanningSource
            or type(plans) is not AuthorAiEpisodePlan
            or type(project_id) is not str or not project_id
            or source.project_id != project_id
            or source.fingerprint != plans.source_fingerprint
            or type(through_episode) is not int
            or not 1 <= through_episode <= 1000
            or plans.first_episode != 1
            or plans.last_episode < through_episode
            or plans.last_episode > source.planning.through_episode
            or plans.interrupted or plans.persisted
            or plans.publication_approved):
        raise AuthorAiNovelGuidanceError(
            '현재 작품에서 처음부터 요청 끝 회차까지 완성된 '
            '미검수 AI 회차 기획 후보를 직접 선택해야 합니다.')
    if (len(plans.episode_drafts) != plans.last_episode
            or tuple(number for number, _ in plans.episode_drafts)
               != tuple(range(1, plans.last_episode + 1))
            or any(type(body) is not str or not body.strip()
                   or len(body) > 6000 or '\x00' in body
                   for _, body in plans.episode_drafts)):
        raise AuthorAiNovelGuidanceError(
            '선택한 1~N화 AI 기획 중 누락/중복/초과 분량이 있습니다. '
            '원문을 임의 잘라 사용하지 않습니다.')
    return AuthorAiNovelGuidance(
        project_id, source, plans, through_episode,
        _fingerprint(source, plans, through_episode))


def require_current_author_ai_novel_guidance(
    snapshot: AuthorAiNovelGuidance,
    store: EpisodeStore, database_path: str | Path,
    project_id: str, through_episode: int,
) -> None:
    """Capture immediately before any first GGUF call or AI plot persistence."""
    if type(snapshot) is not AuthorAiNovelGuidance:
        raise AuthorAiNovelGuidanceError('작가 AI 회차 기획 선택이 없습니다.')
    latest = prepare_author_ai_novel_guidance(
        snapshot.source, snapshot.plans,
        project_id=project_id, through_episode=through_episode)
    if (snapshot.project_id != project_id
            or snapshot.through_episode != through_episode
            or snapshot.fingerprint != latest.fingerprint):
        raise AuthorAiNovelGuidanceError(
            'AI 회차 기획/회차 범위/작품이 변경되어 실행을 보류했습니다.')
    try:
        require_current_author_ai_planning_source(
            snapshot.source, store, database_path, project_id)
    except (AuthorAiPlanningError, ValueError, OSError):
        raise AuthorAiNovelGuidanceError(
            '작가가 저장한 원래 작품/인물/기획이 변경되어 '
            '예전 AI 후보를 모델에 전달하지 않았습니다.') from None
