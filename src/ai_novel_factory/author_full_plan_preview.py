"""저장된 작품 설정으로 1~1000화 아크·회차·장면 뼈대를 일괄 조회한다.

원래 기획 모듈을 연결한다. 이 기능은 AI 줄거리 생성, 작성자의 기획 승인,
원고 저장, 참고작 분석·독창성 검사, 출판이 아니다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json

from .database.episodes import EpisodeStore
from .planning import PlanningInput, PlanningError, draft_premise
from .story_arcs import StoryArc, plan_story_arcs, validate_arc_coverage
from .episode_planner import EpisodePlan, plan_episodes, validate_episode_plans
from .scene_planner import ScenePlan, plan_scenes, validate_scene_plans


class AuthorFullPlanError(ValueError):
    """오류에 원고·작품명·로컬 경로를 넣지 않는다."""


@dataclass(frozen=True)
class AuthorFullPlanSnapshot:
    project_id: str = field(repr=False)
    total_episodes: int = 0
    through_episode: int = 0
    arc_option: int = 0
    scene_count: int = 0
    source_sha256: str = field(default='', repr=False)
    arcs: tuple[StoryArc, ...] = ()
    episodes: tuple[EpisodePlan, ...] = ()
    status: str = '기획 뼈대 미승인 · AI 실행/저장 없음'
    publication_approved: bool = False


def _saved_planning_input(store: EpisodeStore, project_id: str):
    if not isinstance(store, EpisodeStore) or type(project_id) is not str or not project_id:
        raise AuthorFullPlanError('현재 저장된 작품을 먼저 열어 주세요.')
    project = store.get_project(project_id)
    rows = tuple(sorted(
        ((item.key, item.value, item.revision)
         for item in store.list_rules(project_id)),
        key=lambda item: item[0]))
    values = {key: value for key, value, _ in rows}
    target = values.get('target_episodes', '').strip()
    if not target.isdecimal() or not 1 <= int(target) <= 1000:
        raise AuthorFullPlanError('저장된 목표 회차를 1~1000화로 설정해야 합니다.')
    try:
        spec = PlanningInput(
            values.get('genre', '').strip(),
            values.get('subject', '').strip(),
            int(target),
            values.get('mood', '').strip())
        draft_premise(spec)
    except (PlanningError, ValueError):
        raise AuthorFullPlanError('저장된 장르·소재·분위기·회차 설정을 다시 확인하세요.') from None
    fingerprint = sha256(json.dumps(
        (project_id, project.title, rows), ensure_ascii=False,
        separators=(',', ':')).encode('utf-8')).hexdigest()
    return spec, fingerprint


def build_author_full_plan(
    store: EpisodeStore, project_id: str, *,
    through_episode: int, arc_option: int = 0,
    scene_count: int = 3,
) -> AuthorFullPlanSnapshot:
    """전체 저장 목표의 동일한 Arc 구획으로 1~N화 기획 빈 칸을 표시한다.

    arc_option=0이면 기존 30화당 1개 Arc 기본값을 사용한다. 30화 조회와
    250화 조회가 같은 작품에서 서로 다른 Arc 범위를 추정하지 않도록
    항상 저장된 총 회차 수를 기준으로 구획을 계산한다.
    """
    if (type(through_episode) is not int or not 1 <= through_episode <= 1000
            or type(arc_option) is not int or not 0 <= arc_option <= 1000
            or type(scene_count) is not int or not 1 <= scene_count <= 20):
        raise AuthorFullPlanError('회차·아크·장면 수를 다시 입력하세요.')
    spec, stamp = _saved_planning_input(store, project_id)
    if through_episode > spec.episodes or arc_option > spec.episodes:
        raise AuthorFullPlanError('조회 범위가 저장된 총 회차 수를 초과했습니다.')
    try:
        whole = plan_story_arcs(draft_premise(spec), arc_count=arc_option or None)
        if not validate_arc_coverage(whole):
            raise AuthorFullPlanError('전체 아크의 누락·중복이 있습니다.')
        plans = plan_episodes(whole, maximum=1000)
        if not validate_episode_plans(whole, plans):
            raise AuthorFullPlanError('전체 회차의 누락·중복이 있습니다.')
    except PlanningError:
        raise AuthorFullPlanError('저장된 설정으로 아크·회차를 구성할 수 없습니다.') from None
    return AuthorFullPlanSnapshot(
        project_id, spec.episodes, through_episode, arc_option, scene_count,
        stamp, tuple(arc for arc in whole.arcs if arc.start_episode <= through_episode),
        plans[:through_episode])


def require_current_author_full_plan(
    snapshot: AuthorFullPlanSnapshot, store: EpisodeStore, project_id: str,
) -> None:
    """별도 작가 클릭에서 같은 프로젝트·같은 최신 Novel Bible인지 재확인."""
    if (type(snapshot) is not AuthorFullPlanSnapshot
            or snapshot.project_id != project_id):
        raise AuthorFullPlanError('작품 선택이 변경됐습니다.')
    current = build_author_full_plan(
        store, project_id, through_episode=snapshot.through_episode,
        arc_option=snapshot.arc_option, scene_count=snapshot.scene_count)
    if (current.source_sha256 != snapshot.source_sha256
            or current.arcs != snapshot.arcs
            or current.episodes != snapshot.episodes):
        raise AuthorFullPlanError('저장된 기획 설정이 변경됐습니다. 다시 조회하세요.')


def author_full_plan_scenes(
    snapshot: AuthorFullPlanSnapshot, episode_number: int,
) -> tuple[ScenePlan, ...]:
    if (type(snapshot) is not AuthorFullPlanSnapshot
            or type(episode_number) is not int
            or not 1 <= episode_number <= snapshot.through_episode
            or len(snapshot.episodes) != snapshot.through_episode):
        raise AuthorFullPlanError('선택한 계획 회차가 올바르지 않습니다.')
    episode = snapshot.episodes[episode_number - 1]
    try:
        scenes = plan_scenes(episode, snapshot.scene_count)
    except PlanningError:
        raise AuthorFullPlanError('장면별 기획 빈 칸을 만들 수 없습니다.') from None
    if not validate_scene_plans(episode, scenes):
        raise AuthorFullPlanError('장면 번호·회차 연결이 올바르지 않습니다.')
    return scenes
