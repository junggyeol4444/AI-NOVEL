"""Causal handoff from real saved episode N-1 to native GGUF episode N.

The current chapter opening can depend on what *actually happened* at the
previous chapter's end instead of carrying only an outline or a summary.
No model is invoked, no SQLite rows are written and no story events are
invented. All excerpt labels explicitly preserve draft versus saved-final
provenance; neither is assumed to have been approved by the author.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class SavedChapterBridge:
    target_episode: int
    source_episode: int | None
    source_kind: str
    prior_missing: bool
    plot_context: str
    first_scene_context: str
    saved_prose_available: bool
    quality_certified: bool = False
    approved: bool = False


def _excerpt(value: str, *, front: int, end: int) -> str:
    """Retain exact actual character bytes; disclose every discarded middle."""
    if type(value) is not str:
        return ''
    value = value.strip().replace('\x00', '')
    if not value:
        return ''
    if len(value) <= front + end + 18:
        return value
    return value[:front] + '\n[…실제 저장 본문 중간 생략…]\n' + value[-end:]


def build_saved_chapter_bridge(
    existing: Mapping[int, object], target_episode: int,
    *, max_plot_chars: int = 1250,
    max_first_scene_chars: int = 2000,
) -> SavedChapterBridge:
    """Capture the immediately preceding saved chapter's literal prose ending.

    Only previous N-1 can be used as the *immediate* cause. Earlier chapters
    and future AI guides must never substitute for a missing N-1 chapter.
    Plot may be used only as unapproved metadata, not text that occurred.
    """
    if (type(target_episode) is not int or not 1 <= target_episode <= 1000
            or type(max_plot_chars) is not int
            or not 700 <= max_plot_chars <= 2400
            or type(max_first_scene_chars) is not int
            or not 1100 <= max_first_scene_chars <= 3500):
        raise ValueError('회차 인과 연결 문맥 범위가 올바르지 않습니다.')
    if target_episode == 1:
        return SavedChapterBridge(1, None, '', False, '', '', False)
    source_episode = target_episode - 1
    row = existing.get(source_episode)
    if row is None:
        return SavedChapterBridge(
            target_episode, source_episode, '', True,
            f'[직전 {source_episode}화의 저장 원고가 없음: 그 회차의 결말을 '
            '상상해 사실로 쓰지 말 것. 작가 Novel Bible 우선.]',
            f'[직전 {source_episode}화 원고 누락: 장면1이 이전 회차의 '
            '확정된 결과를 이어받는다고 단정하지 말 것.]', False)
    final = getattr(row, 'final_text', '') or ''
    draft = getattr(row, 'draft', '') or ''
    plot = getattr(row, 'plot', '') or ''
    summary = getattr(row, 'summary', '') or ''
    if type(final) is str and final.strip():
        prose, kind = final, '저장 최종본(별도 작가 승인 확인 필요)'
    elif type(draft) is str and draft.strip():
        prose, kind = draft, '저장 AI 미검수 초고'
    else:
        prose, kind = '', '저장된 실제 본문 없음'
    prose = prose.strip() if type(prose) is str else ''
    plot = plot.strip() if type(plot) is str else ''
    summary = summary.strip() if type(summary) is str else ''

    common = (
        f'[실제 로컬 SQLite {source_episode}화 → {target_episode}화 인과 연결 / '
        '확정 캐논·품질 인증 아님]\n'
        f'{source_episode}화 출처: {kind}.\n'
        '이전 회차 말미의 이미 발생한 행동·대사에 따른 결과에서 '
        '새 사건을 진행하고, 이전 문장을 그대로 반복하지 말 것.\n'
        'Novel Bible의 작가 설정·시점별 비밀·관계 및 '
        '서술 시점 지시가 충돌하면 그것을 우선할 것.\n'
    )
    if not prose:
        fallback = summary or plot
        if not fallback:
            content = (
                '직전 회차에 본문·저장 플롯·요약이 없음. '
                '없는 사건을 확정된 일처럼 만들지 말 것.')
        else:
            content = (
                '직전 회차에 실제 본문 없음. 다음은 사건 사실이 아닌 '
                '미확정 저장 요약 또는 플롯 후보:\n'
                + _excerpt(fallback, front=160, end=440))
        plot_context = (common + content)[:max_plot_chars]
        scene_context = (common + content)[:max_first_scene_chars]
        return SavedChapterBridge(
            target_episode, source_episode, kind, False,
            plot_context, scene_context, False)

    # The native model gives only 12k characters to the Novel Bible field.
    # The immediately preceding prose END must survive our 1250/2000 budgets.
    # Header and omission markers are authored directions, never fake scenes.
    shortened_plot = _excerpt(
        prose, front=0, end=max(100, max_plot_chars - len(common) - 120))
    shortened_scene = _excerpt(
        prose, front=190, end=max(180, max_first_scene_chars - len(common) - 320))
    plot_context = (common + '직전 회차 저장 본문 끝:\n'
                    + shortened_plot)[-max_plot_chars:]
    scene_context = (common + '직전 회차의 첫 부분과 실제 결말(중간 생략 표시):\n'
                     + shortened_scene)[-max_first_scene_chars:]
    return SavedChapterBridge(
        target_episode, source_episode, kind, False, plot_context,
        scene_context, True)
