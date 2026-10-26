"""Read-only actual saved chapter bridge at long-form Story Arc boundaries.

Unlike regular recent-chapter recall, the source chapters are the ACTUAL end
of earlier computed Arc ranges, including ranges older than 250 episodes.
Nothing is inferred about events, character feelings or secrets. Only saved
final prose or clearly labeled unreviewed drafts serve as evidence.
A missing previous Arc ending never turns into a made-up story resolution.
No file I/O, local model call, SQLite mutation or literary approval.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .story_arcs import StoryArcPlan, validate_arc_coverage


class SavedArcBridgeError(ValueError):
    """No author-owned prose in error messages."""


@dataclass(frozen=True)
class SavedArcBridge:
    episode: int
    actual_boundaries: tuple[int, ...]
    missing_boundaries: tuple[int, ...]
    first_arc_boundary: int | None
    context: str
    literary_certified: bool = False
    publication_approved: bool = False


def _saved_prose(row: object) -> tuple[str, str]:
    if row is None:
        return '', '본문 누락'
    final = getattr(row, 'final_text', '') or ''
    draft = getattr(row, 'draft', '') or ''
    if type(final) is str and final.strip():
        return final, '작가 저장 최종본(검수 확인은 별도)'
    if type(draft) is str and draft.strip():
        return draft, '저장된 미검수 AI 초고'
    return '', '본문 누락: AI 플롯·요약은 사건 확정으로 사용하지 않음'


def _ends(body: str, *, limit: int) -> str:
    """Quote only the *actual* beginning/end without fabricated summaries."""
    cleaned = body.replace('\x00', '').strip()
    if len(cleaned) <= limit:
        return cleaned
    mark = '\n[저장 본문 중간 생략]\n'
    first = max(24, (limit - len(mark)) // 4)
    last = limit - len(mark) - first
    return cleaned[:first] + mark + cleaned[-last:]


def build_saved_arc_bridge(
    existing: Mapping[int, object], plan: StoryArcPlan,
    next_episode: int, *, max_chars: int = 1500,
) -> SavedArcBridge:
    """Carry genuine chapter endings across previously CLOSED Arc boundaries.

    The latest two closed boundaries and the earliest closed boundary are
    considered, so long-form book openings can remain visible at episode 250
    or 1000. Context is chronological, never ranked as if it were time order.
    The current unfinished Arc ending and ANY future chapter are inaccessible.
    """
    if (not isinstance(existing, Mapping)
            or not isinstance(plan, StoryArcPlan)
            or not validate_arc_coverage(plan)
            or type(next_episode) is not int
            or not 1 <= next_episode <= plan.episode_count
            or type(max_chars) is not int
            or not 800 <= max_chars <= 3000):
        raise SavedArcBridgeError('장편 Arc 저장 원고 연결 범위가 올바르지 않습니다.')
    closed = [arc for arc in plan.arcs if arc.end_episode < next_episode]
    if not closed:
        return SavedArcBridge(next_episode, (), (), None, '')
    # Never make a future/ongoing Arc a completed event. Include a distant
    # opening and recent turns without reading unapproved reference works.
    chosen = [closed[0], *closed[-2:]]
    indices = tuple(sorted({arc.end_episode for arc in chosen}))
    missing: list[int] = []
    found: list[tuple[int, str, str]] = []
    for boundary in indices:
        body, provenance = _saved_prose(existing.get(boundary))
        if body:
            found.append((boundary, provenance, body))
        else:
            missing.append(boundary)
    title = ('[이전 Arc 종료 회차의 실제 SQLite 저장 원고 근거 / '
             'Arc 종료 범위는 기획 구조이고 사건 결말의 승인 아님]\n'
             '아래는 실제 저장 본문의 일부이며 미래 Arc·미저장 회차의 '
             '사건을 추론하거나 앞당기지 말 것.\n')
    footer = ('\n[Arc 경계 원문은 발췌본이며 누락·생략 회차가 '
              '있다면 해당 사건의 발생 여부는 알 수 없음]')
    lines: list[str] = []
    available = max_chars - len(title) - len(footer) - 140
    for pos, (number, kind, body) in enumerate(found):
        remaining = max(1, len(found) - pos)
        allowance = min(490, max(120, available // remaining - 50))
        line = f'- {number}화 Arc 경계 {kind}:\n{_ends(body, limit=allowance)}\n'
        if len(line) > available:
            missing.append(number)
            continue
        lines.append(line)
        available -= len(line)
    if missing:
        note = '[확인 불가 또는 문맥에 수용 못한 이전 Arc 끝 회차: ' + ', '.join(
            str(n) for n in sorted(set(missing))) + '화]\n'
        if len(note) <= available + 140:
            lines.append(note)
    if len(closed) > len(chosen):
        lines.append(f'[이전 Arc 경계 {len(closed)-len(chosen)}개는 '
                     '현재 발췌 대상으로 선택되지 않음]\n')
    text = title + ''.join(lines) + footer
    if len(text) > max_chars:
        # Avoid dropping an unacknowledged author text fragment. A short
        # scope-only notice is always preferable to silently clipping it.
        text = (title
                + '[이전 Arc 근거 일부가 입력 한도를 초과하여 제공되지 않음]\n'
                + footer)
        missing = list(indices)
        found = []
    actual = tuple(number for number, _, _ in found
                   if number not in missing)
    return SavedArcBridge(
        next_episode, actual, tuple(sorted(set(missing))),
        closed[0].end_episode, text)
