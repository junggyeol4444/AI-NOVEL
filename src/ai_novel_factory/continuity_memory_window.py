"""Long-form continuity window from actually saved earlier chapters only.

The writer receives bounded local history, never future events, invented
canon, source-novel prose or a false claim that an AI draft was human-reviewed.
This is a context feature, not a continuity quality PASS or publication gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ContinuityWindow:
    context: str
    episode: int
    prior_saved: int
    missing_prior: int
    milestones_included: int
    omitted_saved: int
    author_approved: bool = False
    quality_certified: bool = False


def _ranges(numbers: list[int], *, limit: int = 8) -> str:
    if not numbers:
        return '없음'
    groups: list[tuple[int, int]] = []
    start = end = numbers[0]
    for number in numbers[1:]:
        if number == end + 1:
            end = number
        else:
            groups.append((start, end))
            start = end = number
    groups.append((start, end))
    shown = groups[:limit]
    value = ', '.join(str(a) if a == b else f'{a}~{b}' for a, b in shown)
    if len(groups) > limit:
        value += f' 외 {len(groups)-limit}개 구간'
    return value


def build_continuity_window(
    existing: Mapping[int, object], next_episode: int, *,
    max_chars: int = 3400, recent_count: int = 8,
) -> ContinuityWindow:
    """Prefer the latest saved prose and long-range milestones.

    Missing chapters and omissions remain explicit. Only the prior 250
    episodes are eligible for prose retrieval; older history is not silently
    declared checked. No reads or writes beyond the provided local objects.
    """
    if type(next_episode) is not int or not 1 <= next_episode <= 1000:
        raise ValueError('집필 회차는 1~1000화 범위여야 합니다.')
    if type(max_chars) is not int or not 900 <= max_chars <= 10000:
        raise ValueError('연속성 문맥 글자 제한이 올바르지 않습니다.')
    if type(recent_count) is not int or not 1 <= recent_count <= 20:
        raise ValueError('최근 회차 개수가 올바르지 않습니다.')
    if next_episode == 1:
        return ContinuityWindow('', next_episode, 0, 0, 0, 0)
    first = max(1, next_episode - 250)
    previous = list(range(first, next_episode))
    saved = [n for n in previous if n in existing]
    missing = [n for n in previous if n not in existing]
    milestones = [n for n in saved if n == 1 or n % 25 == 0]
    recent = saved[-recent_count:]
    chosen = sorted(set(milestones + recent))
    header = (
        '실제 SQLite 이전 회차 참고 기록 (원고·인물·세계관 설정의 최종 승인 아님):\n'
        f'현재 {next_episode}화 / 직전 250화 범위의 저장 회차 {len(saved)}개 / '
        f'누락 {len(missing)}개 ({_ranges(missing)}).\n'
        '최종 원고도 별도 작가 검수·검사 확인이 필요하며, AI 초고·요약은 미확정입니다.\n'
    )
    lines = []
    for n in chosen:
        item = existing[n]
        final = str(getattr(item, 'final_text', '') or '')
        draft = str(getattr(item, 'draft', '') or '')
        summary = str(getattr(item, 'summary', '') or '')
        if final.strip():
            label, excerpt = '저장 최종본(별도 검수 확인 필요)', final[-200:]
        elif draft.strip():
            label, excerpt = '미검수 초고', draft[-200:]
        elif summary.strip():
            label, excerpt = '미확정 AI 요약', summary[:160]
        else:
            label, excerpt = '본문 없음', ''
        lines.append((n, f'- {n}화 {label}: {excerpt.replace(chr(0), "").strip()}\n'))
    # Reserve space for explicit omissions rather than silently dropping them.
    remaining = max_chars - len(header) - 120
    if remaining < 0:
        return ContinuityWindow(header[:max_chars], next_episode,
                                len(saved), len(missing), 0, len(chosen))
    # Latest chapters have first claim; long-range milestones are next.
    priority = sorted(lines, key=lambda row: (row[0] not in recent, -row[0]))
    selected: dict[int, str] = {}
    for n, line in priority:
        if len(line) <= remaining:
            selected[n] = line
            remaining -= len(line)
    omitted = len(chosen) - len(selected)
    footer = (f'[저장된 과거 회차 발췌 {omitted}개 문맥 한도로 생략. '
              f'직전 250화 이전의 회차는 이 범위에서 검사하지 않음.]')
    context = (header + ''.join(selected[n] for n in sorted(selected))
               + '\n' + footer)
    return ContinuityWindow(context[:max_chars], next_episode,
                            len(saved), len(missing),
                            sum(n in selected for n in milestones), omitted)


def extend_scene_context(
    current_context: str, existing: Mapping[int, object], next_episode: int,
    *, max_total_chars: int = 22000,
) -> str:
    """Append only within the existing local-model context budget.

    Preserve the preexisting author Bible and style context byte-for-byte in
    the prefix. If no budget remains, do not displace author-authored facts.
    """
    if type(current_context) is not str or not current_context:
        raise ValueError('기존 집필 문맥이 없습니다.')
    if type(max_total_chars) is not int or max_total_chars < 1000:
        raise ValueError('문맥 제한이 올바르지 않습니다.')
    if len(current_context) >= max_total_chars - 900:
        return current_context[:max_total_chars]
    room = min(3400, max_total_chars - len(current_context) - 2)
    extra = build_continuity_window(existing, next_episode,
                                    max_chars=room).context
    return current_context + '\n\n' + extra if extra else current_context
