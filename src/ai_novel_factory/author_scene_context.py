"""Bind exact author scene beats to an episode/scene in an approved local batch.

The author may opt in. Missing, stale or altered plans BLOCK rather than
fall back to invented beats; no silent truncation and no quality certification.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from .database.episodes import EpisodeStore
from .author_arc_ledger import canon_fingerprint, arc_ledger_fingerprint
from .author_scene_plan import (AuthorScenePlanError, read_author_scene_plans,
                                scene_plan_fingerprint)


@dataclass(frozen=True)
class AuthorSceneContext:
    episode: int
    scene_count: int
    outline_context: str = field(repr=False)
    scene_contexts: tuple[str, ...] = field(repr=False)
    ledger_sha256: str = field(repr=False)
    missing: bool = False
    stale: bool = False
    quality_certified: bool = False
    publication_approved: bool = False


def build_author_scene_context(store: EpisodeStore, project_id: str, *,
                               episode: int, scenes_per_episode: int,
                               folder: str | Path,
                               arc_folder: str | Path | None = None,
                               expected_ledger_sha256: str | None = None,
                               max_outline_chars: int = 3500,
                               max_scene_chars: int = 1700) -> AuthorSceneContext:
    if (type(episode) is not int or not 1 <= episode <= 1000
            or type(scenes_per_episode) is not int or not 1 <= scenes_per_episode <= 20
            or type(max_outline_chars) is not int or not 500 <= max_outline_chars <= 10000
            or type(max_scene_chars) is not int or not 500 <= max_scene_chars <= 5000):
        raise AuthorScenePlanError('장면 문맥 범위 또는 글자 제한이 올바르지 않습니다.')
    stamp = scene_plan_fingerprint(folder)
    if expected_ledger_sha256 is not None and stamp != expected_ledger_sha256:
        raise AuthorScenePlanError('작가 장면 계획 기록이 변경되었습니다. 새 승인이 필요합니다.')
    selected = [p for p in read_author_scene_plans(folder, project_id)
                if not p.revoked and p.episode == episode]
    if not selected:
        return AuthorSceneContext(episode, scenes_per_episode, '', (), stamp, missing=True)
    if len(selected) != 1:
        raise AuthorScenePlanError('이 회차의 장면 계획이 중복되었습니다.')
    plan = selected[0]
    if len(plan.beats) != scenes_per_episode:
        raise AuthorScenePlanError('작가 장면 수와 이번 배치의 장면 수가 다릅니다.')
    stale = plan.canon_sha256 != canon_fingerprint(store, project_id)
    if plan.arc_sha256 is not None:
        stale = stale or (arc_folder is None or
                          plan.arc_sha256 != arc_ledger_fingerprint(arc_folder))
    if stale:
        return AuthorSceneContext(episode, scenes_per_episode, '', (), stamp, stale=True)
    summary = ('[작가 직접 장면 설계표: AI 집필 참고/미검수]\n'
               f'{episode}화 · 총 {scenes_per_episode}장면\n')
    details = []
    for number, beat in enumerate(plan.beats, start=1):
        summary += f'{number}장면 목표: {beat.goal}\n'
        detail = ('[작가 직접 지정한 장면 계획/미검수]\n'
                  f'장면 {number}/{scenes_per_episode}\n'
                  f'목표: {beat.goal}\n갈등: {beat.conflict}\n'
                  f'장소: {beat.place}\n반드시 포함할 사건: {beat.must_include}\n'
                  f'포함하지 말 사건: {beat.avoid}\n'
                  '작가 Novel Bible·회차별 확정 설정 우선. 원문 문장 복제 금지.')
        if len(detail) > max_scene_chars:
            raise AuthorScenePlanError('작가 장면 문맥이 제한을 초과해 집필을 보류했습니다.')
        details.append(detail)
    if len(summary) > max_outline_chars:
        raise AuthorScenePlanError('전체 장면 개요가 제한을 초과해 집필을 보류했습니다.')
    return AuthorSceneContext(episode, scenes_per_episode, summary,
                              tuple(details), stamp)


def require_author_scene_context(context: AuthorSceneContext) -> AuthorSceneContext:
    if (not isinstance(context, AuthorSceneContext) or context.missing
            or context.stale or not context.outline_context
            or len(context.scene_contexts) != context.scene_count):
        raise AuthorScenePlanError('해당 회차의 최신 작가 장면 계획이 없어 집필을 보류했습니다.')
    return context
