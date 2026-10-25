"""기존 저장 작품 설정으로 작가가 승인한 로컬 AI의 장편 기획 후보를 생성한다.

실제 로컬 모델 호출이며 샘플/모의 생성기가 아니다. 사용자가 명시적으로
선택한 실행 파일로만 보내고, 저장된 참고작 원문·사용자 계정·모델을 자동
가져오지 않는다. 결과는 검토 전 임시 후보이며 SQLite·원고·출판 미변경.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Callable
import json

from .author_full_plan_preview import (
    AuthorFullPlanSnapshot, build_author_full_plan,
    require_current_author_full_plan,
)
from .database.episodes import EpisodeStore
from .database.characters import CharacterStore
from .local_models import (
    LocalExecutableProvider, SceneDraftRequest, draft_scene,
)


class AuthorAiPlanningError(ValueError):
    """모델 인수·작품 경로·개인 원고를 표시하지 않는 안내 오류."""


@dataclass(frozen=True)
class AuthorAiPlanningSource:
    project_id: str = field(repr=False)
    planning: AuthorFullPlanSnapshot
    title: str = field(repr=False)
    canon: str = field(repr=False)
    characters: tuple[str, ...] = field(repr=False)
    fingerprint: str = field(repr=False)
    publication_approved: bool = False


@dataclass(frozen=True)
class AuthorAiPlanningDraft:
    source_fingerprint: str = field(repr=False)
    overview: str = field(repr=False)
    arc_drafts: tuple[tuple[int, str], ...] = field(repr=False)
    interrupted: bool = False
    persisted: bool = False
    publication_approved: bool = False

    def as_private_text(self, planning: AuthorFullPlanSnapshot) -> str:
        if self.source_fingerprint == '' or not planning.arcs:
            raise AuthorAiPlanningError('기획 원본을 확인할 수 없습니다.')
        lines = [
            'AI NOVEL FACTORY · 로컬 AI 기획 후보 (미검수·미승인)',
            f'조회 범위: 1~{planning.through_episode}화 / '
            f'저장 총 {planning.total_episodes}화',
            '중단됨 · 미완성' if self.interrupted else '전 아크 생성 호출 완료 · 품질 미검증',
            '',
            '전체 줄거리 기획 후보', self.overview,
        ]
        for number, body in self.arc_drafts:
            arc = next((a for a in planning.arcs if a.number == number), None)
            if arc is None:
                raise AuthorAiPlanningError('기획 아크 범위가 변경되었습니다.')
            lines.extend((
                '', f'아크 {number} ({arc.start_episode}~{arc.end_episode}화)',
                body,
            ))
        return '\n'.join(lines) + '\n'


def capture_author_ai_planning_source(
    store: EpisodeStore, database_path: str | Path, project_id: str, *,
    through_episode: int, arc_option: int = 0, scene_count: int = 3,
) -> AuthorAiPlanningSource:
    """기존 Novel Bible과 인물 입력을 읽기만 하고 스레드용 불변 사본을 만든다."""
    plan = build_author_full_plan(
        store, project_id, through_episode=through_episode,
        arc_option=arc_option, scene_count=scene_count)
    if not 1 <= len(plan.arcs) <= 40:
        raise AuthorAiPlanningError(
            '한 번의 AI 기획은 아크 1~40개만 허용합니다. '
            '아크 수를 조정하거나 조회 범위를 나눠 주세요.')
    project = store.get_project(project_id)
    rules = tuple(sorted(
        ((row.key, row.value, row.revision) for row in store.list_rules(project_id)
         if row.key != 'ai_story_outline_preview'),
        key=lambda item: item[0]))
    with CharacterStore(database_path) as book:
        known = tuple(book.list_characters(project_id))
    if len(known) > 80:
        raise AuthorAiPlanningError('저장된 인물 수가 모델 기획 문맥 한도를 초과했습니다.')
    character_records = tuple(
        (row.character_id, row.revision, row.name, row.personality,
         row.goal, row.speech_style, row.secret) for row in known)
    canon_rows = [f'작품 제목: {project.title}']
    canon_rows.extend(f'{key}: {value}' for key, value, _ in rules)
    canon_rows.extend(
        '작가가 저장한 인물: ' + ' / '.join((
            row.name, '성격 ' + row.personality, '목표 ' + row.goal,
            '말투 ' + row.speech_style, '비밀 ' + row.secret))
        for row in known)
    canon = '\n'.join(canon_rows)
    if not 20 <= len(canon) <= 17000:
        raise AuthorAiPlanningError(
            '기존 작품 설정·인물이 너무 짧거나 로컬 모델 문맥 한도를 초과했습니다. '
            '원본을 임의로 자르지 않고 기획을 보류합니다.')
    names = tuple(row.name for row in known)
    if len(names) > 20:
        raise AuthorAiPlanningError(
            '이번 모델 기획에 포함할 인물이 20명을 초과합니다. '
            '기존 인물 정보를 임의로 누락하지 않습니다.')
    stamp = sha256(json.dumps(
        (plan.source_sha256, project.title, rules, character_records),
        ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
    return AuthorAiPlanningSource(
        project_id, plan, project.title, canon, names or ('미정인 주인공',), stamp)


def require_current_author_ai_planning_source(
    snapshot: AuthorAiPlanningSource,
    store: EpisodeStore, database_path: str | Path, project_id: str,
) -> None:
    """기획 결과 표시·인계 전에 저장 작품 규칙과 인물 변경을 다시 확인."""
    if type(snapshot) is not AuthorAiPlanningSource or snapshot.project_id != project_id:
        raise AuthorAiPlanningError('기획 대상 작품이 변경되었습니다.')
    require_current_author_full_plan(snapshot.planning, store, project_id)
    current = capture_author_ai_planning_source(
        store, database_path, project_id,
        through_episode=snapshot.planning.through_episode,
        arc_option=snapshot.planning.arc_option,
        scene_count=snapshot.planning.scene_count)
    if current.fingerprint != snapshot.fingerprint:
        raise AuthorAiPlanningError(
            '작가 설정 또는 저장된 인물이 변경되었습니다. 다시 직접 기획하세요.')


def generate_author_ai_planning(
    source: AuthorAiPlanningSource, provider: LocalExecutableProvider, *,
    should_stop: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
    resume_from: AuthorAiPlanningDraft | None = None,
) -> AuthorAiPlanningDraft:
    """신규 또는 명시적으로 승인한 중단 후보에서 아크별 실모델 호출을 이어간다.

    재개는 같은 작품 스냅샷의 끊기지 않은 1~N번 아크만 허용한다.
    원고/SQLite/아크 JSON은 건드리지 않으며 기존 후보를 다시 생성하지 않는다.
    """
    if (type(source) is not AuthorAiPlanningSource
            or type(provider) is not LocalExecutableProvider):
        raise AuthorAiPlanningError('승인한 로컬 AI와 최신 작품 기획 선택이 필요합니다.')
    arcs = source.planning.arcs
    if not 1 <= len(arcs) <= 40:
        raise AuthorAiPlanningError('이번 기획의 아크 개수를 다시 확인하세요.')
    if resume_from is not None:
        if (type(resume_from) is not AuthorAiPlanningDraft
                or resume_from.source_fingerprint != source.fingerprint
                or not resume_from.interrupted
                or resume_from.persisted or resume_from.publication_approved
                or not resume_from.overview.strip()
                or len(resume_from.arc_drafts) >= len(arcs)
                or tuple(number for number, _ in resume_from.arc_drafts)
                   != tuple(arc.number for arc in arcs[:len(resume_from.arc_drafts)])
                or any(type(body) is not str or not body.strip()
                       for _, body in resume_from.arc_drafts)):
            raise AuthorAiPlanningError(
                '같은 작품에서 중단된 연속 아크 후보만 재개할 수 있습니다.')
        overview = resume_from.overview
        responses: list[tuple[int, str]] = list(resume_from.arc_drafts)
    else:
        overview = ''
        responses = []
    if should_stop is not None and should_stop():
        return AuthorAiPlanningDraft(
            source.fingerprint, overview, tuple(responses), True)
    if resume_from is None:
        goal = (
        f'사용자가 저장한 Novel Bible만 기준으로 독창적인 장편 '
        f'{source.planning.total_episodes}화 전체 줄거리 및 '
        f'1~{source.planning.through_episode}화 전개, 인물 동기, '
        '아크 갈등과 결말을 새로 구상. 참고작 문장/설정 복제 금지. '
        '검수 전 줄거리 후보 문장만 작성.')
        request = SceneDraftRequest(
            source.project_id, 1, 1, source.canon, goal,
            '인물 목표에 기반한 장기 갈등과 그 해소',
            '작가가 저장한 세계관 안의 장소', source.characters,
            target_chars=1800)
        overview = draft_scene(request, provider).draft
    if should_stop is not None and should_stop():
        return AuthorAiPlanningDraft(
            source.fingerprint, overview, tuple(responses), True)
    for arc in arcs[len(responses):]:
        if should_stop is not None and should_stop():
            return AuthorAiPlanningDraft(source.fingerprint, overview, tuple(responses), True)
        previous_excerpt = (
            '\n[직전 아크의 AI 후보 마지막 1200자 — 미승인, 일부 발췌]\n'
            + responses[-1][1][-1200:] if responses else '')
        synopsis_excerpt = (
            '\n[AI 전체 줄거리 후보 앞 1800자 — 미승인, 일부 발췌]\n'
            + overview[:1800])
        bible = source.canon + synopsis_excerpt + previous_excerpt
        if len(bible) > 24000:
            raise AuthorAiPlanningError(
                '작가 설정과 AI 기획 후보가 모델 문맥 범위를 초과했습니다.')
        details = (
            f'{arc.number}번째 아크, {arc.start_episode}~{arc.end_episode}화. '
            f'전체 {source.planning.total_episodes}화 중 이 아크의 '
            '독창적 사건, 인물 성장, 감정 흐름, 복선 설치/회수, '
            '해결되지 않은 갈등 및 다음 아크 연결을 구체적으로 서술. '
            '앞선 사용자 설정과 전체 줄거리 후보 우선. '
            '참고 작품의 고유 표현/설정 복제 금지. 검토 전 후보만 작성.')
        scene = SceneDraftRequest(
            source.project_id, arc.start_episode, 1,
            bible, details,
            '해당 아크의 원인·행동·결과로 이어지는 갈등',
            '저장된 작품의 가상 세계관', source.characters,
            target_chars=1400)
        if progress is not None:
            progress(arc.number, len(arcs))
        result = draft_scene(scene, provider)
        responses.append((arc.number, result.draft))
    return AuthorAiPlanningDraft(source.fingerprint, overview, tuple(responses))
