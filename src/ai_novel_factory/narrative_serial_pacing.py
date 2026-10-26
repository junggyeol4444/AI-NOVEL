"""Non-invented long-form pacing guidance for ACTUAL local GGUF writing.

The deterministic old StoryArcPlan only identifies episode ranges; its
objectives are placeholders and do not specify the opening, middle or end
of an actual 30/100/250 chapter novel. This module translates the position
within the real configured novel and its current arc into explicit narrative
*structural* questions for a local model to answer with fresh prose.

No title, character, relationship, event, foreshadow, or secret is created.
User-authored Novel Bible, plans and scene beats always outrank this guide.
The guide does not assess output quality, approve a manuscript, write SQLite,
or imply the next chapter's undisclosed story facts already occurred.
"""
from __future__ import annotations

from dataclasses import dataclass


class LongformPacingError(ValueError):
    """No original author content or model text in errors."""


@dataclass(frozen=True)
class SerialPacingGoal:
    episode: int
    total_episodes: int
    arc_number: int
    arc_start: int
    arc_end: int
    arc_phase: str
    story_phase: str
    plot_guidance: str
    scene_guidance: str
    ending_guidance: str
    author_plan_overrides: bool = True
    future_events_claimed: bool = False
    quality_certified: bool = False
    publication_approved: bool = False


def _phase(ordinal: int, count: int, label: str) -> tuple[str, str]:
    """Select a structural position, NEVER predict story events."""
    if count == 1:
        return ('압축 단일화',
                f'{label}이 단 한 화에 걸쳐 도입·갈등·전환·정리를 갖추되 '
                '원작자가 지정하지 않은 사건을 덧붙이지 말 것.')
    if ordinal == 1:
        return ('도입', f'{label} 첫 회차: 직전까지 실제 발생한 사실과 연결하고 '
                '새 목표·장애를 행동으로 보여주되 장기 갈등을 바로 해소하지 말 것.')
    if ordinal == count:
        return ('구간 결말', f'{label} 마지막 회차: 작가가 설정한 목표·갈등의 '
                '현재 구간 변화를 실제 인과와 대가로 결산할 것.')
    # 1-based position inclusive; adjust automatically for 30/100/250/1000.
    ratio = (ordinal - 1) / (count - 1)
    if ratio < .35:
        return ('전개', f'{label} 초중반: 인물이 앞선 선택의 대가를 겪게 하고 '
                '새 장애와 행동을 추가하되 같은 사건을 재서술하지 말 것.')
    if ratio < .70:
        return ('누적·전환', f'{label} 중반: 누적된 갈등의 원인과 인물 관계의 '
                '변화를 행동으로 전개하고 후반을 향한 전환을 쌓을 것.')
    return ('후반 수렴', f'{label} 후반: 이미 서술된 사건의 결과를 모아 '
            '구간 결말의 인과를 준비하되 해결이나 비밀 공개를 앞당기지 말 것.')


def plan_local_serial_pacing(
    episode: int, *, total_episodes: int,
    arc_number: int, arc_start: int, arc_end: int,
) -> SerialPacingGoal:
    """Render scope-bounded prose goals from validated range numbers only.

    This method deliberately knows neither author characters nor future
    chapter plans: it cannot reveal or manufacture facts.
    """
    if any(type(v) is not int for v in
           (episode, total_episodes, arc_number, arc_start, arc_end)):
        raise LongformPacingError('회차·장편 Arc 번호는 정수여야 합니다.')
    if not (1 <= episode <= total_episodes <= 1000
            and 1 <= arc_number <= total_episodes
            and 1 <= arc_start <= episode <= arc_end <= total_episodes):
        raise LongformPacingError('장편 회차와 해당 Arc 범위가 일치하지 않습니다.')
    arc_order = episode - arc_start + 1
    arc_count = arc_end - arc_start + 1
    arc_phase, arc_rule = _phase(arc_order, arc_count, f'{arc_number}번째 Arc')
    story_phase, story_rule = _phase(episode, total_episodes, '전체 장편')
    boundary = (
        '이번 화가 작품의 최종화이므로 이미 원고에 제시된 주요 갈등의 '
        '실제 귀결과 인물 선택의 대가를 완결하되, 작가의 직접 열린 결말 '
        '지시가 있다면 그 지시를 우선할 것. '
        '다음 화를 반드시 암시하거나 미확정 복선을 자동 생성하지 말 것.'
        if episode == total_episodes else
        '이번 화가 현 Arc 끝이므로 이 구간의 직접적 결과를 정리하면서 '
        '이미 작성한 사건에서만 다음 Arc의 자연스러운 연결을 남길 것. '
        '전체 작품의 최종 결말을 미리 확정하지 말 것.'
        if episode == arc_end else
        '이번 화의 선택·대가·미해결 질문은 현재 Arc 구간에서만 진전시키고 '
        '미래 회차에 예정된 사건과 비밀을 미리 실제 발생한 일로 만들지 말 것.'
    )
    header = (f'[장편 실제 집필 진행 위치: {episode}/{total_episodes}화, '
              f'Arc {arc_number} {arc_order}/{arc_count}화. '
              '작가의 직접 기획·Novel Bible·원고·인물 사실보다 우선하지 '
              '않는 구조적 템포 지시. 사건을 자동 추가하는 기획 아님.]')
    plot = (
        header + '\n' + arc_rule + '\n' + story_rule + '\n' + boundary
        + '\n이전 실제 저장 회차와 현재 인물의 목표·행동에서 원인을 '
        '받고 이 회차에 새로운 결과가 남도록 서술할 것.'
    )
    scene = (
        f'장편 진행 {episode}/{total_episodes}화, Arc {arc_number} '
        f'{arc_order}/{arc_count}: {arc_phase}. '
        '현재 배정된 장면 사건을 처음부터 끝까지 새로운 소설 문장으로 '
        '진전시키고 작가가 직접 지정한 장면 계획을 우선할 것. '
        + ('작품 최종화이므로 기존 소설 갈등의 인과를 실제로 매듭지을 것.'
           if episode == total_episodes
           else '다음 화·장면의 결과를 앞당겨 확정하지 말 것.')
    )
    ending = (
        '작품 최종화: 기존 사건·선택의 귀결을 닫고 '
        '인물 목표의 결산을 다루되 작가의 명시적 열린 결말은 우선.'
        if episode == total_episodes else
        'Arc 경계: 앞선 장면에서 실제 일어난 변화의 대가를 서술하고 '
        '이전 사실에 근거한 다음 Arc의 연결만 유지.'
        if episode == arc_end else
        '연재 중간화: 현재 갈등은 인과적으로 진행하되 작품 전체 결말이나 '
        '미래 공개 사건을 이번 화에서 임의 확정하지 말 것.'
    )
    return SerialPacingGoal(
        episode, total_episodes, arc_number, arc_start, arc_end,
        arc_phase, story_phase, plot, scene, ending)
